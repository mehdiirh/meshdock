"""Regression coverage for compact TCP proxies and saved NAT generation upgrades."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_port_ranges import single_link
from test_topology import payload

from app import remote_agent, topology
from app.changes import affected_links
from app.db import connect
from app.planner import build, empty, validate_bindings
from app.remote_agent import Agent, OperationError, atomic_json
from app.security import AppError
from app.worker import targets


def range_snapshot(admin):
    value, link = single_link(admin)
    link["ports"] = [
        {"public": "18000-18002", "target": "18000-18002", "host": "127.0.0.1", "exclude": [18001]}
    ]
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    with connect() as database:
        return topology.desired(database, True)


def test_upgrade_reconciles_existing_gre_once_and_attributes_it(admin):
    desired = range_snapshot(admin)
    previous = copy.deepcopy(desired)
    previous.pop("method_versions")
    link = desired["links"][0]
    assert {t.server["id"] for t in targets(previous, desired)} == {
        link["entry_id"],
        link["exit_id"],
    }
    assert affected_links(previous, desired) == [link["id"]]
    assert targets(desired, desired) == []
    assert affected_links(desired, desired) == []


def test_preview_exposes_compact_haproxy_listeners_and_capacity(admin):
    range_snapshot(admin)
    plans = admin.get("/api/v1/preview").json()
    active = [plan for plan in plans if plan["method_count"]]
    assert len(active) == 2
    for plan in active:
        assert len(plan["socket_ranges"]) == 2
        assert plan["resources"]["listeners"] == 2
        assert plan["resources"]["nofile"] >= 131072
        assert "haproxy.cfg" in plan["files"]
        assert not plan["forwarded_ranges"]
    methods = admin.get("/api/v1/methods").json()
    assert all(method["mapping"]["capacity_basis"] == "system_resources" for method in methods)


@pytest.mark.parametrize("field", ["socket_ranges", "forwarded_ranges"])
def test_existing_listener_conflicts_with_ranges_before_apply(tmp_path, monkeypatch, field):
    agent = Agent("a" * 10, root=tmp_path)
    plan = empty()
    plan[field] = [{"address": "192.0.2.1", "protocol": "tcp", "start": 8000, "end": 8099}]
    monkeypatch.setattr(remote_agent.shutil, "which", lambda _: True)
    monkeypatch.setattr(
        remote_agent,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout=b'LISTEN 0 128 0.0.0.0:8080 0.0.0.0:* users:(("nginx",pid=999999999,fd=3))\n',
            returncode=0,
        ),
    )
    with pytest.raises(OperationError, match="listener_conflict"):
        agent.socket_preflight(plan)


def test_range_readiness_checks_every_port_and_retains_exclusions(tmp_path, monkeypatch):
    agent = Agent("a" * 10, root=tmp_path)
    plan = empty()
    plan["socket_ranges"] = [
        {"address": "192.0.2.1", "protocol": "tcp", "start": 8000, "end": 8002},
        {"address": "192.0.2.1", "protocol": "tcp", "start": 8004, "end": 8004},
    ]
    output = "\n".join(
        f"LISTEN 0 128 192.0.2.1:{port} 0.0.0.0:*" for port in (8000, 8001, 8002, 8004)
    )
    monkeypatch.setattr(
        remote_agent, "run", lambda *a, **k: SimpleNamespace(stdout=output.encode())
    )
    agent.socket_readiness(plan)
    output = output.split("\n", 1)[1]
    with pytest.raises(OperationError, match="health_failed"):
        agent.socket_readiness(plan)


def test_range_egress_exhaustion_requires_explicit_exception(tmp_path, monkeypatch):
    agent = Agent("a" * 10, root=tmp_path)
    plan = empty()
    plan["socket_ranges"] = [
        {"address": "192.0.2.1", "protocol": "tcp", "start": 1023, "end": 65535}
    ]
    original = Path.read_text
    values = {
        "/proc/sys/net/ipv4/ip_local_port_range": "40000 40002",
        "/proc/sys/net/ipv4/ip_local_reserved_ports": "",
    }
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda p, *a, **k: values[str(p)] if str(p) in values else original(p, *a, **k),
    )
    monkeypatch.setattr(remote_agent.shutil, "which", lambda _: True)
    monkeypatch.setattr(
        remote_agent,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=b'[{"prefsrc":"192.0.2.1"}]', returncode=0),
    )
    with pytest.raises(OperationError, match="outgoing_port_capacity"):
        agent.outgoing_port_preflight(plan)
    plan["socket_ranges"][0]["end"] = 40000
    agent.outgoing_port_preflight(plan)


def test_compile_rejects_overlapping_range_and_single_listeners():
    plan = empty()
    plan["socket_ranges"] = [
        {"address": "192.0.2.1", "protocol": "tcp", "start": 8000, "end": 8099}
    ]
    plan["sockets"] = [{"address": "192.0.2.1", "protocol": "tcp", "port": 8080}]
    with pytest.raises(AppError, match="control_port_conflict"):
        validate_bindings(plan)


def test_nat_upgrade_activation_failure_restores_saved_manifest_and_retries(
    admin, tmp_path, monkeypatch
):
    snapshot = range_snapshot(admin)
    desired = build(snapshot)[snapshot["links"][0]["entry_id"]]
    agent = Agent(snapshot["namespace"], root=tmp_path / "agent")
    agent.units = tmp_path / "units"
    agent.units.mkdir()
    old = copy.deepcopy(desired)
    saved = json.loads((Path(__file__).parent / "fixtures/legacy-gre-network.json").read_text())[0]
    old.update(saved)
    old["socket_ranges"] = []
    router = f"{agent.prefix}router.service"
    network = f"{agent.prefix}network.service"
    old["units"].pop(router)
    old["files"].pop("haproxy.cfg")
    old["units"][network] = "[Service]\nExecStart=/legacy/network-up\n"
    directories = []
    for index, plan in enumerate((old, desired)):
        plan = json.loads(
            json.dumps(plan).replace(f'/var/lib/meshdock/{snapshot["namespace"]}', str(agent.root))
        )
        directory = agent.generation(str(index + 1) * 32)
        directory.mkdir(parents=True)
        atomic_json(directory / "manifest.json", plan)
        directories.append(directory)
    commands = []
    fail = False

    def run(args, **kwargs):
        commands.append(args)
        if fail and args == ["systemctl", "start", router]:
            raise OperationError("health_failed")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(remote_agent, "run", run)
    monkeypatch.setattr(remote_agent.shutil, "which", lambda _: True)
    monkeypatch.setattr(agent, "firewall", lambda _: None)
    monkeypatch.setattr(agent, "network_down", lambda: commands.append(["network_down"]))
    monkeypatch.setattr(agent, "preflight", lambda _: None)
    agent.switch(directories[0])
    atomic_json(
        directories[1] / "journal.json", {"previous": directories[0].name, "phase": "prepared"}
    )
    commands.clear()
    fail = True
    with pytest.raises(OperationError):
        agent.apply(directories[1].name)
    assert commands.index(["network_down"]) < commands.index(["systemctl", "start", router])
    fail = False
    agent.rollback(directories[1].name)
    assert agent.current() == directories[0]
    assert agent.manifest(agent.current())["network_rules"] == saved["network_rules"]
    assert ["systemctl", "start", network] in commands
    agent.rollback(directories[1].name)  # Idempotent rollback.
    agent.apply(directories[1].name)
    assert agent.current() == directories[1]
    assert router in agent.manifest(agent.current())["units"]
    assert not any(agent.manifest(agent.current())["network_rules"].values())
    agent.switch(None)
    assert agent.current() is None
    assert ["systemctl", "stop", router] in commands
