"""Transport capabilities drive allocation, TLS, conflicts and public contracts."""

import pytest
from app import topology
from app.allocation import allocate
from app.db import connect
from app.methods import REGISTRY
from app.planner import build
from test_topology import payload, seeded

CASES = [(method, name) for method, adapter in REGISTRY.items() for name in adapter.transports]


@pytest.mark.parametrize("method,transport", CASES)
def test_transport_contract_and_plan(admin, method, transport):
    value = seeded(admin)
    value["links"] = value["links"][:1]
    link = value["links"][0]
    link.update(method=method, settings={"transport": transport})
    if method == "backhaul" and transport == "udp":
        for mapping in link["ports"]:
            mapping["protocol"] = "udp"
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    with connect() as database:
        snapshot = topology.desired(database, True)
    compiled = build(snapshot)
    allocated = allocate(snapshot)[0]
    entry, exit = compiled[link["entry_id"]], compiled[link["exit_id"]]
    capability = REGISTRY[method].transport(link)
    control = allocated["allocated_control"]
    assert {s["protocol"] for s in entry["sockets"] if s["port"] == control} == set(
        capability["control_protocols"]
    )
    assert {r["protocol"] for r in entry["firewall"] if r.get("port") == control} == set(
        capability["control_protocols"]
    )
    entry_aux, exit_aux = REGISTRY[method].auxiliary_counts(link)
    assert len(allocated["auxiliary_ports"]) == entry_aux
    assert len(allocated["exit_auxiliary_ports"]) == exit_aux
    if capability["tls_mode"] == "verified_bridge":
        config = exit["files"]["haproxy.cfg"]
        assert "ssl verify required ca-file" in config
        assert "verifyhost tunnel.internal" in config
        assert "ssl-min-ver TLSv1.2" in config
        assert "BEGIN PRIVATE KEY" not in str(exit)
    elif capability["tls_mode"] == "verified_native":
        config = exit["files"][f'link-{allocated["slot"]}.toml']
        assert "trustedCaFile" in config and 'serverName = "tunnel.internal"' in config
        assert "BEGIN PRIVATE KEY" not in str(exit)
    public = str(admin.get("/api/v1/preview").json())
    assert "PRIVATE KEY" not in public and "CERTIFICATE" not in public


@pytest.mark.parametrize("transport", ["kcp", "quic"])
def test_frp_udp_transport_still_checks_mandatory_tcp_listener(admin, transport):
    value = seeded(admin)
    value["links"] = value["links"][:1]
    link = value["links"][0]
    link.update(
        method="frp_wss", settings={"transport": transport}, control_port=link["ports"][0]["public"]
    )
    result = admin.put("/api/v1/topology", json=payload(value))
    assert result.status_code == 400
    assert result.json()["code"] == "control_port_conflict"


@pytest.mark.parametrize(
    "settings",
    [
        {"transport": "quic", "tcp_mux": True},
        {"transport": "tcp", "quic_keepalive": 10},
        {"transport": "quic", "quic_keepalive": 30, "quic_idle_timeout": 30},
    ],
)
def test_inactive_or_incompatible_transport_options_are_rejected(admin, settings):
    value = seeded(admin)
    value["links"][0].update(method="frp_wss", settings=settings)
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 422


def test_tls_helper_allocation_avoids_exit_destination_and_ssh(admin):
    value = seeded(admin)
    value["links"] = value["links"][:1]
    value["links"][0].update(method="backhaul", settings={"transport": "wssmux"})
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    with connect() as database:
        snapshot = topology.desired(database, True)
    link = snapshot["links"][0]
    address = REGISTRY["backhaul"].internal_address(link)
    link["ports"] = [
        {"public": "8000-8002", "target": "30000-30002", "host": address, "exclude": []}
    ]
    exit = next(s for s in snapshot["servers"] if s["id"] == link["exit_id"])
    exit["ssh_port"] = 30003
    allocated = allocate(snapshot)[0]
    assert allocated["exit_auxiliary_ports"] == [30004]


def test_rathole_websocket_architecture_fails_before_host_changes(tmp_path, monkeypatch):
    from app.remote_agent import Agent, OperationError

    monkeypatch.setattr("app.remote_agent.platform.machine", lambda: "aarch64")
    agent = Agent("a" * 10, root=tmp_path)
    with pytest.raises(OperationError, match="transport_architecture_unsupported"):
        agent.architecture_preflight(
            {
                "architecture_requirements": [
                    {"method": "rathole", "transport": "wss", "supported": ["x86_64"]}
                ]
            }
        )
    agent.architecture_preflight({})
