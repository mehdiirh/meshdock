"""Public UDP ingress to private native listeners in isolated Linux namespaces."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
import test_gre_linux
from app import planner
from app.topology import material
from test_gre_linux import (
    echo,
    helper,
    inside,
    request,
    udp_echo,
    udp_request,
)

# Register the shared fixture and preserve its container-only opt-in guard.
network = test_gre_linux.network
pytestmark = test_gre_linux.pytestmark


def test_native_udp_public_forwarding_and_previous_generation_restore(network, monkeypatch):
    binary = Path(os.environ.get("MESHDOCK_TEST_BIN_DIR", "/missing")) / "backhaul"
    if not binary.exists():
        pytest.skip("Requires the pinned Backhaul binary")
    net = network
    secrets = material()
    monkeypatch.setattr(planner, "unseal", lambda _: secrets)
    for port in (19000, 19002):
        echo(net, net.exit, port)
        udp_echo(net, net.exit, port)
    running = []
    for generation, protocol in (("a", "both"), ("b", "tcp"), ("c", "both")):
        for process in running:
            process.terminate()
            process.wait(timeout=10)
            net.processes.remove(process)
        running.clear()
        snapshot = {
            "namespace": "aaaaaaaaaa",
            "servers": [
                {"id": net.entry, "address": "192.0.2.1", "ssh_port": 22},
                {"id": net.exit, "address": "192.0.2.6", "ssh_port": 22},
            ],
            "links": [
                {
                    "id": "test",
                    "slot": 1,
                    "method": "backhaul",
                    "enabled": True,
                    "entry_id": net.entry,
                    "exit_id": net.exit,
                    "encrypted": "test",
                    "ports": [
                        {
                            "public": "18000-18002",
                            "target": "19000-19002",
                            "host": "127.0.0.1",
                            "exclude": [18001],
                            "protocol": protocol,
                        }
                    ],
                    "settings": {"transport": "tcp"},
                    "policy": "failover",
                    "weight": 1,
                }
            ],
        }
        plans = planner.build(snapshot)
        for ns, plan in plans.items():
            directory = net.root / ns / "generations" / (generation * 32)
            directory.mkdir(parents=True)
            pointer = directory.parent.parent / "current"
            if pointer.exists():
                helper(net, ns, "a.network_down()")
                address_script = pointer / "link-1-address.sh"
                if address_script.exists():
                    inside(ns, "sh", str(address_script), "down")
                pointer.unlink()
            (directory / "manifest.json").write_text(json.dumps(plan))
            for name, content in plan["files"].items():
                (directory / name).write_text(
                    content.replace("/run/meshdock-aaaaaaaaaa-stats.sock", f"/tmp/{ns}.sock")
                )
            pointer.symlink_to(directory)
            if (directory / "link-1-address.sh").exists():
                inside(ns, "sh", str(directory / "link-1-address.sh"), "up")
            helper(net, ns, "p=a.manifest(a.current()); a.firewall(p['firewall'])")
            if plan["network_interfaces"]:
                helper(net, ns, "a.network_up()")
            commands = [[str(binary), "-c", str(directory / "link-1.toml")]]
            if "haproxy.cfg" in plan["files"]:
                commands.append(["haproxy", "-db", "-f", str(directory / "haproxy.cfg")])
            for index, command in enumerate(commands):
                with (directory / f"process-{index}.log").open("w") as log:
                    process = subprocess.Popen(
                        ["ip", "netns", "exec", ns, *command], stdout=log, stderr=log
                    )
                net.processes.append(process)
                running.append(process)
        for _ in range(80):
            try:
                request(net, 18000)
                break
            except AssertionError:
                time.sleep(0.1)
        else:
            pytest.fail("Native transport did not start")
        for port in (18000, 18002):
            request(net, port)
            udp_request(net, port, protocol == "both")
        udp_request(net, 18001, False)
        # Never weaken loopback filtering on the public NIC.
        assert (
            inside(
                net.entry, "cat", "/proc/sys/net/ipv4/conf/public0/route_localnet"
            ).stdout.strip()
            == "0"
        )
        assert "UNRELATED_TEST" in inside(net.entry, "iptables-save").stdout
    for ns in (net.entry, net.exit):
        helper(net, ns, "a.network_down(); a.firewall([])")
        inside(ns, "sh", str(net.root / ns / "current" / "link-1-address.sh"), "down")
        rules = inside(ns, "iptables-save").stdout
        assert "MESHDOCK_AAAAAAAAAA" not in rules
        assert "UNRELATED_TEST" in rules
    udp_request(net, 18000, False)
