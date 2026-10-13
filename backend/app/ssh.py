"""Root SSH transport; authenticate only after verifying the pinned host key."""

import base64
import hashlib
import io
import json
import socket
import time
from pathlib import Path

import paramiko

from .security import AppError


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def transport(host, port):
    sock = socket.create_connection((host, port), timeout=15)
    t = paramiko.Transport(sock)
    try:
        t.start_client(timeout=15)
        return t
    except Exception:
        t.close()
        raise


def discover(host, port):
    t = transport(host, port)
    try:
        return {
            "fingerprint": fingerprint(t.get_remote_server_key()),
            "algorithm": t.get_remote_server_key().get_name(),
        }
    finally:
        t.close()


def private_key(secret, passphrase=""):
    for kind in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return kind.from_private_key(io.StringIO(secret), password=passphrase or None)
        except (paramiko.SSHException, ValueError):
            pass
    raise AppError("invalid_key")


class Remote:
    def __init__(self, server, credential, namespace):
        self.server = server
        self.ns = namespace
        self.t = transport(server["host"], server["ssh_port"])
        try:
            if fingerprint(self.t.get_remote_server_key()) != server["fingerprint"]:
                raise AppError("host_key_changed")
            if credential["kind"] == "password":
                self.t.auth_password("root", credential["secret"])
            else:
                self.t.auth_publickey(
                    "root",
                    private_key(credential["secret"], credential.get("passphrase", "")),
                )
            self.t.set_keepalive(20)
            if not self.t.is_authenticated():
                raise AppError("ssh_auth")
        except Exception:
            self.t.close()
            raise

    def close(self):
        self.t.close()

    def command(self, command, data=b"", timeout=360):
        ch = self.t.open_session(timeout=15)
        ch.settimeout(15)
        ch.exec_command(command)
        if data:
            ch.sendall(data)
        ch.shutdown_write()
        output = bytearray()
        start = time.monotonic()
        try:
            while True:
                for ready, recv in (
                    (ch.recv_ready, ch.recv),
                    (ch.recv_stderr_ready, ch.recv_stderr),
                ):
                    if ready():
                        output.extend(recv(32768))
                        if len(output) > 2_000_000:
                            raise RuntimeError("output_limit")
                if ch.exit_status_ready() and not ch.recv_ready() and not ch.recv_stderr_ready():
                    break
                if time.monotonic() - start > timeout:
                    raise TimeoutError("remote_timeout")
                time.sleep(0.05)
            code = ch.recv_exit_status()
            if code:
                raise RuntimeError(
                    "remote_command_failed"
                )  # Remote output can contain credentials; never echo it.
            return output.decode(errors="replace")
        finally:
            ch.close()

    def install_agent(self):
        self.command(
            "command -v python3 >/dev/null || (DEBIAN_FRONTEND=noninteractive apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3)"
        )
        path = "/var/lib/tunnel-manager/" + self.ns
        self.command("install -d -m 700 " + path)
        sftp = paramiko.SFTPClient.from_transport(self.t)
        try:
            with sftp.file(path + "/agent.py.tmp", "w") as f:
                f.write(Path(__file__).with_name("remote_agent.py").read_bytes())
            sftp.chmod(path + "/agent.py.tmp", 0o700)
            sftp.posix_rename(path + "/agent.py.tmp", path + "/agent.py")
        finally:
            sftp.close()

    def call(self, action, payload):
        raw = self.command(
            "python3 /var/lib/tunnel-manager/" + self.ns + "/agent.py",
            json.dumps({"namespace": self.ns, "action": action, **payload}).encode(),
            timeout=1200 if action == "prepare" else 360,
        )
        result = json.loads(raw)
        if not result.get("ok"):
            details = result.get("detail", {})
            safe = {}
            if result.get("code") == "listener_conflict":
                from ipaddress import ip_address

                if (
                    details.get("protocol") in ("tcp", "udp")
                    and isinstance(details.get("port"), int)
                    and 1 <= details["port"] <= 65535
                ):
                    address = details.get("address", "")
                    if address not in ("*", "0.0.0.0", "::"):
                        address = str(ip_address(address))
                    safe = {
                        "protocol": details["protocol"],
                        "port": details["port"],
                        "address": address,
                        "server_id": self.server["id"],
                    }
            if result.get("code") == "outgoing_port_capacity":
                from ipaddress import ip_address

                if (
                    type(details.get("start")) is int
                    and type(details.get("end")) is int
                    and 1 <= details["start"] <= details["end"] <= 65535
                ):
                    safe = {
                        "start": details["start"],
                        "end": details["end"],
                        "address": str(ip_address(details["address"])),
                        "server_id": self.server["id"],
                    }
            if result.get("code") == "descriptor_capacity":
                safe = {
                    key: value
                    for key, value in details.items()
                    if key in ("required", "available") and type(value) is int and value >= 0
                }
                safe["server_id"] = self.server["id"]
            raise AppError(result.get("code", "remote_failed"), details=safe)
        return result
