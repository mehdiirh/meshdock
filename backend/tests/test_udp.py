"""Protocol-aware intent, allocation, migration and coordinated compensation."""

import json

import pytest
from alembic import command
from app import topology
from app.allocation import allocate
from app.db import connect
from app.methods import REGISTRY
from app.migrate import configuration, migrate
from app.planner import build
from test_port_ranges import single_link
from test_topology import payload


def save(admin, method="gre", settings=None, protocol="both"):
    value, link = single_link(admin, method)
    link["settings"] = settings or {}
    link["ports"] = [
        {
            "public": "18000-18002",
            "target": "19000-19002",
            "host": "127.0.0.1",
            "exclude": [18001],
            "protocol": protocol,
        }
    ]
    response = admin.put("/api/v1/topology", json=payload(value))
    assert response.status_code == 200, response.text
    with connect() as db:
        snapshot = topology.desired(db, True)
    return snapshot, build(snapshot)


CASES = [("gre", {}), ("hysteria2", {})] + [
    (name, {"transport": transport})
    for name in ("backhaul", "rathole", "frp_wss")
    for transport, details in REGISTRY[name].transports.items()
    if "udp" in details.get("payload_protocols", REGISTRY[name].metadata["protocols"])
]


@pytest.mark.parametrize("method,settings", CASES)
def test_supported_protocols_compile_and_preserve_intent(admin, method, settings):
    protocol = "udp" if settings.get("transport") == "udp" else "both"
    snapshot, plans = save(admin, method, settings, protocol)
    link = snapshot["links"][0]
    entry, exit = plans[link["entry_id"]], plans[link["exit_id"]]
    assert all("-p tcp" not in rule for rules in entry["network_rules"].values() for rule in rules)
    assert entry["forwarded_ranges"]
    assert all(item["protocol"] == "udp" for item in entry["forwarded_ranges"])
    assert "haproxy.cfg" in entry["files"] or protocol == "udp"
    assert not any(check["port"] in (19000, 19002) for check in exit["checks"])
    if method != "gre":
        assert any(s["protocol"] == "udp" for s in entry["sockets"])
        assert any(name.endswith("-address.service") for name in entry["units"])
        assert not entry["loopback_interfaces"]
        assert "--ctorigdst" in entry["files"]["firewall.sh"]
    else:
        assert "-p udp --dport 18000" in entry["network_rules"]["pre"][0]
        assert "127.0.0.1:19000" in exit["network_rules"]["pre"][0]
    assert snapshot["links"][0]["ports"][0]["protocol"] == protocol


def test_rows_are_independent_and_same_number_can_have_two_destinations(admin):
    value, link = single_link(admin)
    link["ports"] = [
        {"public": "1023-2048", "target": "1023-2048", "protocol": "tcp"},
        {"public": "2049-3000", "target": "4049-5000", "protocol": "udp"},
        {"public": "3001-3500", "target": "5001-5500", "protocol": "both", "exclude": [3100]},
        {"public": 1023, "target": 7000, "protocol": "udp"},
    ]
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    saved = admin.get("/api/v1/topology").json()
    assert [p["protocol"] for p in saved["links"][0]["ports"]] == ["tcp", "udp", "both", "udp"]
    saved["links"][0]["method"] = "reverse_ssh"
    assert (
        admin.put("/api/v1/topology", json=payload(saved)).json()["code"]
        == "mapping_protocol_unsupported"
    )
    assert admin.get("/api/v1/topology").json()["revision"] == saved["revision"]
    saved["links"][0]["ports"][2]["public"] = "3001-1500"
    assert admin.put("/api/v1/topology", json=payload(saved)).status_code == 422


@pytest.mark.parametrize("transport", ["tcpmux", "ws", "wss", "wsmux", "wssmux"])
def test_backhaul_rejects_udp_on_unsupported_transports(admin, transport):
    value, link = single_link(admin, "backhaul")
    link["settings"] = {"transport": transport}
    link["ports"][0]["protocol"] = "both"
    assert (
        admin.put("/api/v1/topology", json=payload(value)).json()["code"]
        == "mapping_protocol_unsupported"
    )


def test_udp_ssh_number_is_allowed_but_udp_control_conflicts(admin):
    value, link = single_link(admin, "frp_wss")
    link["ports"] = [{"public": 22, "target": 53, "protocol": "udp"}]
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    value = admin.get("/api/v1/topology").json()
    value["links"][0].update(settings={"transport": "quic"}, control_port=22)
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 400
    value["links"][0]["ports"][0]["public"] = 20001
    value["links"][0]["control_port"] = 20001
    assert (
        admin.put("/api/v1/topology", json=payload(value)).json()["code"] == "control_port_conflict"
    )


def test_udp_control_auto_allocation_skips_udp_public_mapping(admin):
    snapshot, _ = save(admin, "frp_wss", {"transport": "quic"}, "udp")
    link = snapshot["links"][0]
    link["ports"] = [
        {"public": 20000 + link["slot"], "target": 53, "host": "127.0.0.1", "protocol": "udp"}
    ]
    assert allocate(snapshot)[0]["allocated_control"] != 20000 + link["slot"]


def test_migration_defaults_legacy_rows_without_rewriting_job_history(admin):
    snapshot, _ = save(admin, protocol="tcp")
    with connect() as db:
        before = [tuple(row) for row in db.execute("SELECT id,snapshot FROM jobs ORDER BY id")]
    command.downgrade(configuration(), "b74d8ea93021")
    with connect() as db:
        assert "protocol" not in json.loads(db.execute("SELECT ports FROM links").fetchone()[0])[0]
    migrate()
    migrate()
    with connect() as db:
        assert (
            json.loads(db.execute("SELECT ports FROM links").fetchone()[0])[0]["protocol"] == "tcp"
        )
        assert [
            tuple(row) for row in db.execute("SELECT id,snapshot FROM jobs ORDER BY id")
        ] == before


def test_downgrade_refuses_to_reinterpret_udp_as_tcp(admin):
    save(admin)
    with pytest.raises(RuntimeError, match="UDP mappings"):
        command.downgrade(configuration(), "b74d8ea93021")
    with connect() as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "c81f6e902a14"
        assert (
            json.loads(db.execute("SELECT ports FROM links").fetchone()[0])[0]["protocol"] == "both"
        )


def test_backhaul_both_reuses_native_listener_pair(admin):
    snapshot, plans = save(admin, "backhaul")
    link = allocate(snapshot)[0]
    assert link["internal_ports"][:2] == link["internal_ports"][2:]
    plan = plans[link["entry_id"]]
    assert "accept_udp = true" in plan["files"][f'link-{link["slot"]}.toml']
    assert len([s for s in plan["sockets"] if s["address"] == link["internal_address"]]) == 4


def test_loopback_udp_nat_is_scoped_and_upgrade_selects_existing_endpoints(admin):
    import copy
    from app.worker import targets

    snapshot, plans = save(admin, protocol="both")
    link = snapshot["links"][0]
    entry, exit = plans[link["entry_id"]], plans[link["exit_id"]]
    assert "input" not in entry["network_rules"]
    rules = exit["network_rules"]["input"]
    assert len(rules) == 2  # The excluded port is not covered.
    for rule in rules:
        assert "-p udp" in rule and "-i md" in rule
        assert "-d 127.0.0.1" in rule
        assert "--ctstate DNAT --ctorigdst 10.253." in rule
        assert "-j SNAT --to-source 127.0.0.1" in rule
    assert all("-p tcp" not in r for r in rules)
    previous = copy.deepcopy(snapshot)
    previous["method_versions"]["gre"] = 4
    assert snapshot["method_versions"]["gre"] == 5
    assert {target.server["id"] for target in targets(previous, snapshot)} == {
        link["entry_id"],
        link["exit_id"],
    }
    assert targets(snapshot, snapshot) == []


def test_conntrack_cleanup_is_scoped_and_failure_is_not_silenced(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.remote_agent import Agent, OperationError

    agent = Agent("a" * 10, root=tmp_path)
    commands = []
    response = SimpleNamespace(returncode=1, stderr=b"conntrack: 0 flow entries have been deleted.")
    monkeypatch.setattr(
        "app.remote_agent.run", lambda args, **kwargs: commands.append(args) or response
    )
    peers = [{"source": "10.253.0.5", "destination": "10.253.0.6"}]
    agent.clear_udp_connections(peers)
    assert commands == [
        ["conntrack", "-D", "-p", "udp", "--orig-src", "10.253.0.5", "--orig-dst", "10.253.0.6"]
    ]
    response.stderr = b"Operation not permitted"
    with pytest.raises(OperationError, match="remote_failed"):
        agent.clear_udp_connections(peers)


def test_conntrack_installation_progress_remains_visible():
    from app.ssh import progress_event

    event = progress_event(
        json.dumps({"event": "packages_installing", "detail": {"packages": ["conntrack"]}})
    )
    assert event[1]["packages"] == ["conntrack"]


@pytest.mark.parametrize("endpoint", ["entry", "exit", "legacy_exit"])
def test_health_checks_only_declared_network_chains(admin, tmp_path, monkeypatch, endpoint):
    from types import SimpleNamespace
    from app.remote_agent import Agent, OperationError

    snapshot, plans = save(admin, protocol="both")
    link = snapshot["links"][0]
    plan = plans[link["entry_id"] if endpoint == "entry" else link["exit_id"]]
    if endpoint == "legacy_exit":
        plan["network_rules"].pop("input")
    agent = Agent("a" * 10, root=tmp_path)
    monkeypatch.setattr(agent, "generation", lambda _: tmp_path)
    monkeypatch.setattr(agent, "manifest", lambda _: plan)
    monkeypatch.setattr(agent, "socket_readiness", lambda _: None)
    commands = []
    missing_chain = None

    def run(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=int(args[-1] == missing_chain))

    monkeypatch.setattr("app.remote_agent.run", run)
    agent.health("generation")
    expected = [
        ["iptables", "-w", "-t", table, "-C", parent, "-j", chain]
        for key, (table, parent, chain) in agent.network_chains().items()
        if plan["network_rules"].get(key)
    ]
    assert [args for args in commands if args[0] == "iptables"] == expected
    assert any(args[5] == "INPUT" for args in expected) == (endpoint == "exit")
    # Optional chains may be absent from a plan; declared chains must exist live.
    missing_chain = expected[-1][-1]
    with pytest.raises(OperationError, match="health_failed"):
        agent.health("generation")
