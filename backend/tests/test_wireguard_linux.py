"""Actual authenticated WireGuard over managed GRE, in disposable namespaces.

MESHDOCK_TEST_XRAY points to a verified Linux binary. No inventory credentials,
production network, host TUN interface, or host routes are used.
"""

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import test_gre_linux
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from test_gre_linux import (
    activate,
    echo,
    inside,
    request,
    udp_echo,
)

# Register the shared fixture and preserve its container-only opt-in guard.
network = test_gre_linux.network
pytestmark = test_gre_linux.pytestmark


def keys():
    private = X25519PrivateKey.generate()
    return (
        base64.b64encode(private.private_bytes_raw()).decode(),
        base64.b64encode(private.public_key().public_bytes_raw()).decode(),
    )


def test_wireguard_wildcard_handshake_tcp_and_udp_payloads(network):
    binary = os.environ.get("MESHDOCK_TEST_XRAY")
    if not binary or not Path(binary).is_file():
        pytest.skip("Requires a verified Xray Linux binary")
    net = network
    echo(net, net.exit, 25000, "0.0.0.0")
    udp_echo(net, net.exit, 25000, "0.0.0.0")
    echo(net, net.exit, 19000, "0.0.0.0")
    server_private, server_public = keys()
    client_private, client_public = keys()
    server = {
        "log": {"loglevel": "debug"},
        "inbounds": [
            {
                "listen": "0.0.0.0",
                "port": 19000,
                "protocol": "wireguard",
                "settings": {
                    "secretKey": server_private,
                    "mtu": 1280,
                    "noKernelTun": True,
                    "peers": [{"publicKey": client_public, "allowedIPs": ["10.70.0.2/32"]}],
                },
            }
        ],
        "outbounds": [{"protocol": "freedom"}],
    }
    client = {
        "log": {"loglevel": "debug"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": 25001,
                "protocol": "dokodemo-door",
                "settings": {"address": "192.0.2.6", "port": 25000, "network": "tcp,udp"},
            }
        ],
        "outbounds": [
            {
                "protocol": "wireguard",
                "settings": {
                    "secretKey": client_private,
                    "address": ["10.70.0.2/32"],
                    "mtu": 1280,
                    "noKernelTun": True,
                    "peers": [
                        {
                            "endpoint": "192.0.2.1:18000",
                            "publicKey": server_public,
                            "allowedIPs": ["0.0.0.0/0"],
                        }
                    ],
                },
            }
        ],
    }
    for ns, config in ((net.exit, server), (net.client, client)):
        path = net.root / f"{ns}.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        with (net.root / f"{ns}.log").open("w") as log:
            process = subprocess.Popen(
                ["ip", "netns", "exec", ns, binary, "run", "-c", str(path)], stdout=log, stderr=log
            )
        net.processes.append(process)
    for _ in range(50):
        if ":19000 " in inside(net.exit, "ss", "-H", "-lun").stdout:
            break
        time.sleep(0.1)
    else:
        pytest.fail("WireGuard test listener did not start")
    activate(
        net, {"public": 18000, "target": 19000, "host": "127.0.0.1", "protocol": "both"}, "a" * 32
    )
    request(net, 18000)  # Outer TCP continues to work alongside WireGuard UDP.
    probe = """import socket
with socket.create_connection(('127.0.0.1', 25001), timeout=4) as tcp:
 tcp.settimeout(8)
 tcp.sendall(b'wireguard-tcp-payload')
 assert tcp.recv(128) == b'wireguard-tcp-payload'
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
 udp.settimeout(8)
 udp.sendto(b'wireguard-udp-payload', ('127.0.0.1', 25001))
 assert udp.recv(128) == b'wireguard-udp-payload'
"""
    result = inside(net.client, sys.executable, "-c", probe, check=False)
    diagnostics = "\n".join(p.read_text() for p in net.root.glob("*.log"))
    assert result.returncode == 0, result.stderr + diagnostics
