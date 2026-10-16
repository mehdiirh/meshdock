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

from app import planner

pytestmark = pytest.mark.skipif(
    os.getenv("MESHDOCK_TEST_LINUX_NETWORK") != "1" or platform.system() != "Linux",
    reason="Opt-in disposable Linux namespace test",
)


def command(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=20)


def inside(ns, *args, check=True):
    return command("ip", "netns", "exec", ns, *args, check=check)


@pytest.fixture
def network(tmp_path, monkeypatch):
    monkeypatch.setattr(planner, "unseal", lambda _: {})
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
            client=client, entry=entry, exit=exit, root=tmp_path, processes=processes, proxies={}
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


def echo(net, ns, port, address="127.0.0.1"):
    code = f"""import socketserver
class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(self.request.recv(1024))
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
Server(({address!r}, {port}), Echo).serve_forever()
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
    assert (result.returncode == 0) == succeeds, f"Port {port}: {result.stderr}"


def stop_proxy(net, ns):
    process = net.proxies.pop(ns, None)
    if process:
        process.terminate()
        process.wait(timeout=10)
        net.processes.remove(process)


def activate(net, mapping, generation, settings=None, legacy=False):
    plans = planner.build(
        {
            "namespace": "aaaaaaaaaa",
            "servers": [
                {"id": net.entry, "address": "192.0.2.1", "ssh_port": 22},
                {"id": net.exit, "address": "192.0.2.6", "ssh_port": 22},
            ],
            "links": [
                {
                    "id": "test",
                    "slot": 1,
                    "method": "gre",
                    "enabled": True,
                    "entry_id": net.entry,
                    "exit_id": net.exit,
                    "encrypted": "test",
                    "ports": mapping if isinstance(mapping, list) else [mapping],
                    "settings": settings or {},
                    "policy": "failover",
                    "weight": 1,
                }
            ],
        }
    )
    if legacy:
        from pathlib import Path

        saved = json.loads((Path(__file__).parent / "fixtures/legacy-gre-network.json").read_text())
        for plan, old in zip(plans.values(), saved, strict=True):
            plan.update(old)
            plan["socket_ranges"] = []
            plan["files"].pop("haproxy.cfg")
    for ns, plan in plans.items():
        stop_proxy(net, ns)
        directory = net.root / ns / "generations" / generation
        directory.mkdir(parents=True, exist_ok=True)
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
        helper(net, ns, "p=a.manifest(a.current()); a.firewall(p['firewall'])")
        if plan["network_interfaces"]:
            helper(net, ns, "a.network_up()")
        if "haproxy.cfg" not in plan["files"]:
            continue
        config = directory / "haproxy.cfg"
        # Namespaces share /run; give test processes distinct stats sockets.
        config.write_text(
            plan["files"]["haproxy.cfg"].replace(
                "/run/meshdock-aaaaaaaaaa-stats.sock", f"/tmp/{ns}.sock"
            )
        )
        validation = inside(ns, "haproxy", "-c", "-f", str(config), check=False)
        assert validation.returncode == 0, validation.stderr
        process = subprocess.Popen(
            ["ip", "netns", "exec", ns, "haproxy", "-db", "-f", str(config)],
            stdout=(directory / "proxy.log").open("w"),
            stderr=subprocess.PIPE,
        )
        net.processes.append(process)
        net.proxies[ns] = process
        for _ in range(100):
            result = inside(
                ns,
                sys.executable,
                "-c",
                f"from app.remote_agent import Agent; a=Agent('aaaaaaaaaa', root={str(pointer.parent)!r}); a.socket_readiness(a.manifest(a.current()))",
                check=False,
            )
            if result.returncode == 0:
                break
            assert process.poll() is None, process.stderr.read().decode()
            time.sleep(0.05)
        else:
            raise AssertionError("HAProxy listeners did not become ready")


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
        "exclude": [20001, "40000-40999"],
    }
    activate(net, broad, "b" * 32)
    for port in (1023, 30000, 65535):
        request(net, port)
    request(net, 20001, succeeds=False)
    assert inside(net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/forwarding").stdout == before
    for ns in (net.entry, net.exit):
        rules = inside(ns, "iptables-save").stdout
        assert "DNAT" not in rules and "SNAT" not in rules and "MASQUERADE" not in rules
        assert (
            inside(ns, "cat", "/proc/sys/net/ipv4/conf/mdaaaaaa1/route_localnet").stdout.strip()
            == "0"
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
    # Negative offsets use the same preserved entry-port indexing.
    negative = {
        "public": "51000-51002",
        "target": "41000-41002",
        "host": "127.0.0.1",
        "exclude": [51001],
    }
    activate(net, negative, "d" * 32)
    request(net, 51000)
    request(net, 51002)
    request(net, 51001, succeeds=False)
    activate(net, broad, "b" * 32)
    request(net, 30000)
    for ns in (net.entry, net.exit):
        stop_proxy(net, ns)
        pointer = net.root / ns / "current"
        helper(net, ns, "a.network_down(); a.firewall([]); a.network_down()")
        inside(ns, "sh", str(pointer / "gre.sh"), "down")
        rules = inside(ns, "iptables-save").stdout
        assert "MESHDOCK_AAAAAAAAAA" not in rules
        assert "UNRELATED_TEST" in rules
    assert inside(net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/forwarding").stdout == before
    request(net, 30000, succeeds=False)


def test_legacy_nat_upgrade_and_rollback_restore_real_traffic(network):
    net = network
    mapping = {
        "public": "18000-18002",
        "target": "18000-18002",
        "host": "127.0.0.1",
        "exclude": [18001],
    }
    echo(net, net.exit, 18000)
    before = inside(net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/forwarding").stdout
    for generation, legacy in (("a", True), ("b", False), ("c", True), ("d", False)):
        activate(net, mapping, generation * 32, legacy=legacy)
        request(net, 18000)
        request(net, 18001, succeeds=False)
        rules = inside(net.entry, "iptables-save").stdout
        assert ("DNAT" in rules) == legacy
        assert "UNRELATED_TEST" in rules
        if not legacy:
            assert (
                inside(net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/forwarding").stdout
                == before
            )


def test_gre_relay_coexists_with_wildcard_destination_and_rolls_back(network):
    net = network
    mapping = {
        "public": "18000-18002",
        "target": "18000-18002",
        "host": "127.0.0.1",
        "exclude": [18001],
    }
    for port in (18000, 18002):
        echo(net, net.exit, port, "0.0.0.0")
    for generation, legacy in (("a", True), ("b", False), ("c", True), ("d", False)):
        activate(net, mapping, generation * 32, legacy=legacy)
        for port in (18000, 18002):
            request(net, port)
        request(net, 18001, succeeds=False)
        listeners = inside(net.exit, "ss", "-H", "-ltn").stdout
        assert "0.0.0.0:18000" in listeners
        assert ("10.253.0.6:30000" in listeners) == (not legacy)


def udp_echo(net, ns, port, address="127.0.0.1"):
    code = f"""import socket
s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(({address!r}, {port}))
while True:
 data, peer=s.recvfrom(65535)
 s.sendto(data, peer)
"""
    process = subprocess.Popen(["ip", "netns", "exec", ns, sys.executable, "-c", code])
    net.processes.append(process)
    for _ in range(30):
        if f":{port} " in inside(ns, "ss", "-H", "-lun").stdout:
            return
        time.sleep(0.05)
    raise AssertionError("UDP echo did not start")


def udp_request(net, port, succeeds=True, source_port=0):
    code = f"""import socket
s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(.5)
s.bind(('0.0.0.0', {source_port}))
s.sendto(b'udp-wire-test', ('192.0.2.1', {port}))
data, peer=s.recvfrom(128)
assert data == b'udp-wire-test'
assert peer == ('192.0.2.1', {port}), peer
"""
    result = inside(net.client, sys.executable, "-c", code, check=False)
    assert (result.returncode == 0) == succeeds, result.stderr


def test_mixed_protocol_ranges_switch_rollback_and_cleanup(network):
    net = network
    for port in (19000, 19002, 21000):
        echo(net, net.exit, port)
        udp_echo(net, net.exit, port)
    mapping = {
        "public": "18000-18002",
        "target": "19000-19002",
        "host": "127.0.0.1",
        "exclude": [18001],
        "protocol": "both",
    }
    before = inside(net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/forwarding").stdout
    for generation, rows in (
        ("a", [mapping]),
        (
            "b",
            [
                {**mapping, "protocol": "tcp"},
                {"public": 20000, "target": 21000, "host": "127.0.0.1", "protocol": "udp"},
            ],
        ),
        ("c", [mapping]),
    ):
        activate(net, rows, generation * 32)
        for port in (18000, 18002):
            request(net, port)
            udp_request(net, port, generation != "b")
        udp_request(net, 20000, generation == "b")
        request(net, 18001, False)
        udp_request(net, 18001, False)
        rules = inside(net.entry, "iptables-save").stdout
        assert not any("-p tcp" in line and "DNAT" in line for line in rules.splitlines())
        assert (
            inside(
                net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/route_localnet"
            ).stdout.strip()
            == "0"
        )
    for ns in (net.entry, net.exit):
        stop_proxy(net, ns)
        helper(net, ns, "a.network_down(); a.firewall([]); a.network_down()")
        inside(ns, "sh", str(net.root / ns / "current" / "gre.sh"), "down")
        rules = inside(ns, "iptables-save").stdout
        assert "MESHDOCK_AAAAAAAAAA" not in rules
        assert "UNRELATED_TEST" in rules
    assert inside(net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/forwarding").stdout == before
    udp_request(net, 18000, False)


def test_udp_full_range_is_compact_and_preserves_offsets(network):
    net = network
    for port in (1023, 65535, 41000, 41002):
        udp_echo(net, net.exit, port)
    broad = {
        "public": "1023-65535",
        "target": "1023-65535",
        "host": "127.0.0.1",
        "protocol": "udp",
        "exclude": [20000],
    }
    activate(net, broad, "a" * 32)
    udp_request(net, 1023)
    udp_request(net, 65535)
    udp_request(net, 20000, False)
    for generation, start in (("b", 31000), ("c", 51000)):
        activate(
            net,
            {
                "public": f"{start}-{start+2}",
                "target": "41000-41002",
                "host": "127.0.0.1",
                "protocol": "udp",
                "exclude": [start + 1],
            },
            generation * 32,
        )
        udp_request(net, start)
        udp_request(net, start + 2)
        udp_request(net, start + 1, False)


def test_gre_udp_remote_destination_enables_and_restores_return_interface(network):
    net = network
    udp_echo(net, net.entry, 19000, "192.0.2.5")
    before = inside(net.exit, "cat", "/proc/sys/net/ipv4/conf/underlay1/forwarding").stdout
    activate(
        net, {"public": 18000, "target": 19000, "host": "192.0.2.5", "protocol": "udp"}, "a" * 32
    )
    udp_request(net, 18000)
    assert (
        inside(net.exit, "cat", "/proc/sys/net/ipv4/conf/underlay1/forwarding").stdout.strip()
        == "1"
    )
    helper(net, net.exit, "a.network_down()")
    assert inside(net.exit, "cat", "/proc/sys/net/ipv4/conf/underlay1/forwarding").stdout == before


@pytest.mark.parametrize("bind", ["0.0.0.0", "127.0.0.1"])
@pytest.mark.parametrize("public", [18000, 19000, 21000])
def test_tcp_udp_wildcard_replies_keep_public_port_across_switch_and_rollback(
    network, bind, public
):
    net = network
    for port in (19000, 19002):
        echo(net, net.exit, port, bind)
        udp_echo(net, net.exit, port, bind)
    mapping = {
        "public": f"{public}-{public+2}",
        "target": "19000-19002",
        "host": "127.0.0.1",
        "protocol": "both",
        "exclude": [public + 1],
    }
    for generation, protocol in (("a", "both"), ("b", "tcp"), ("c", "both")):
        activate(net, {**mapping, "protocol": protocol}, generation * 32)
        for port in (public, public + 2):
            request(net, port)
            udp_request(net, port, protocol == "both")
        request(net, public + 1, False)
        udp_request(net, public + 1, False)
    for ns in (net.entry, net.exit):
        stop_proxy(net, ns)
        helper(net, ns, "a.network_down(); a.firewall([]); a.network_down()")
        inside(ns, "sh", str(net.root / ns / "current" / "gre.sh"), "down")
        rules = inside(ns, "iptables-save").stdout
        assert "MESHDOCK_AAAAAAAAAA" not in rules
        assert "UNRELATED_TEST" in rules


def test_failed_udp_input_nat_activation_cleans_up_and_restores_traffic(network):
    net = network
    udp_echo(net, net.exit, 19000, "0.0.0.0")
    activate(
        net, {"public": 18000, "target": 19000, "host": "127.0.0.1", "protocol": "udp"}, "a" * 32
    )
    udp_request(net, 18000)
    result = helper(
        net,
        net.exit,
        """
import app.remote_agent as module
original = module.run
def fail_after_install(args, **kwargs):
    result = original(args, **kwargs)
    if args[:5] == ['iptables', '-w', '-t', 'nat', '-I'] and args[5] == 'INPUT':
        raise RuntimeError('Injected failure after INPUT NAT installation')
    return result
module.run = fail_after_install
try:
    a.network_up()
except RuntimeError:
    pass
else:
    raise AssertionError('Injected activation failure did not run')
assert not (a.root / 'network-state.json').exists()
module.run = original
rules = original(['iptables-save']).stdout.decode()
assert 'MESHDOCK_AAAAAAAAAA_IN' not in rules
assert 'MESHDOCK_AAAAAAAAAA_PRE' not in rules
assert 'UNRELATED_TEST' in rules
a.network_up()
""",
    )
    udp_request(net, 18000)


def test_upgrade_clears_only_owned_stale_udp_sessions(network):
    net = network
    udp_echo(net, net.exit, 19000, "0.0.0.0")
    activate(
        net, {"public": 19000, "target": 19000, "host": "127.0.0.1", "protocol": "udp"}, "a" * 32
    )
    manifest = net.root / net.exit / "current" / "manifest.json"
    fixed = json.loads(manifest.read_text())
    # Reproduce a deployed version-4 generation without INPUT SNAT.
    helper(net, net.exit, "a.network_down()")
    old = json.loads(json.dumps(fixed))
    old["network_rules"].pop("input")
    old.pop("udp_conntrack_peers")
    manifest.write_text(json.dumps(old))
    helper(net, net.exit, "a.network_up()")
    udp_request(net, 19000, False, source_port=45000)
    # An unrelated local UDP session must survive the targeted invalidation.
    udp_echo(net, net.exit, 19800)
    inside(
        net.exit,
        sys.executable,
        "-c",
        "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(b'unrelated',('127.0.0.1',19800)); s.recv(128)",
    )
    before = inside(net.exit, "conntrack", "-L", "-p", "udp").stdout
    assert "dport=19800" in before
    assert "dst=10.253.0.6" in before
    helper(net, net.exit, "a.network_down()")
    manifest.write_text(json.dumps(fixed))
    helper(net, net.exit, "a.network_up()")
    # Same client tuple: do not hide stale NAT by choosing a new source port.
    udp_request(net, 19000, source_port=45000)
    after = inside(net.exit, "conntrack", "-L", "-p", "udp").stdout
    assert "dport=19800" in after
