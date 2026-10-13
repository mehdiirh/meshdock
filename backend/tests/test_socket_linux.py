"""Opt-in Linux validators and SSH traffic test in a disposable Docker container.

Never run with host networking or host mounts. No inventory hosts are used.
"""

import os
import platform
import signal
import socket
import socketserver
import subprocess
import threading
import time
from pathlib import Path

import pytest
from app import planner
from app.remote_agent import Agent, OperationError
from app.topology import material

pytestmark = pytest.mark.skipif(
    os.getenv("MESHDOCK_TEST_LINUX_NETWORK") != "1"
    or platform.system() != "Linux"
    or not Path("/.dockerenv").exists(),
    reason="Requires the disposable Linux test container",
)


def plans(monkeypatch, method, public="1023-65535", target="1023-65535", exclusions=None):
    secrets = material()
    monkeypatch.setattr(planner, "unseal", lambda _: secrets)
    return planner.build(
        {
            "namespace": "abcdef1234",
            "servers": [
                {"id": "entry", "address": "127.0.0.2", "ssh_port": 22},
                {"id": "exit", "address": "127.0.0.3", "ssh_port": 22},
            ],
            "links": [
                {
                    "id": "a" * 32,
                    "entry_id": "entry",
                    "exit_id": "exit",
                    "slot": 1,
                    "method": method,
                    "enabled": True,
                    "encrypted": "test fixture",
                    "control_port": 2222,
                    "policy": "roundrobin",
                    "weight": 1,
                    "ports": [
                        {
                            "public": public,
                            "target": target,
                            "exclude": exclusions or [],
                            "host": "127.0.0.1",
                        }
                    ],
                }
            ],
        }
    )


def write_files(tmp_path, compiled):
    root = "/var/lib/meshdock/abcdef1234/current"
    folders = {}
    for role, plan in compiled.items():
        folder = tmp_path / role
        folder.mkdir()
        folders[role] = folder
        for name, contents in plan["files"].items():
            path = folder / name
            path.write_text(contents.replace(root, str(folder)))
            path.chmod(0o600)
    return folders


@pytest.mark.parametrize("method", ["backhaul", "rathole", "frp_wss", "hysteria2", "reverse_ssh"])
def test_full_range_haproxy_configuration(tmp_path, monkeypatch, method):
    compiled = plans(monkeypatch, method, exclusions=[2222])
    folders = write_files(tmp_path, compiled)
    result = subprocess.run(
        ["haproxy", "-c", "-f", str(folders["entry"] / "haproxy.cfg")],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode()


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(self.request.recv(128))


def test_reverse_ssh_4097_listeners_and_both_session_boundaries(tmp_path, monkeypatch):
    compiled = plans(monkeypatch, "reverse_ssh", "10000-14096", "19000-23096")
    folders = write_files(tmp_path, compiled)
    # Container test accommodation only: no production account/config is changed.
    # Root's package-image password is locked and fixture files live under /tmp.
    subprocess.run(
        ["usermod", "-p", "test-invalid-password-hash", "root"],
        check=True,
        capture_output=True,
    )
    Path("/run/sshd").mkdir(exist_ok=True)
    server_config = folders["entry"] / "link-1-sshd.conf"
    with server_config.open("a") as stream:
        stream.write("\nStrictModes no\n")
    processes, echoes, logs = [], [], []
    try:
        for port in (19000, 23096):
            echo = socketserver.ThreadingTCPServer(("127.0.0.1", port), Echo)
            echoes.append(echo)
            threading.Thread(target=echo.serve_forever, daemon=True).start()
        commands = [["/usr/sbin/sshd", "-D", "-e", "-f", str(server_config)]]
        for name in sorted(folders["exit"].glob("*-ssh-*.conf")):
            commands.append(["ssh", "-NT", "-F", str(name), "tunnel"])
        commands.append(["haproxy", "-db", "-f", str(folders["entry"] / "haproxy.cfg")])
        for index, command in enumerate(commands):
            stream = (tmp_path / f"process-{index}.log").open("wb")
            logs.append(stream)
            processes.append(
                subprocess.Popen(command, stdout=stream, stderr=stream, start_new_session=True)
            )
            if index == 0:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        with socket.create_connection(("127.0.0.2", 2222), timeout=0.2):
                            break
                    except OSError:
                        time.sleep(0.05)
        agent = Agent("abcdef1234", root=tmp_path / "agent")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if any(process.poll() is not None for process in processes):
                pytest.fail(
                    "A test transport process exited: "
                    + "\n".join(path.read_text() for path in tmp_path.glob("process-*.log"))
                )
            try:
                agent.socket_readiness(compiled["entry"])
                for port in (10000, 14096):
                    with socket.create_connection(("127.0.0.2", port), timeout=1) as connection:
                        connection.settimeout(2)
                        connection.sendall(b"large-range-echo")
                        assert connection.recv(128) == b"large-range-echo"
                break
            except (OperationError, OSError, AssertionError):
                time.sleep(0.2)
        else:
            pytest.fail("SSH range listeners or cross-session traffic did not become ready")
        # All intermediate destinations are closed; range readiness still passes.
        assert not compiled["exit"]["checks"]
        assert len(compiled["entry"]["checks"]) == 2
        # A client cannot ask this key/daemon to bind a public listener.
        deny_config = tmp_path / "deny.conf"
        original = (folders["exit"] / "link-1-ssh-1.conf").read_text()
        deny_config.write_text(
            "\n".join(line for line in original.splitlines() if "RemoteForward" not in line)
        )
        command = [
            "ssh",
            "-NT",
            "-F",
            str(deny_config),
            "-R",
            "127.0.0.2:25000:127.0.0.1:19000",
            "tunnel",
        ]
        denied = subprocess.run(command, capture_output=True, timeout=10)
        assert denied.returncode != 0
        assert b"remote port forwarding failed" in denied.stderr
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        for stream in logs:
            stream.close()
        for echo in echoes:
            echo.shutdown()
            echo.server_close()


def test_socket_listeners_can_exhaust_outgoing_source_ports():
    namespace = f"meshdock-egress-{os.getpid()}"
    subprocess.run(["ip", "netns", "add", namespace], check=True, capture_output=True)
    try:
        prefix = ["ip", "netns", "exec", namespace]
        subprocess.run(prefix + ["ip", "link", "set", "lo", "up"], check=True, capture_output=True)
        subprocess.run(
            prefix + ["sysctl", "-w", "net.ipv4.ip_local_port_range=40000 40003"],
            check=True,
            capture_output=True,
        )
        script = """
import errno, socket
listeners = []
for port in range(40000, 40004):
    listener = socket.socket()
    listener.bind(("127.0.0.1", port))
    listener.listen()
    listeners.append(listener)
target = socket.socket()
target.bind(("127.0.0.2", 1234))
target.listen()
try:
    socket.create_connection(("127.0.0.2", 1234), timeout=1)
except OSError as error:
    assert error.errno == errno.EADDRNOTAVAIL, error
else:
    raise AssertionError("Expected source-port exhaustion")
listeners.pop().close()
with socket.create_connection(("127.0.0.2", 1234), timeout=1):
    pass
"""
        result = subprocess.run(
            prefix + ["/usr/bin/python3", "-c", script], capture_output=True, timeout=10
        )
        assert result.returncode == 0, result.stderr.decode()
    finally:
        subprocess.run(["ip", "netns", "del", namespace], check=True, capture_output=True)
