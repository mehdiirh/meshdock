"""Opt-in packet tests in disposable Linux namespaces, with no external network.

Run the dedicated Dockerfile.network-test image with --privileged --network none.
The test never connects to inventory hosts or shares the host network namespace.
"""

import json
import os
import platform
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from app.methods import REGISTRY
from app.methods.base import Context
from app.planner import empty

pytestmark = pytest.mark.skipif(
    os.getenv("MESHDOCK_TEST_LINUX_NETWORK") != "1" or platform.system() != "Linux",
    reason="Opt-in disposable Linux namespace test",
)


def command(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=20)


def inside(ns, *args, check=True):
    return command("ip", "netns", "exec", ns, *args, check=check)


@pytest.fixture
def network(tmp_path):
    suffix = str(os.getpid())
    client, entry, exit = [f"meshdock-test-{suffix}-{side}" for side in ("c", "e", "x")]
    processes = []
    try:
        for ns in (client, entry, exit):
            command("ip", "netns", "add", ns)
            inside(ns, "ip", "link", "set", "lo", "up")
        for first_ns, first_ip, second_ns, second_ip, a, b in (
            (client, "192.0.2.2/30", entry, "192.0.2.1/30", "client0", "public0"),
            (entry, "192.0.2.5/30", exit, "192.0.2.6/30", "underlay0", "underlay1"),
        ):
            inside(first_ns, "ip", "link", "add", a, "type", "veth", "peer", "name", b)
            inside(first_ns, "ip", "link", "set", b, "netns", second_ns)
            for ns, interface, address in ((first_ns, a, first_ip), (second_ns, b, second_ip)):
                inside(ns, "ip", "addr", "add", address, "dev", interface)
                inside(ns, "ip", "link", "set", interface, "up")
        inside(exit, "ip", "route", "add", "192.0.2.0/30", "via", "192.0.2.5")
        # An unrelated rule must survive setup, rollback and cleanup.
        for ns in (entry, exit):
            inside(ns, "iptables", "-N", "UNRELATED_TEST")
            inside(ns, "iptables", "-A", "INPUT", "-j", "UNRELATED_TEST")
            inside(ns, "iptables", "-P", "FORWARD", "DROP")
        yield SimpleNamespace(
            client=client, entry=entry, exit=exit, root=tmp_path, processes=processes
        )
    finally:
        for process in processes:
            process.terminate()
            process.wait(timeout=5)
        for ns in (client, entry, exit):
            command("ip", "netns", "del", ns, check=False)


def helper(net, ns, body):
    root = net.root / ns
    root.mkdir(exist_ok=True)
    code = (
        "from app.remote_agent import Agent; " f"a=Agent('aaaaaaaaaa',root={str(root)!r}); " + body
    )
    return inside(ns, sys.executable, "-c", code)


def echo(net, ns, port):
    code = f"""import socketserver
class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(self.request.recv(1024))
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
Server(('127.0.0.1', {port}), Echo).serve_forever()
"""
    process = subprocess.Popen(["ip", "netns", "exec", ns, sys.executable, "-c", code])
    net.processes.append(process)
    for _ in range(30):
        if f":{port} " in inside(ns, "ss", "-H", "-ltn").stdout:
            return
        time.sleep(0.05)
    raise AssertionError("Echo service did not start")


def request(net, port, succeeds=True):
    code = f"""import socket
with socket.create_connection(('192.0.2.1', {port}), timeout=2) as s:
    s.sendall(b'gre-wire-test')
    assert s.recv(1024) == b'gre-wire-test'
"""
    result = inside(net.client, sys.executable, "-c", code, check=False)
    assert (result.returncode == 0) == succeeds, result.stderr


def activate(net, mapping, generation, settings=None):
    entry, exit = empty(), empty()
    context = Context(
        "aaaaaaaaaa",
        {"slot": 1, "ports": [mapping], "settings": settings or {}},
        {"address": "192.0.2.1"},
        {"address": "192.0.2.6"},
        {},
    )
    REGISTRY["gre"].configure(context, entry, exit)
    for ns, plan in ((net.entry, entry), (net.exit, exit)):
        directory = net.root / ns / "generations" / generation
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps(plan))
        pointer = directory.parent.parent / "current"
        if pointer.exists():
            helper(net, ns, "a.network_down()")
            inside(ns, "sh", str(pointer / "gre.sh"), "down")
            pointer.unlink()
        script = directory / "gre.sh"
        script.write_text(plan["files"]["link-1-gre.sh"])
        inside(ns, "sh", str(script), "up")
        pointer.symlink_to(directory)
        helper(net, ns, "p=a.manifest(a.current()); a.firewall(p['firewall']); a.network_up()")


def test_gre_settings_change_and_previous_settings_restore(network):
    mapping = {"public": "18000-18001", "target": "18000-18001", "host": "127.0.0.1"}
    echo(network, network.exit, 18000)
    for generation, settings in (
        ("e" * 32, {"mtu": 1200, "ttl": 32, "tos": 16}),
        ("f" * 32, {"mtu": 1400, "ttl": 64}),
        ("a" * 32, {"mtu": 1200, "ttl": 32, "tos": 16}),
    ):
        activate(network, mapping, generation, settings)
        for ns in (network.entry, network.exit):
            interface = json.loads(
                inside(ns, "ip", "-j", "-d", "link", "show", "mdaaaaaa1").stdout
            )[0]
            assert interface["mtu"] == settings["mtu"]
            assert interface["linkinfo"]["info_data"]["ttl"] == settings["ttl"]
        request(network, 18000)


def test_real_gre_range_packets_exclusions_switch_rollback_and_cleanup(network):
    net = network
    for port in (1023, 20001, 30000, 65535, 41000, 41002):
        echo(net, net.exit, port)
    before = inside(net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/forwarding").stdout
    broad = {
        "public": "1023-65535",
        "target": "1023-65535",
        "host": "127.0.0.1",
        "exclude": [20001],
    }
    activate(net, broad, "b" * 32)
    for port in (1023, 30000, 65535):
        request(net, port)
    request(net, 20001, succeeds=False)
    assert (
        inside(net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/forwarding").stdout.strip() == "1"
    )
    # The destination offset must remain correct after skipping the middle port.
    shifted = {
        "public": "31000-31002",
        "target": "41000-41002",
        "host": "127.0.0.1",
        "exclude": [31001],
    }
    activate(net, shifted, "c" * 32)
    request(net, 31000)
    request(net, 31002)
    request(net, 31001, succeeds=False)
    # A failure after one table was installed must restore sysctls and remove
    # partial owned chains before coordinated rollback starts.
    broken = net.root / net.entry / "generations" / ("d" * 32)
    broken.mkdir()
    current = net.root / net.entry / "current"
    failed_plan = json.loads((current / "manifest.json").read_text())
    failed_plan["network_rules"]["post"] = ["-j INVALID_MESHDOCK_TEST"]
    (broken / "manifest.json").write_text(json.dumps(failed_plan))
    helper(net, net.entry, "a.network_down()")
    current.unlink()
    current.symlink_to(broken)
    result = inside(
        net.entry,
        sys.executable,
        "-c",
        "from app.remote_agent import Agent; "
        + f"Agent('aaaaaaaaaa',root={str(current.parent)!r}).network_up()",
        check=False,
    )
    assert result.returncode != 0
    assert "MESHDOCK_AAAAAAAAAA_PRE" not in inside(net.entry, "iptables-save").stdout
    assert inside(net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/forwarding").stdout == before
    # Restore the prior generation's compact plan, as rollback does.
    for ns in (net.entry, net.exit):
        helper(
            net,
            ns,
            "a.network_down(); (a.root/'current').unlink(); (a.root/'current').symlink_to(a.generation('"
            + "b" * 32
            + "')); p=a.manifest(a.current()); a.firewall(p['firewall']); a.network_up()",
        )
    request(net, 30000)
    for ns in (net.entry, net.exit):
        helper(net, ns, "a.network_down(); a.firewall([]); a.network_down()")
        rules = inside(ns, "iptables-save").stdout
        assert "MESHDOCK_AAAAAAAAAA" not in rules
        assert "UNRELATED_TEST" in rules
    assert inside(net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/forwarding").stdout == before
    request(net, 30000, succeeds=False)
