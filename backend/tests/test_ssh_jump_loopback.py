"""Opt-in real SSH/SFTP over a loopback-only jump; never uses inventory hosts."""

import io
import os
import select
import socket
import threading
import time
from contextlib import contextmanager, suppress
from pathlib import Path

import paramiko
import pytest
from app.security import AppError
from app.ssh import Remote, discover, fingerprint

pytestmark = pytest.mark.skipif(
    os.getenv("MESHDOCK_TEST_SSH_LOOPBACK") != "1",
    reason="Opt in to isolated loopback SSH servers with MESHDOCK_TEST_SSH_LOOPBACK=1",
)


class Files(paramiko.SFTPServerInterface):
    def __init__(self, server, *, folder):
        super().__init__(server)
        self.folder = folder

    def open(self, path, flags, attr):
        target = self.folder / Path(path).name
        descriptor = os.open(target, flags, 0o600)
        file = os.fdopen(
            descriptor, "r+b" if flags & os.O_RDWR else "wb" if flags & os.O_WRONLY else "rb"
        )
        handle = paramiko.SFTPHandle(flags)
        handle.readfile = file
        handle.writefile = file
        return handle

    def stat(self, path):
        return paramiko.SFTPAttributes.from_stat((self.folder / Path(path).name).stat())


@contextmanager
def ssh_server(folder, *, destination=None, deny_forward=False):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.2)
    host_key = paramiko.RSAKey.generate(2048)
    login_key = paramiko.RSAKey.generate(2048)
    username = "jump-user" if destination else "root"
    password = "jump-fixture-password" if destination else "target-fixture-password"
    stop = threading.Event()
    sessions, channels, workers, auth, destinations, errors = [], [], [], [], [], []

    class Handler(paramiko.ServerInterface):
        def get_allowed_auths(self, user):
            return "password,publickey"

        def check_auth_password(self, user, secret):
            auth.append((user, "password"))
            return (
                paramiko.AUTH_SUCCESSFUL
                if user == username and secret == password
                else paramiko.AUTH_FAILED
            )

        def check_auth_publickey(self, user, key):
            auth.append((user, "key"))
            return (
                paramiko.AUTH_SUCCESSFUL
                if user == username and key == login_key
                else paramiko.AUTH_FAILED
            )

        def check_channel_request(self, kind, channel_id):
            return (
                paramiko.OPEN_SUCCEEDED
                if kind == "session" and not destination
                else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
            )

        def check_channel_direct_tcpip_request(self, channel_id, origin, address):
            destinations.append(address)
            return (
                paramiko.OPEN_SUCCEEDED
                if destination and not deny_forward
                else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
            )

        def check_channel_exec_request(self, channel, command):
            if command != b"fixture-read-only":
                return False

            def reply():
                time.sleep(0.03)
                channel.sendall(b"target-ssh-ok\n")
                channel.send_exit_status(0)
                channel.shutdown_write()

            thread = threading.Thread(target=reply, daemon=True)
            workers.append(thread)
            thread.start()
            return True

    def relay(channel):
        peer = socket.create_connection(destination, timeout=3)
        try:
            while not stop.is_set() and not channel.closed:
                readable, _, _ = select.select([peer, channel], [], [], 0.2)
                for source in readable:
                    data = source.recv(32768)
                    if not data:
                        return
                    (channel if source is peer else peer).sendall(data)
        except (OSError, EOFError):
            pass
        finally:
            peer.close()
            with suppress(OSError, EOFError):
                channel.close()

    def serve(connection):
        session = paramiko.Transport(connection)
        sessions.append(session)
        session.add_server_key(host_key)
        session.set_subsystem_handler("sftp", paramiko.SFTPServer, Files, folder=folder)
        try:
            session.start_server(server=Handler())
            while not stop.is_set() and session.is_active():
                channel = session.accept(0.2)
                if channel is None:
                    continue
                channels.append(channel)
                if destination:
                    thread = threading.Thread(target=relay, args=(channel,), daemon=True)
                    workers.append(thread)
                    thread.start()
        except (EOFError, OSError, paramiko.SSHException):
            # Negative pin/auth tests deliberately disconnect during negotiation.
            pass
        except Exception as error:
            errors.append(error)
        finally:
            session.close()

    def accept():
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            thread = threading.Thread(target=serve, args=(connection,), daemon=True)
            workers.append(thread)
            thread.start()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    pem = io.StringIO()
    login_key.write_private_key(pem)
    try:
        yield {
            "host": "127.0.0.1",
            "ssh_port": listener.getsockname()[1],
            "fingerprint": fingerprint(host_key),
            "username": username,
            "password": {"kind": "password", "secret": password},
            "key": {"kind": "key", "secret": pem.getvalue()},
            "auth": auth,
            "destinations": destinations,
        }
    finally:
        stop.set()
        listener.close()
        for session in sessions:
            session.close()
        thread.join(timeout=2)
        for worker in workers:
            worker.join(timeout=2)
        assert not errors


def endpoint(target, jump):
    return {
        "id": "a" * 32,
        # Only the jump resolves/reaches this synthetic name. No direct socket
        # to this name is available to the controller-side implementation.
        "host": "target.internal",
        "ssh_port": target["ssh_port"],
        "fingerprint": target["fingerprint"],
        "ssh_jump": {key: jump[key] for key in ("host", "ssh_port", "fingerprint", "username")},
    }


@pytest.mark.parametrize("kind", ["password", "key"])
def test_real_ssh_discovery_commands_and_sftp_through_jump(tmp_path, kind):
    with ssh_server(tmp_path) as target:
        with ssh_server(tmp_path, destination=(target["host"], target["ssh_port"])) as jump:
            server = endpoint(target, jump)
            result = discover(server["host"], server["ssh_port"], server["ssh_jump"], jump[kind])
            assert result["fingerprint"] == target["fingerprint"]
            assert target["auth"] == []
            remote = Remote(server, {**target[kind], "jump": jump[kind]}, "fixture")
            try:
                assert remote.command("fixture-read-only", timeout=5) == "target-ssh-ok\n"
                with paramiko.SFTPClient.from_transport(remote.t) as sftp:
                    sftp.putfo(io.BytesIO(b"synthetic-agent-fixture"), "/agent-fixture")
                    with sftp.open("/agent-fixture", "rb") as file:
                        assert file.read() == b"synthetic-agent-fixture"
            finally:
                remote.close()
            assert target["auth"] == [("root", kind)]
            assert jump["auth"] == [("jump-user", kind)] * 2
            assert jump["destinations"] == [("target.internal", target["ssh_port"])] * 2


@pytest.mark.parametrize("hop", ["jump", "target"])
def test_real_ssh_pin_failure_precedes_authentication(tmp_path, hop):
    with ssh_server(tmp_path) as target:
        with ssh_server(tmp_path, destination=(target["host"], target["ssh_port"])) as jump:
            server = endpoint(target, jump)
            (server["ssh_jump"] if hop == "jump" else server)["fingerprint"] = "SHA256:" + "X" * 43
            with pytest.raises(AppError) as exc:
                Remote(server, {**target["password"], "jump": jump["password"]}, "fixture")
            assert exc.value.code == (
                "ssh_jump_host_key_changed" if hop == "jump" else "host_key_changed"
            )
            assert (jump if hop == "jump" else target)["auth"] == []


def test_real_jump_forwarding_denial_is_actionable(tmp_path):
    with ssh_server(tmp_path) as target:
        with ssh_server(
            tmp_path, destination=(target["host"], target["ssh_port"]), deny_forward=True
        ) as jump:
            with pytest.raises(AppError) as exc:
                Remote(
                    endpoint(target, jump),
                    {**target["password"], "jump": jump["password"]},
                    "fixture",
                )
            assert exc.value.code == "ssh_jump_forward_failed"
            assert target["auth"] == []
