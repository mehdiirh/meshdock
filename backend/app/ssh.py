"""Root SSH transport; authenticate only after verifying the pinned host key."""

import base64
import hashlib
import io
import json
import socket
import time
from contextlib import suppress
from pathlib import Path

import paramiko

from .diagnostics import health_details
from .security import AppError


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def transport(host, port, sock=None):
    sock = sock if sock is not None else socket.create_connection((host, port), timeout=15)
    session = None
    try:
        session = paramiko.Transport(sock)
        session.auth_timeout = 15
        session.banner_timeout = 15
        session.start_client(timeout=15)
        return session
    except Exception:
        if session is not None:
            session.close()
        sock.close()
        raise


def authenticate(session, endpoint, credential, *, jump=False):
    prefix = "ssh_jump_" if jump else ""
    if fingerprint(session.get_remote_server_key()) != endpoint["fingerprint"]:
        raise AppError(prefix + "host_key_changed")
    try:
        username = endpoint.get("username", "root") if jump else "root"
        if credential["kind"] == "password":
            session.auth_password(username, credential["secret"])
        else:
            session.auth_publickey(
                username, private_key(credential["secret"], credential.get("passphrase", ""))
            )
        if not session.is_authenticated():
            raise paramiko.AuthenticationException()
        session.set_keepalive(20)
    except (paramiko.SSHException, OSError):
        raise AppError("ssh_jump_auth" if jump else "ssh_auth") from None


class SSHConnection:
    """An end-to-end SSH session, optionally carried by a pinned jump host."""

    def __init__(self, endpoint, credentials=None, *, discover_only=False):
        self.target = None
        self.jump = None
        self.channel = None
        jump = endpoint.get("ssh_jump")
        try:
            if jump:
                try:
                    self.jump = transport(jump["host"], jump["ssh_port"])
                except (OSError, paramiko.SSHException):
                    raise AppError("ssh_jump_unreachable", 502) from None
                authenticate(self.jump, jump, credentials["jump"], jump=True)
                try:
                    self.channel = self.jump.open_channel(
                        "direct-tcpip",
                        dest_addr=(endpoint["host"], endpoint["ssh_port"]),
                        src_addr=("127.0.0.1", 0),
                        timeout=15,
                    )
                except (OSError, paramiko.SSHException):
                    raise AppError("ssh_jump_forward_failed", 502) from None
            try:
                if self.channel is None:
                    self.target = transport(endpoint["host"], endpoint["ssh_port"])
                else:
                    self.target = transport(endpoint["host"], endpoint["ssh_port"], self.channel)
            except (OSError, paramiko.SSHException):
                raise AppError("ssh_unreachable", 502) from None
            if not discover_only:
                authenticate(self.target, endpoint, credentials)
        except Exception:
            self.close()
            raise

    def close(self):
        for name in ("target", "channel", "jump"):
            resource = getattr(self, name)
            if resource is not None:
                setattr(self, name, None)
                with suppress(Exception):
                    resource.close()


def discover(host, port, jump=None, jump_credential=None):
    connection = SSHConnection(
        {"host": host, "ssh_port": port, "ssh_jump": jump},
        {"jump": jump_credential},
        discover_only=True,
    )
    try:
        key = connection.target.get_remote_server_key()
        return {"fingerprint": fingerprint(key), "algorithm": key.get_name()}
    finally:
        connection.close()


def private_key(secret, passphrase=""):
    for kind in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return kind.from_private_key(io.StringIO(secret), password=passphrase or None)
        except (paramiko.SSHException, ValueError):
            pass
    raise AppError("invalid_key")


PROGRESS_CODES = {
    "dependencies_checking",
    "packages_installing",
    "dependencies_ready",
    "binary_downloading",
    "binary_verified",
    "preflight_checking",
    "preflight_passed",
    "configuration_validating",
    "configuration_ready",
}


def progress_event(line):
    try:
        event = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    if (
        not isinstance(event, dict)
        or not isinstance(event.get("event"), str)
        or event["event"] not in PROGRESS_CODES
    ):
        return None
    detail = event.get("detail", {})
    safe = {}
    packages = detail.get("packages", []) if isinstance(detail, dict) else []
    allowed = {
        "haproxy",
        "iproute2",
        "iptables",
        "ca-certificates",
        "openssh-server",
        "openssh-client",
        "iputils-ping",
        "conntrack",
    }
    if (
        isinstance(packages, list)
        and packages
        and all(isinstance(p, str) and p in allowed for p in packages)
    ):
        safe["packages"] = packages
    if (
        isinstance(detail, dict)
        and isinstance(detail.get("binary"), str)
        and detail["binary"]
        in {
            "backhaul",
            "rathole",
            "frpc",
            "frps",
            "hysteria",
        }
    ):
        safe["binary"] = detail["binary"]
    return event["event"], safe


class Remote:
    def __init__(self, server, credential, namespace):
        self.on_progress = None
        self.server = server
        self.ns = namespace
        try:
            self.connection = SSHConnection(server, credential)
            self.t = self.connection.target
        except AppError as error:
            error.details = {"server_id": server["id"]}
            raise

    def close(self):
        self.connection.close()

    def command(self, command, data=b"", timeout=360, stream=False):
        ch = self.t.open_session(timeout=15)
        ch.settimeout(15)
        ch.exec_command(command)
        if data:
            ch.sendall(data)
        ch.shutdown_write()
        output = bytearray()
        pending = bytearray()
        start = time.monotonic()
        try:
            while True:
                for ready, recv in (
                    (ch.recv_ready, ch.recv),
                    (ch.recv_stderr_ready, ch.recv_stderr),
                ):
                    if ready():
                        chunk = recv(32768)
                        output.extend(chunk)
                        if stream:
                            pending.extend(chunk)
                            while b"\n" in pending:
                                line, _, remainder = pending.partition(b"\n")
                                pending = bytearray(remainder)
                                event = progress_event(line)
                                if event and self.on_progress:
                                    self.on_progress(*event)
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
            text = output.decode(errors="replace")
            if stream:
                text = "\n".join(line for line in text.splitlines() if not progress_event(line))
            return text
        finally:
            ch.close()

    def install_agent(self):
        self.command(
            "command -v python3 >/dev/null || (DEBIAN_FRONTEND=noninteractive apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3)"
        )
        path = "/var/lib/meshdock/" + self.ns
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
            "python3 /var/lib/meshdock/" + self.ns + "/agent.py",
            json.dumps({"namespace": self.ns, "action": action, **payload}).encode(),
            timeout=1200 if action == "prepare" else 360,
            stream=True,
        )
        result = json.loads(raw)
        if not result.get("ok"):
            details = result.get("detail", {})
            if not isinstance(details, dict):
                details = {}
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
            if result.get("code") == "health_failed":
                safe = health_details(details)
            if details.get("command") in {
                "apt-get",
                "env",
                "haproxy",
                "sshd",
                "systemctl",
                "iptables",
                "iptables-restore",
                "ip",
            }:
                safe["command"] = details["command"]
            if type(details.get("exit_code")) is int:
                safe["exit_code"] = details["exit_code"]
            safe["server_id"] = self.server["id"]
            raise AppError(result.get("code", "remote_failed"), details=safe)
        return result
