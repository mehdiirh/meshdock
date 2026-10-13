import json
import tomllib
from pathlib import Path

import pytest
from alembic import command
from app import migrate as migration_module
from app import topology
from app.db import connect
from app.methods import REGISTRY
from app.methods.base import Context
from app.migrate import configuration, migrate
from app.planner import build, empty
from app.security import AppError
from test_topology import payload, seeded

CUSTOM = {
    "backhaul": {"transport": "tcpmux", "mux_recievebuffer": 8388608, "mux_version": 2},
    "gre": {"mtu": 1300, "ttl": 32, "tos": 16},
    "rathole": {"heartbeat_interval": 15, "heartbeat_timeout": 60, "nodelay": False},
    "reverse_ssh": {"server_alive_interval": 30, "compression": True},
    "frp_wss": {"tcp_mux": False, "pool_count": 12},
    "hysteria2": {"obfuscation": False, "stream_receive_window": 4194304},
}


@pytest.mark.parametrize("method", list(REGISTRY))
def test_settings_round_trip_snapshot_preview_and_compilation(admin, method):
    value = seeded(admin)
    value["links"] = value["links"][:1]
    link = value["links"][0]
    link.update(method=method, settings=CUSTOM[method])
    result = admin.put("/api/v1/topology", json=payload(value))
    assert result.status_code == 200, result.text
    assert admin.get("/api/v1/topology").json()["links"][0]["settings"] == CUSTOM[method]
    with connect() as database:
        snapshot = topology.desired(database, True)
        saved = json.loads(
            database.execute(
                "SELECT snapshot FROM jobs WHERE id=?", (result.json()["job_id"],)
            ).fetchone()[0]
        )
    assert saved["links"][0]["settings"] == CUSTOM[method]
    custom = build(snapshot)
    snapshot["links"][0]["settings"] = {}
    assert custom != build(snapshot)
    assert admin.get("/api/v1/preview").status_code == 200


@pytest.mark.parametrize("method", list(REGISTRY))
def test_old_snapshots_and_unknown_or_injected_options(method):
    adapter = REGISTRY[method]
    assert adapter.options({}).model_dump() == adapter.options({"settings": {}}).model_dump()
    for settings in (
        {"unrecognized-secret": "secret-value"},
        {"token": "secret-value"},
        {"command": "secret-value"},
    ):
        with pytest.raises(AppError) as error:
            adapter.options({"settings": settings})
        assert error.value.code == "invalid_method_settings"
        assert "secret" not in str(error.value.details)


@pytest.mark.parametrize(
    "method,settings",
    [
        ("backhaul", {"transport": "invalid"}),
        ("backhaul", {"transport": "tcp", "mux_recievebuffer": 4194304}),
        (
            "backhaul",
            {"transport": "tcpmux", "mux_recievebuffer": 65536, "mux_streambuffer": 131072},
        ),
        ("backhaul", {"connection_pool": "16"}),
        ("backhaul", {"transport": "tcpmux", "mux_version": True}),
        ("gre", {"mtu": 100}),
        ("gre", {"ttl": True}),
        ("rathole", {"heartbeat_interval": 40, "heartbeat_timeout": 40}),
        ("reverse_ssh", {"compression": "yes"}),
        ("frp_wss", {"tcp_mux": False, "tcp_mux_keepalive": 20}),
        ("frp_wss", {"heartbeat_interval": 100}),
        ("hysteria2", {"stream_receive_window": 100000000}),
        ("hysteria2", {"max_idle_timeout": 5, "keepalive_period": 10}),
    ],
)
def test_invalid_settings_rejected_before_mutation(admin, method, settings):
    value = seeded(admin)
    before = admin.get("/api/v1/jobs").json()
    value["links"][0].update(method=method, settings=settings)
    result = admin.put("/api/v1/topology", json=payload(value), headers={"Accept-Language": "fa"})
    assert result.status_code == 422, result.text
    assert result.json()["code"] == "invalid_method_settings"
    assert "تنظیمات" in result.json()["message"]
    assert admin.get("/api/v1/topology").json()["revision"] == value["revision"]
    assert admin.get("/api/v1/jobs").json() == before


def test_switching_method_requires_compatible_settings(admin):
    value = seeded(admin)
    value["links"][0].update(method="gre", settings={"mtu": 1300})
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    value = admin.get("/api/v1/topology").json()
    value["links"][0]["method"] = "rathole"
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 422
    value["links"][0]["settings"] = {}
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200


def test_migration_preserves_existing_links_and_defaults(admin):
    seeded(admin)
    with connect() as database:
        before = [
            tuple(row)
            for row in database.execute("SELECT id,encrypted,ports FROM links ORDER BY id")
        ]
    command.downgrade(configuration(), "8d4af912ab63")
    migrate()
    migrate()
    with connect() as database:
        assert before == [
            tuple(row)
            for row in database.execute("SELECT id,encrypted,ports FROM links ORDER BY id")
        ]
        assert all(row[0] == "{}" for row in database.execute("SELECT settings FROM links"))
    command.check(configuration())


def test_generated_options_have_correct_roles_and_preserve_managed_secrets():
    secrets = topology.material()
    for method, settings in CUSTOM.items():
        context = Context(
            "a" * 10,
            {"slot": 1, "ports": [], "settings": settings},
            {"address": "192.0.2.1"},
            {"address": "192.0.2.2"},
            secrets,
        )
        entry, exit = empty(), empty()
        REGISTRY[method].configure(context, entry, exit)
        if method == "backhaul":
            server = tomllib.loads(entry["files"]["link-1.toml"])["server"]
            client = tomllib.loads(exit["files"]["link-1.toml"])["client"]
            assert server["transport"] == client["transport"] == "tcpmux"
            assert server["mux_recievebuffer"] == client["mux_recievebuffer"] == 8388608
            assert "mux_con" not in client and "connection_pool" not in server
            assert server["token"] == client["token"] == secrets["token"]
        elif method == "rathole":
            server = tomllib.loads(entry["files"]["link-1.toml"])["server"]
            client = tomllib.loads(exit["files"]["link-1.toml"])["client"]
            assert server["heartbeat_interval"] == 15
            assert client["heartbeat_timeout"] == 60
            assert server["transport"]["type"] == client["transport"]["type"] == "noise"
            assert client["transport"]["tcp"]["nodelay"] is False
        elif method == "frp_wss":
            for plan in (entry, exit):
                transport = tomllib.loads(plan["files"]["link-1.toml"])["transport"]
                assert transport["tcpMux"] is False
                assert "tcpMuxKeepaliveInterval" not in transport
        elif method == "hysteria2":
            for plan in (entry, exit):
                config = json.loads(plan["files"]["link-1.json"])
                assert "obfs" not in config
                assert config["quic"]["maxStreamReceiveWindow"] == 4194304
        elif method == "gre":
            assert "mtu 1300" in entry["files"]["link-1-gre.sh"]
            assert "ttl 32 tos 16" in exit["files"]["link-1-gre.sh"]


def test_method_catalog_exposes_typed_settings(admin):
    for method in admin.get("/api/v1/methods").json():
        schema = method["settings_schema"]
        assert schema["version"] == 1
        assert schema["additionalProperties"] is False
        assert schema["properties"]
        assert all(
            "default" in field and "scope" in field for field in schema["properties"].values()
        )


def test_browser_fixture_matches_adapter_schemas():
    fixture = Path(__file__).resolve().parents[2] / "frontend/e2e/fixtures/methods.json"
    methods = json.loads(fixture.read_text())
    assert {method["id"] for method in methods} == set(REGISTRY)
    for method in methods:
        assert method["settings_schema"] == REGISTRY[method["id"]].options_model.schema()


def test_settings_migration_failure_rolls_back_column_and_revision(environment, monkeypatch):
    command.downgrade(configuration(), "8d4af912ab63")
    upgrade = command.upgrade

    def fail_after_upgrade(*args, **kwargs):
        upgrade(*args, **kwargs)
        raise RuntimeError("injected post-DDL failure")

    monkeypatch.setattr(migration_module.command, "upgrade", fail_after_upgrade)
    with pytest.raises(RuntimeError, match="post-DDL"):
        migrate()
    with connect() as database:
        assert "settings" not in {row[1] for row in database.execute("PRAGMA table_info(links)")}
        assert (
            database.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "8d4af912ab63"
        )
