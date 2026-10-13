"""Optional real binary tests; only loopback listeners, never SSH or a real server.

Set MESHDOCK_TEST_BIN_DIR to a directory containing checksum-verified platform binaries.
"""

import os
import socket
import socketserver
import ssl
import subprocess
import threading
import time
from pathlib import Path

import pytest
from app.methods import REGISTRY
from app.methods.base import Context
from app.planner import empty
from app.ports import expand
from app.topology import material


class TLSRelay(socketserver.ThreadingTCPServer):
    """Loopback stand-in for HAProxy's TLS listener; transport binaries stay real."""

    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        try:
            return self.tls.wrap_socket(connection, server_side=True), address
        except Exception:
            connection.close()
            raise


class RelayHandler(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(self.server.target, timeout=5) as upstream:

            def copy(source, destination):
                try:
                    while data := source.recv(65536):
                        destination.sendall(data)
                except OSError:
                    pass

            outgoing = threading.Thread(target=copy, args=(self.request, upstream), daemon=True)
            outgoing.start()
            copy(upstream, self.request)


BINARIES = os.getenv("MESHDOCK_TEST_BIN_DIR")


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        while data := self.request.recv(4096):
            self.request.sendall(data)


@pytest.mark.skipif(
    not BINARIES, reason="Set MESHDOCK_TEST_BIN_DIR for opt-in real transport smoke tests"
)
@pytest.mark.parametrize(
    "method,binaries,settings",
    [
        (
            "rathole",
            ("rathole", "rathole"),
            {"nodelay": False, "heartbeat_interval": 15, "heartbeat_timeout": 60},
        ),
        ("frp_wss", ("frps", "frpc"), {}),
        ("frp_wss", ("frps", "frpc"), {"tcp_mux": False, "pool_count": 12}),
        ("hysteria2", ("hysteria", "hysteria"), {}),
        (
            "hysteria2",
            ("hysteria", "hysteria"),
            {"obfuscation": False, "stream_receive_window": 4194304},
        ),
        ("backhaul", ("backhaul", "backhaul"), {}),
        (
            "backhaul",
            ("backhaul", "backhaul"),
            {"transport": "tcpmux", "mux_version": 2, "mux_recievebuffer": 8388608},
        ),
        ("backhaul", ("backhaul", "backhaul"), {"transport": "ws"}),
        (
            "backhaul",
            ("backhaul", "backhaul"),
            {"transport": "wsmux", "mux_recievebuffer": 8388608},
        ),
    ],
)
def test_round_trip_over_actual_transport(tmp_path, method, binaries, settings):
    if any(not (Path(BINARIES) / name).exists() for name in binaries):
        pytest.skip("Required test binary absent")
    for _ in range(30):
        echo = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
        first = echo.server_address[1]
        try:
            if first > 65533:
                raise OSError("Port range exceeds TCP space")
            second = socketserver.ThreadingTCPServer(("127.0.0.1", first + 2), Echo)
            break
        except OSError:
            echo.server_close()
    else:
        pytest.fail("No adjacent test ports available")
    for server in (echo, second):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as control:
        control.bind(("127.0.0.1", 0))
        control_port = control.getsockname()[1]
    link = {
        "id": "a" * 32,
        "slot": 987,
        "settings": settings,
        "ports": expand(
            [
                {
                    "public": "443-445",
                    "target": f"{first}-{first + 2}",
                    "exclude": [444],
                    "host": "127.0.0.1",
                }
            ]
        ),
        "allocated_control": control_port,
        "internal_ports": [48021, 48023],
        "auxiliary_ports": [48025],
        "policy": "roundrobin",
        "weight": 1,
    }
    context = Context(
        "a" * 10, link, {"address": "127.0.0.1"}, {"address": "127.0.0.1"}, material()
    )
    entry, exit = empty(), empty()
    REGISTRY[method].configure(context, entry, exit)
    processes = []
    streams = []
    relay = None
    try:
        for role, plan, binary in [("entry", entry, binaries[0]), ("exit", exit, binaries[1])]:
            folder = tmp_path / role
            folder.mkdir()
            for name, content in plan["files"].items():
                (folder / name).write_text(content.replace(context.root, str(folder)))
            if method == "frp_wss" and role == "entry":
                relay = TLSRelay(("127.0.0.1", context.control), RelayHandler)
                relay.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                relay.tls.load_cert_chain(folder / (context.filename + "-tls.pem"))
                relay.target = ("127.0.0.1", context.auxiliary(0))
                threading.Thread(target=relay.serve_forever, daemon=True).start()
            config = folder / (context.filename + (".json" if method == "hysteria2" else ".toml"))
            command = [str(Path(BINARIES) / binary)]
            if method == "hysteria2":
                command += ["client" if role == "entry" else "server"]
            command += [str(config)] if method == "rathole" else ["-c", str(config)]
            stream = (folder / "output.log").open("wb")
            streams.append(stream)
            processes.append(subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                for index in range(2):
                    with socket.create_connection(
                        ("127.0.0.1", context.internal(index)), timeout=1
                    ) as client:
                        client.settimeout(2)
                        client.sendall(b"meshdock-roundtrip")
                        if client.recv(128) != b"meshdock-roundtrip":
                            raise OSError("Unexpected payload")
                break
            except OSError:
                pass
            time.sleep(0.3)
        else:
            diagnostics = "\n".join(
                (tmp_path / role / "output.log").read_text() for role in ("entry", "exit")
            )
            # Test data only, but redact random generated tokens too.
            pytest.fail(
                "Transport did not carry loopback traffic: "
                + diagnostics.replace(context.secrets["token"], "[redacted]")
            )
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for stream in streams:
            stream.close()
        if relay:
            relay.shutdown()
            relay.server_close()
        for server in (echo, second):
            server.shutdown()
            server.server_close()
