import copy
import json
from types import SimpleNamespace

import pytest
from app import remote_agent, topology
from app.db import connect
from app.methods import REGISTRY
from app.planner import build, empty
from app.ports import expand, segments
from app.remote_agent import Agent, OperationError
from app.schemas import Port
from pydantic import ValidationError
from test_topology import payload, seeded


def single_link(admin, method="gre"):
    value = seeded(admin)
    value["links"] = [value["links"][0]]
    value["links"][0]["method"] = method
    return value, value["links"][0]


@pytest.mark.parametrize(
    "public,target,exclude",
    [
        (0, 80, []),
        (65536, 80, []),
        (True, 80, []),
        ("100-90", "100-90", []),
        ("80;id", 80, []),
        ("80-90", "90-101", []),
        ("80-90", "80-90", [79]),
        ("80-90", "80-90", ["80-90"]),
        ("80-90", "80-90", ["80-83", "83-85"]),
    ],
)
def test_invalid_mapping_intent(public, target, exclude):
    with pytest.raises(ValidationError):
        Port(public=public, target=target, exclude=exclude)


def test_exceptions_preserve_shifted_offsets():
    mapping = Port(public="8000-8009", target="9000-9009", exclude=[8001, "8004-8007"]).model_dump()
    assert list(segments(mapping)) == [
        (8000, 8000, 9000, 9000),
        (8002, 8003, 9002, 9003),
        (8008, 8009, 9008, 9009),
    ]
    assert [(p["public"], p["target"]) for p in expand([mapping])] == [
        (8000, 9000),
        (8002, 9002),
        (8003, 9003),
        (8008, 9008),
        (8009, 9009),
    ]


@pytest.mark.parametrize("method", list(REGISTRY))
def test_all_adapters_compile_ranges_with_exceptions(admin, method):
    value, link = single_link(admin, method)
    link["ports"] = [
        {
            "public": "30000-30020",
            "target": "40000-40020",
            "host": "127.0.0.1",
            "exclude": [30004, "30010-30012"],
        }
    ]
    response = admin.put("/api/v1/topology", json=payload(value))
    assert response.status_code == 200, response.text
    with connect() as database:
        snapshot = topology.desired(database, True)
    plans = build(snapshot)
    entry, exit = plans[link["entry_id"]], plans[link["exit_id"]]
    assert admin.get("/api/v1/topology").json()["links"][0]["ports"] == link["ports"]
    if method == "gre":
        rules = "\n".join(entry["network_rules"]["pre"])
        assert "--dport 30000:30003" in rules
        assert ":40000-40003/30000" in rules
        assert ":40005-40009/30005" in rules
        assert entry["shifted_ranges"]
        assert not entry["sockets"]
        assert not exit["checks"]
    else:
        public = [
            item["port"]
            for item in entry["sockets"]
            if item["address"] == "192.0.2.10" and item["port"] >= 30000
        ]
        assert len(public) == 17
        assert 30004 not in public and 30010 not in public
        assert (
            len(
                {item["port"] for item in entry["sockets"] if item["address"].startswith("127.77.")}
            )
            >= 17
        )
        assert not exit["checks"]  # Range targets may be started later.
        assert len(entry["checks"]) == 1


def test_full_gre_range_compact_and_method_switch_supported(admin):
    value, link = single_link(admin)
    link["ports"] = [
        {
            "public": "1023-65535",
            "target": "1023-65535",
            "host": "127.0.0.1",
            "exclude": [2222, "8080-8081"],
        }
    ]
    entry = next(server for server in value["servers"] if server["id"] == link["entry_id"])
    entry["ssh_port"] = 2222
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    with connect() as database:
        snapshot = topology.desired(database, True)
    plans = build(snapshot)
    assert len(plans[link["entry_id"]]["network_rules"]["pre"]) == 3
    assert len(json.dumps(plans)) < 20000
    assert not plans[link["entry_id"]]["listeners"]
    value = admin.get("/api/v1/topology").json()
    for method in REGISTRY:
        if method == "gre":
            continue
        value["links"][0]["method"] = method
        response = admin.put("/api/v1/topology", json=payload(value))
        assert response.status_code == 200, response.text
        value = admin.get("/api/v1/topology").json()
        with connect() as database:
            plans = build(topology.desired(database, True))
        plan = plans[link["entry_id"]]
        public = {s["port"] for s in plan["sockets"] if s["address"] == entry["address"]}
        assert 1023 in public and 65535 in public
        assert "listen public_8080\n" not in plan["files"]["haproxy.cfg"]
        assert len(plan["checks"]) == 1
        assert plan["files"]["haproxy.cfg"].count("check inter") <= 2
        assert len(plan["files"]["firewall.sh"].splitlines()) < 25
        assert plan["resources"]["nofile"] > 65536
    value["links"][0]["ports"][0]["exclude"] = []
    assert admin.put("/api/v1/topology", json=payload(value)).json()["code"] == "ssh_port_conflict"


def test_range_pool_conflicts_and_exceptions(admin):
    value, link = single_link(admin)
    link["ports"] = [{"public": "8000-8099", "target": "8000-8099", "host": "127.0.0.1"}]
    other = {
        **copy.deepcopy(link),
        "id": "f" * 32,
        "method": "rathole",
        "ports": [{"public": 8080, "target": 8080, "host": "127.0.0.1"}],
    }
    value["links"].append(other)
    assert (
        admin.put("/api/v1/topology", json=payload(value)).json()["code"] == "range_pool_conflict"
    )
    link["ports"][0]["exclude"] = [8080]
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200


def test_automatic_controls_avoid_ranges_and_explicit_controls(admin):
    value, link = single_link(admin, "rathole")
    link["ports"] = [{"public": "19999-20020", "target": "19999-20020", "host": "127.0.0.1"}]
    link["control_port"] = 20010
    assert (
        admin.put("/api/v1/topology", json=payload(value)).json()["code"] == "control_port_conflict"
    )
    link["ports"][0]["exclude"] = [20010]
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    value = admin.get("/api/v1/topology").json()
    value["links"][0]["ports"][0]["exclude"] = []
    value["links"][0]["control_port"] = None
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    with connect() as database:
        plans = build(topology.desired(database, True))
    config = plans[link["entry_id"]]["files"]["link-1.toml"]
    assert 'bind_addr = "192.0.2.10:1024"' in config


def test_protocol_spaces_are_separate(admin):
    value, link = single_link(admin, "hysteria2")
    link["control_port"] = 22  # UDP does not collide with management TCP/22.
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200


def test_different_native_targets_cannot_share_overlay_target_range(admin):
    value, link = single_link(admin)
    link["ports"] = [
        {"public": "8000-8009", "target": "9000-9009", "host": "127.0.0.1"},
        {"public": "8100-8109", "target": "9000-9009", "host": "127.0.0.2"},
    ]
    assert (
        admin.put("/api/v1/topology", json=payload(value)).json()["code"] == "range_target_conflict"
    )


@pytest.mark.parametrize(
    "address,protocol,conflicts",
    [
        ("127.0.0.1", "tcp", False),
        ("192.0.2.1", "tcp", True),
        ("0.0.0.0", "tcp", True),
        ("[::]", "tcp", True),
        ("192.0.2.2", "tcp", False),
        ("192.0.2.1", "udp", False),
    ],
)
def test_live_conflicts_respect_bind_address_and_protocol(
    tmp_path, monkeypatch, address, protocol, conflicts
):
    agent = Agent("a" * 10, root=tmp_path)
    plan = empty()
    plan["forwarded_ranges"] = [
        {"address": "192.0.2.1", "protocol": "tcp", "start": 1023, "end": 65535}
    ]

    def run(args, **kwargs):
        mode = "tcp" if "-ltnpe" in args else "udp"
        output = (
            f'LISTEN 0 128 {address}:8080 0.0.0.0:* users:(("unrelated",pid=999999999,fd=3))\n'
            if protocol == mode
            else ""
        )
        return SimpleNamespace(stdout=output.encode(), returncode=0)

    monkeypatch.setattr(remote_agent, "run", run)
    monkeypatch.setattr(remote_agent.shutil, "which", lambda _: "/usr/bin/ss")
    if conflicts:
        with pytest.raises(OperationError, match="listener_conflict") as error:
            agent.socket_preflight(plan)
        assert error.value.detail["port"] == 8080
    else:
        agent.socket_preflight(plan)


def test_stale_manifest_does_not_authorize_occupied_port(tmp_path, monkeypatch):
    agent = Agent("a" * 10, root=tmp_path)
    monkeypatch.setattr(remote_agent.shutil, "which", lambda _: "/usr/bin/ss")
    monkeypatch.setattr(
        remote_agent,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout=b"LISTEN 0 128 127.0.0.1:30000 0.0.0.0:*\n", returncode=0
        ),
    )
    plan = empty()
    plan["sockets"] = [{"address": "127.0.0.1", "port": 30000, "protocol": "tcp"}]
    with pytest.raises(OperationError, match="listener_conflict"):
        agent.socket_preflight(plan)


def test_ipv6_only_socket_does_not_claim_ipv4(tmp_path, monkeypatch):
    agent = Agent("a" * 10, root=tmp_path)
    monkeypatch.setattr(remote_agent.shutil, "which", lambda _: "/usr/bin/ss")
    monkeypatch.setattr(
        remote_agent,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout=b"LISTEN 0 128 [::]:30000 [::]:* v6only:1\n", returncode=0
        ),
    )
    plan = empty()
    plan["sockets"] = [{"address": "192.0.2.1", "port": 30000, "protocol": "tcp"}]
    agent.socket_preflight(plan)


def test_gre_shifted_ranges_require_supported_kernel(tmp_path, monkeypatch):
    agent = Agent("a" * 10, root=tmp_path)
    monkeypatch.setattr(remote_agent.platform, "release", lambda: "4.15.0-test")
    plan = empty()
    plan["network_interfaces"] = ["tmtest"]
    plan["shifted_ranges"] = True
    with pytest.raises(OperationError, match="range_kernel_unsupported"):
        agent.network_preflight(plan)


def test_ranges_survive_restart_and_normal_schema_validation(admin):
    from app.migrate import migrate

    value, link = single_link(admin, "rathole")
    link["ports"] = [
        {"public": "50000-50020", "target": "51000-51020", "host": "127.0.0.1", "exclude": [50003]}
    ]
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    before = admin.get("/api/v1/topology").json()
    migrate()
    migrate()
    assert admin.get("/api/v1/topology").json() == before


def test_internal_allocation_respects_destination_exceptions_and_bind_address(admin):
    value, first = single_link(admin)
    middle = next(server for server in value["servers"] if server["id"] == first["exit_id"])
    middle["role"] = "both"
    last = next(
        server
        for server in value["servers"]
        if server["role"] == "exit" and server["id"] != middle["id"]
    )
    first["ports"] = [
        {"public": "1023-65535", "target": "1023-65535", "host": "127.0.0.1", "exclude": [30000]}
    ]
    value["links"].append(
        {
            **copy.deepcopy(first),
            "id": "e" * 32,
            "entry_id": middle["id"],
            "exit_id": last["id"],
            "method": "rathole",
            "ports": [{"public": 443, "target": 8443, "host": "127.0.0.1"}],
        }
    )
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    with connect() as database:
        plans = build(topology.desired(database, True))
    assert any(item["address"].startswith("127.77.") for item in plans[middle["id"]]["sockets"])
    assert not any(item["address"] == "127.0.0.1" for item in plans[middle["id"]]["sockets"])


def test_control_port_cannot_replace_a_declared_destination_service(admin):
    value, link = single_link(admin, "rathole")
    # Reverse direction control listens on the entry. Add a preceding entry so
    # this control server also has a declared public-address application target.
    original_entry = next(s for s in value["servers"] if s["id"] == link["entry_id"])
    original_entry["role"] = "both"
    other = next(
        s for s in value["servers"] if s["role"] == "entry" and s["id"] != original_entry["id"]
    )
    link["control_port"] = 8443
    value["links"].append(
        {
            **copy.deepcopy(link),
            "id": "e" * 32,
            "entry_id": other["id"],
            "exit_id": original_entry["id"],
            "method": "gre",
            "control_port": None,
            "ports": [{"public": 9443, "target": 8443, "host": original_entry["address"]}],
        }
    )
    assert (
        admin.put("/api/v1/topology", json=payload(value)).json()["code"] == "control_port_conflict"
    )


def test_reverse_ssh_shards_forwards_and_bounds_authorized_key_line(admin):
    import subprocess
    import tempfile
    from pathlib import Path

    value, link = single_link(admin, "reverse_ssh")
    link["ports"] = [{"public": "10000-14096", "target": "20000-24096", "host": "127.0.0.1"}]
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    with connect() as database:
        plans = build(topology.desired(database, True))
    entry, exit = plans[link["entry_id"]], plans[link["exit_id"]]
    configs = [v for k, v in exit["files"].items() if "-ssh-" in k]
    assert [c.count("RemoteForward") for c in configs] == [4096, 1]
    assert 'permitlisten="127.77.0.1:*"' in entry["files"]["link-1-authorized"]
    assert len(entry["files"]["link-1-authorized"].encode()) < 8192
    assert "PermitListen 127.77.0.1:*" in entry["files"]["link-1-sshd.conf"]
    assert "AllowStreamLocalForwarding no" in entry["files"]["link-1-sshd.conf"]
    assert all(len(unit) < 1500 for unit in exit["units"].values())
    # The actual local OpenSSH parser validates the generated large client file;
    # -G prints configuration and never connects to a server.
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "ssh.conf"
        path.write_text(configs[0])
        result = subprocess.run(["ssh", "-G", "-F", str(path), "tunnel"], capture_output=True)
        assert result.returncode == 0, result.stderr.decode()
        assert result.stdout.count(b"remoteforward ") == 4096


def test_large_parallel_links_have_distinct_private_listener_spaces(admin):
    from app.allocation import allocate

    value, link = single_link(admin, "rathole")
    link["ports"] = [{"public": "1023-65535", "target": "1023-65535", "host": "127.0.0.1"}]
    value["links"].append({**copy.deepcopy(link), "id": "d" * 32, "method": "frp_wss"})
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    with connect() as database:
        allocations = allocate(topology.desired(database, True))
    assert len(allocations) == 2
    assert all(len(a["internal_ports"]) == 64513 for a in allocations)
    assert allocations[0]["internal_address"] != allocations[1]["internal_address"]
    assert all(1 <= a["allocated_control"] < 1023 for a in allocations)
    assert allocations[0]["allocated_control"] != allocations[1]["allocated_control"]


def test_live_descriptor_capacity_fails_before_deployment(tmp_path, monkeypatch):
    from pathlib import Path

    agent = Agent("a" * 10, root=tmp_path)
    plan = empty()
    plan["resources"] = {"nofile": 264000, "descriptor_budget": 200000}
    original = Path.read_text
    values = {"/proc/sys/fs/nr_open": "1048576", "/proc/sys/fs/file-nr": "10000 0 1000000"}
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda p, *a, **k: values[str(p)] if str(p) in values else original(p, *a, **k),
    )
    agent.resource_preflight(plan)
    values["/proc/sys/fs/nr_open"] = "65536"
    with pytest.raises(OperationError, match="descriptor_capacity") as error:
        agent.resource_preflight(plan)
    assert error.value.detail == {"required": 264000, "available": 65536}
    values["/proc/sys/fs/nr_open"] = "1048576"
    values["/proc/sys/fs/file-nr"] = "900000 0 1000000"
    with pytest.raises(OperationError, match="descriptor_capacity"):
        agent.resource_preflight(plan)


def test_range_readiness_detects_missing_listener_without_probing_targets(tmp_path, monkeypatch):
    agent = Agent("a" * 10, root=tmp_path)
    plan = empty()
    plan["sockets"] = [
        {"address": "127.77.0.1", "port": p, "protocol": "tcp"} for p in range(30000, 31000)
    ]
    output = "\n".join(f"LISTEN 0 128 127.77.0.1:{p} 0.0.0.0:*" for p in range(30000, 31000))
    monkeypatch.setattr(
        remote_agent, "run", lambda *a, **k: SimpleNamespace(stdout=output.encode(), returncode=0)
    )
    agent.socket_readiness(plan)
    output = output.split("\n", 1)[1]
    with pytest.raises(OperationError, match="health_failed"):
        agent.socket_readiness(plan)
