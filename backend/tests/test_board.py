import json

import pytest
from alembic import command
from app.db import connect
from app.migrate import configuration, migrate
from test_removals import deployment as deployment
from test_topology import payload, seeded


def current(admin):
    return admin.get("/api/v1/topology").json()


def place(admin, value, id, hidden=True, **extra):
    return admin.patch(
        f"/api/v1/servers/{id}/board",
        json={"revision": value["revision"], "hidden": hidden, **extra},
    )


@pytest.fixture
def unused(admin):
    value = seeded(admin)
    server = {**value["servers"][0], "id": "f" * 32, "host": "192.0.2.99", "address": "192.0.2.99"}
    value["servers"].append(server)
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    return current(admin), server


def test_hide_restore_persists_without_deployment_or_snapshot_changes(admin, unused):
    value, server = unused
    with connect() as db:
        jobs = [tuple(row) for row in db.execute("SELECT * FROM jobs")]
        applied = db.execute("SELECT applied FROM state").fetchone()[0]
    assert place(admin, value, server["id"]).status_code == 200
    migrate()
    after = current(admin)
    assert after["hidden_server_ids"] == [server["id"]]
    assert after["servers"] == value["servers"] and after["revision"] == value["revision"]
    assert after["links"] == value["links"]
    assert place(admin, value, server["id"], False, position={"x": 42, "y": 100}).status_code == 200
    after = current(admin)
    assert after["hidden_server_ids"] == []
    assert next(s for s in after["servers"] if s["id"] == server["id"])["position"]["x"] == 42
    with connect() as db:
        assert jobs == [tuple(row) for row in db.execute("SELECT * FROM jobs")]
        assert applied == db.execute("SELECT applied FROM state").fetchone()[0]
        assert (
            db.execute("SELECT COUNT(*) FROM audit WHERE action LIKE 'board_%'").fetchone()[0] == 2
        )


def test_board_requires_write_scope_existing_server_and_current_revision(admin, unused):
    value, server = unused
    assert (
        place(admin, {**value, "revision": value["revision"] - 1}, server["id"]).status_code == 409
    )
    assert place(admin, value, "0" * 32).status_code == 404
    key = admin.post("/api/v1/keys", json={"name": "viewer", "scope": "read"})
    # Use a separate bearer-authenticated client; sessions must not override the scope.
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as viewer:
        assert (
            viewer.patch(
                f'/api/v1/servers/{server["id"]}/board',
                json={"revision": value["revision"], "hidden": True},
            ).status_code
            == 401
        )
        viewer.headers["Authorization"] = "Bearer " + key.json()["token"]
        assert place(viewer, value, server["id"]).status_code == 403


def test_connected_and_disabled_links_cannot_be_hidden(admin, unused):
    value, _ = unused
    server_id = value["links"][0]["entry_id"]
    response = place(admin, value, server_id)
    assert response.status_code == 409 and response.json()["code"] == "board_server_in_use"
    for link in value["links"]:
        link["enabled"] = False
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    assert place(admin, current(admin), server_id).status_code == 409


def test_jump_reveals_both_endpoints_and_reciprocal_routes_are_independent(admin, unused):
    value, jump = unused
    assert place(admin, value, jump["id"]).status_code == 200
    target = value["servers"][0]

    def config(server):
        return {
            key: server[key] for key in ("host", "ssh_port", "credential_id", "fingerprint")
        } | {"username": "root"}

    target["ssh_jump"] = config(jump)
    jump["ssh_jump"] = config(target)
    # Fixture's returned server is separate from the fetched list.
    value["servers"][-1] = jump
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    after = current(admin)
    assert after["hidden_server_ids"] == []
    assert {(j["source_id"], j["target_id"]) for j in after["jump_connections"]} == {
        (target["id"], jump["id"]),
        (jump["id"], target["id"]),
    }
    for id in (target["id"], jump["id"]):
        assert place(admin, after, id).status_code == 409
    # No credentials or fingerprints in the visual relationship contract.
    assert "credential" not in json.dumps(after["jump_connections"])
    assert "SHA256" not in json.dumps(after["jump_connections"])
    for server in after["servers"]:
        server["ssh_jump"] = None
    assert admin.put("/api/v1/topology", json=payload(after)).status_code == 200
    assert jump["id"] not in current(admin)["hidden_server_ids"]


def test_external_jump_and_address_alias_are_visible(admin, unused):
    value, server = unused
    target = value["servers"][0]
    target["ssh_jump"] = {
        "host": "jump.example.test",
        "ssh_port": 2222,
        "username": "ops",
        "credential_id": server["credential_id"],
        "fingerprint": server["fingerprint"],
    }
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    after = current(admin)
    assert after["jump_connections"][0]["source_id"] is None
    after["servers"][-1].update(host="jump.example.test", ssh_port=2222)
    assert admin.put("/api/v1/topology", json=payload(after)).status_code == 200
    assert current(admin)["jump_connections"][0]["source_id"] == server["id"]
    after = current(admin)
    after["servers"][0]["ssh_jump"]["host"] = server["address"]
    assert admin.put("/api/v1/topology", json=payload(after)).status_code == 200
    assert current(admin)["jump_connections"][0]["source_id"] == server["id"]


def test_failed_removal_and_retained_jump_cannot_disappear(admin, deployment):
    worker, remote, original = deployment
    value = current(admin)
    target = value["servers"][0]
    jump = value["servers"][-1]
    with connect(True) as db:
        applied = json.loads(db.execute("SELECT applied FROM state").fetchone()[0])
        saved = next(s for s in applied["servers"] if s["id"] == target["id"])
        saved["ssh_jump"] = {"host": jump["host"], "ssh_port": jump["ssh_port"]}
        db.execute("UPDATE state SET applied=?", (json.dumps(applied),))
    value["links"] = []
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    remote.failure = "apply"
    worker.process(worker.claim())
    after = current(admin)
    assert after["pending_removals"]
    assert any(j["retained"] and j["source_id"] == jump["id"] for j in after["jump_connections"])
    for id in (target["id"], jump["id"]):
        assert place(admin, after, id).status_code == 409


def test_board_migration_preserves_existing_servers_and_plans(admin, unused):
    value, _ = unused
    config = configuration()
    command.downgrade(config, "af62c83419de")
    migrate()
    migrate()
    after = current(admin)
    assert after["servers"] == value["servers"] and after["links"] == value["links"]
    assert after["hidden_server_ids"] == []
    command.check(config)
