from app import topology
from app.db import connect
from app.planner import build
from app.security import AppError
from app.worker import Worker


def seeded(admin):
    response = admin.post("/api/v1/demo/seed")
    assert response.status_code == 200, response.text
    return admin.get("/api/v1/topology").json()


def payload(value):
    return {key: value[key] for key in ("revision", "servers", "links")}


def test_revision_conflict_and_non_deploying_positions(admin):
    value = seeded(admin)
    count = len(admin.get("/api/v1/jobs").json())
    server = value["servers"][0]["id"]
    assert (
        admin.patch(
            "/api/v1/positions", json={"positions": {server: {"x": 999, "y": 555}}}
        ).status_code
        == 200
    )
    assert len(admin.get("/api/v1/jobs").json()) == count
    bad = payload(value)
    bad["revision"] = 0
    assert admin.put("/api/v1/topology", json=bad).status_code == 409


def test_method_registry_compiles_every_adapter(admin):
    value = seeded(admin)
    for method in admin.get("/api/v1/methods").json():
        value = admin.get("/api/v1/topology").json()
        for link in value["links"]:
            link["method"] = method["id"]
        response = admin.put("/api/v1/topology", json=payload(value))
        assert response.status_code == 200, response.text
        with connect() as database:
            plans = build(topology.desired(database, True))
        assert all(
            "token" not in str(row) for row in admin.get("/api/v1/preview").json()
        )
        assert any(p["units"] for p in plans.values())
        if method["id"] == "hysteria2":
            assert any(p["udp_listeners"] for p in plans.values())


def test_cycles_conflicting_pools_and_credentials_in_use(admin):
    value = seeded(admin)
    assert (
        admin.delete(
            "/api/v1/credentials/" + value["servers"][0]["credential_id"]
        ).status_code
        == 409
    )
    value["links"][1]["policy"] = "leastconn"
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 400
    value["links"][1]["policy"] = "roundrobin"
    value["links"][0]["ports"][0]["public"] = 20001
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 400


class RecordingRemote:
    calls = []
    fail_apply = False
    fail_rollback = False

    def __init__(self, *args):
        pass

    def install_agent(self):
        pass

    def close(self):
        pass

    def call(self, action, payload):
        self.calls.append(action)
        if self.fail_apply and action == "apply":
            raise AppError("remote_failed")
        if self.fail_rollback and action == "rollback":
            raise OSError("offline")
        return {"ok": True}


def test_success_and_cleanup(admin):
    value = seeded(admin)
    worker = Worker(RecordingRemote)
    assert worker.acquire()
    worker.process(worker.claim())
    assert admin.get("/api/v1/jobs").json()[0]["status"] == "succeeded"
    assert admin.get("/api/v1/topology").json()["applied_revision"] == value["revision"]
    assert (
        admin.post("/api/v1/cleanup", json={"revision": value["revision"]}).status_code
        == 202
    )
    with connect() as database:
        plans = build(topology.desired(database, True))
    assert all(not p["units"] and not p["firewall"] for p in plans.values())
    worker.process(worker.claim())
    assert admin.get("/api/v1/jobs").json()[0]["status"] == "succeeded"


def test_failed_activation_compensates_and_retries(admin, monkeypatch):
    seeded(admin)
    monkeypatch.setattr(RecordingRemote, "fail_apply", True)
    RecordingRemote.calls = []
    worker = Worker(RecordingRemote)
    assert worker.acquire()
    worker.process(worker.claim())
    assert "rollback" in RecordingRemote.calls
    assert admin.get("/api/v1/jobs").json()[0]["status"] == "retrying"
    assert admin.get("/api/v1/topology").json()["applied_revision"] == 0


def test_unreachable_rollback_blocks_new_deployments(admin, monkeypatch):
    value = seeded(admin)
    monkeypatch.setattr(RecordingRemote, "fail_apply", True)
    monkeypatch.setattr(RecordingRemote, "fail_rollback", True)
    worker = Worker(RecordingRemote)
    worker.acquire()
    worker.process(worker.claim())
    job = admin.get("/api/v1/jobs").json()[0]
    assert job["status"] == "recovery_required"
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 409
    monkeypatch.setattr(RecordingRemote, "fail_rollback", False)
    assert admin.post("/api/v1/jobs/" + job["id"] + "/recover").status_code == 202
    worker.process(worker.claim())
    assert admin.get("/api/v1/jobs").json()[0]["error_code"] == "recovered"


def test_host_replacement_includes_old_endpoint_for_cleanup(admin):
    from app.worker import targets

    value = seeded(admin)
    with connect() as database:
        previous = topology.desired(database, True)
    value["servers"][0]["host"] = "192.0.2.199"
    value["servers"][0]["address"] = "192.0.2.199"
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    with connect() as database:
        desired = topology.desired(database, True)
    fleet = targets(previous, desired)
    assert len(fleet) == len(value["servers"]) + 1
    old = next(t for t in fleet if t.identity == "192.0.2.10:22")
    assert not old.plan["units"]
