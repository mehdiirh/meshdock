import copy
import json

import pytest
from app import topology
from app.db import connect
from app.planner import build
from app.security import AppError
from app.worker import Worker
from test_removals import deployment as deployment
from test_removals import remove
from test_topology import payload


@pytest.fixture
def fleet(admin, deployment, monkeypatch):
    worker, remote, original = deployment
    original_init = remote.__init__
    remote.offline = set()
    remote.probes = []

    def connect_host(self, server, credential, namespace):
        remote.probes.append(server["id"])
        if server["id"] in remote.offline:
            raise AppError("ssh_unreachable")
        original_init(self, server, credential, namespace)

    monkeypatch.setattr(remote, "__init__", connect_host)
    return worker, remote, original


def request(admin, original):
    server_id = original["links"][0]["exit_id"]
    revision = admin.get("/api/v1/topology").json()["revision"]
    response = admin.post(f"/api/v1/servers/{server_id}/force-delete", json={"revision": revision})
    assert response.status_code == 202, response.text
    return response.json()


def latest(admin):
    return admin.get("/api/v1/jobs").json()[0]


def test_missing_target_cleans_peer_and_forgets_only_target(admin, fleet):
    worker, remote, original = fleet
    link = original["links"][0]
    remote.offline = {link["exit_id"]}
    before = copy.deepcopy(remote.active)
    result = request(admin, original)
    # The card remains while the operation is queued.
    assert link["exit_id"] in {s["id"] for s in admin.get("/api/v1/topology").json()["servers"]}
    worker.process(worker.claim())
    assert set(remote.probes) >= {link["entry_id"], link["exit_id"]}
    assert not remote.active[link["entry_id"]]["units"]
    assert remote.active[link["exit_id"]] == before[link["exit_id"]]
    job = latest(admin)
    assert job["id"] == result["job_id"] and job["status"] == "succeeded"
    statuses = {host["server_id"]: host["status"] for host in job["force_delete"]["hosts"]}
    assert statuses == {link["entry_id"]: "cleaned", link["exit_id"]: "skipped"}
    assert job["error_code"] == "force_delete_orphans"
    value = admin.get("/api/v1/topology").json()
    assert link["exit_id"] not in {s["id"] for s in value["servers"]}
    assert not value["links"] and not value["pending_removals"]
    assert "encrypted" not in json.dumps(job) and "receipt" not in job and "snapshot" not in job


def test_both_unreachable_require_explicit_skip_and_keep_audit(admin, fleet):
    worker, remote, original = fleet
    remote.offline = {s["id"] for s in original["servers"]}
    result = request(admin, original)
    worker.process(worker.claim())
    job = latest(admin)
    assert job["status"] == "waiting_cleanup" and job["force_delete"]["can_skip"]
    current = admin.get("/api/v1/topology").json()
    assert current["links"]
    assert (
        admin.put("/api/v1/topology", json=payload(current)).json()["code"] == "force_delete_busy"
    )
    assert (
        admin.post("/api/v1/reconcile", json={"revision": current["revision"]}).status_code == 409
    )
    assert admin.post(f'/api/v1/jobs/{job["id"]}/cancel').status_code == 409
    path = f'/api/v1/jobs/{job["id"]}/skip-cleanup'
    assert admin.post(path, json={"revision": result["revision"] - 1}).status_code == 409
    assert admin.post(path, json={"revision": result["revision"]}).status_code == 202
    remote.probes.clear()
    worker.process(worker.claim())
    assert not remote.probes
    assert latest(admin)["status"] == "succeeded"
    assert {host["status"] for host in latest(admin)["force_delete"]["hosts"]} == {"skipped"}
    with connect() as db:
        actions = {r[0] for r in db.execute("SELECT action FROM audit")}
    assert {
        "force_delete_requested",
        "force_delete_skip_confirmed",
        "server_force_deleted",
    } <= actions


def test_retry_cleans_remaining_endpoint_without_repeating_completed_peer(admin, fleet):
    worker, remote, original = fleet
    entry = original["links"][0]["entry_id"]
    remote.offline = {entry}
    result = request(admin, original)
    worker.process(worker.claim())
    assert latest(admin)["status"] == "waiting_cleanup"
    remote.offline.clear()
    remote.calls.clear()
    assert (
        admin.post(
            f'/api/v1/jobs/{result["job_id"]}/retry-cleanup', json={"revision": result["revision"]}
        ).status_code
        == 202
    )
    worker.process(worker.claim())
    assert {server for server, _ in remote.calls} == {entry}
    assert latest(admin)["status"] == "succeeded"
    assert latest(admin)["error_code"] is None


@pytest.mark.parametrize("phase", ["prepare", "apply", "health", "commit"])
def test_cleanup_failure_still_checks_and_cleans_other_endpoint(admin, fleet, phase):
    worker, remote, original = fleet
    before = copy.deepcopy(remote.active)
    remote.failure = phase
    remote.fail_server = original["links"][0]["exit_id"]
    result = request(admin, original)
    worker.process(worker.claim())
    job = latest(admin)
    assert job["status"] == "waiting_cleanup"
    assert sorted(h["status"] for h in job["force_delete"]["hosts"]) == ["cleaned", "failed"]
    assert not job["force_delete"]["can_skip"]
    assert remote.active[remote.fail_server] == before[remote.fail_server]
    assert (remote.fail_server, "rollback") in remote.calls
    assert (
        admin.post(
            f'/api/v1/jobs/{result["job_id"]}/skip-cleanup', json={"revision": result["revision"]}
        ).status_code
        == 409
    )
    remote.failure = None
    assert (
        admin.post(
            f'/api/v1/jobs/{result["job_id"]}/retry-cleanup', json={"revision": result["revision"]}
        ).status_code
        == 202
    )
    worker.process(worker.claim())
    assert latest(admin)["status"] == "succeeded"


def test_force_removal_takes_over_failed_deletion_recovery(admin, fleet):
    worker, remote, original = fleet
    remove(admin, original, server=True)
    remote.offline = {original["links"][0]["exit_id"]}
    worker.process(worker.claim())
    assert latest(admin)["status"] == "recovery_required"
    old = latest(admin)["id"]
    request(admin, original)
    worker.process(worker.claim())
    assert latest(admin)["status"] == "succeeded"
    assert not admin.get("/api/v1/topology").json()["pending_removals"]
    with connect() as db:
        assert (
            db.execute("SELECT status FROM jobs WHERE id=?", (old,)).fetchone()[0] == "superseded"
        )


def test_auth_and_key_errors_do_not_authorize_skipping(admin, fleet, monkeypatch):
    worker, remote, original = fleet
    old = worker.remote
    target = original["links"][0]["exit_id"]

    def changed_key(server, namespace):
        if server["id"] == target:
            raise AppError("host_key_changed")
        return old(server, namespace)

    monkeypatch.setattr(worker, "remote", changed_key)
    request(admin, original)
    worker.process(worker.claim())
    assert latest(admin)["status"] == "waiting_cleanup"
    assert not latest(admin)["force_delete"]["can_skip"]


def test_crash_recovery_resumes_cleanup_instead_of_restoring_removed_peer(
    admin, fleet, monkeypatch
):
    worker, remote, original = fleet
    request(admin, original)
    operate = worker.operate
    crashed = False

    def crash(server, namespace, action, body, **kwargs):
        nonlocal crashed
        value = operate(server, namespace, action, body, **kwargs)
        if action == "commit" and not crashed:
            crashed = True
            raise KeyboardInterrupt()
        return value

    monkeypatch.setattr(worker, "operate", crash)
    with pytest.raises(KeyboardInterrupt):
        worker.process(worker.claim())
    with connect(True) as db:
        db.execute("UPDATE leader SET until=0")
    replacement = Worker(remote)
    assert replacement.acquire()
    job = replacement.claim()
    assert job["status"] == "recovering"
    replacement.process(job)
    assert latest(admin)["status"] == "succeeded"
    assert not any(action == "rollback" for _, action in remote.calls)
    assert all(not plan["units"] for plan in remote.active.values())


def test_force_delete_rejects_stale_revision_and_non_admin(admin, fleet):
    worker, remote, original = fleet
    target = original["links"][0]["exit_id"]
    path = f"/api/v1/servers/{target}/force-delete"
    revision = admin.get("/api/v1/topology").json()["revision"]
    assert admin.post(path, json={"revision": revision - 1}).status_code == 409
    key = admin.post("/api/v1/keys", json={"name": "reader", "scope": "read"}).json()["token"]
    admin.cookies.clear()
    admin.headers["Authorization"] = "Bearer " + key
    assert admin.post(path, json={"revision": revision}).status_code == 403


def test_shared_entry_keeps_other_tunnel_and_skipped_slots_stay_reserved(admin, fleet):
    from app.db import uid

    worker, remote, original = fleet
    value = payload(admin.get("/api/v1/topology").json())
    extra = copy.deepcopy(value["links"][0])
    other_exit = next(
        s for s in value["servers"] if s["role"] == "exit" and s["id"] != extra["exit_id"]
    )
    extra.update(
        id=uid(),
        exit_id=other_exit["id"],
        ports=[{"public": 9443, "target": 9443, "host": "127.0.0.1"}],
    )
    value["links"].append(extra)
    assert admin.put("/api/v1/topology", json=value).status_code == 200
    worker.process(worker.claim())
    with connect() as db:
        applied = topology.desired(db, True)
    remaining = copy.deepcopy(applied)
    target = applied["links"][0]["exit_id"]
    slot = applied["links"][0]["slot"]
    remaining["links"] = remaining["links"][1:]
    remaining["servers"] = [s for s in remaining["servers"] if s["id"] != target]
    remote.offline = {target}
    request(admin, applied)
    worker.process(worker.claim())
    entry = applied["links"][0]["entry_id"]
    assert remote.active[entry] == build(remaining)[entry]
    assert remote.active[other_exit["id"]] == build(remaining)[other_exit["id"]]
    value = payload(admin.get("/api/v1/topology").json())
    value["links"].append(
        {**extra, "id": uid(), "ports": [{"public": 9553, "target": 9553, "host": "127.0.0.1"}]}
    )
    assert admin.put("/api/v1/topology", json=value).status_code == 200
    with connect() as db:
        assert slot not in {r[0] for r in db.execute("SELECT slot FROM links")}


def test_unrelated_pending_edits_are_not_deployed_by_force_delete(admin, fleet):
    worker, remote, original = fleet
    value = payload(admin.get("/api/v1/topology").json())
    other = next(
        s
        for s in value["servers"]
        if s["id"] not in (value["links"][0]["entry_id"], value["links"][0]["exit_id"])
    )
    other["host"] = "192.0.2.199"
    response = admin.put("/api/v1/topology", json=value).json()
    assert admin.post(f'/api/v1/jobs/{response["job_id"]}/cancel').status_code == 202
    remote.probes.clear()
    request(admin, original)
    worker.process(worker.claim())
    assert other["id"] not in remote.probes
    assert latest(admin)["status"] == "succeeded"


def test_lease_loss_stops_cleanup_before_mutation_and_keeps_pending_record(
    admin, fleet, monkeypatch
):
    worker, remote, original = fleet
    request(admin, original)
    job = worker.claim()
    before = copy.deepcopy(remote.active)
    with connect(True) as db:
        db.execute("UPDATE leader SET until=0")
    remote.calls.clear()
    worker.process(job)
    assert not remote.calls and remote.active == before
    assert latest(admin)["status"] == "running"
    assert worker.lease_lost.is_set()


def test_unrelated_recovery_cannot_be_bypassed(admin, fleet):
    worker, remote, original = fleet
    value = payload(admin.get("/api/v1/topology").json())
    value["links"][0]["ports"] = [{"public": 9999, "target": 9999, "host": "127.0.0.1"}]
    assert admin.put("/api/v1/topology", json=value).status_code == 200
    remote.failure = "apply"
    remote.rollback_offline = True
    worker.process(worker.claim())
    assert latest(admin)["status"] == "recovery_required"
    current = admin.get("/api/v1/topology").json()
    response = admin.post(
        f'/api/v1/servers/{original["links"][0]["exit_id"]}/force-delete',
        json={"revision": current["revision"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "force_delete_recovery_conflict"


def test_cleanup_failure_retries_then_keeps_uncertain_rollback_reviewable(
    admin, fleet, monkeypatch
):
    worker, remote, original = fleet
    monkeypatch.setattr("app.worker.settings.MAX_ATTEMPTS", 2)
    remote.failure = "apply"
    remote.rollback_offline = True
    result = request(admin, original)
    worker.process(worker.claim())
    assert latest(admin)["status"] == "retrying"
    with connect(True) as db:
        db.execute("UPDATE jobs SET next_run=0 WHERE id=?", (result["job_id"],))
    worker.process(worker.claim())
    assert latest(admin)["status"] == "waiting_cleanup"
    assert not latest(admin)["force_delete"]["can_skip"]
    with connect() as db:
        receipt = json.loads(
            db.execute("SELECT receipt FROM jobs WHERE id=?", (result["job_id"],)).fetchone()[0]
        )
    assert any(item.get("phase") == "uncertain" for item in receipt["hosts"])
    remote.failure = None
    remote.rollback_offline = False
    assert (
        admin.post(
            f'/api/v1/jobs/{result["job_id"]}/retry-cleanup', json={"revision": result["revision"]}
        ).status_code
        == 202
    )
    worker.process(worker.claim())
    assert latest(admin)["status"] == "succeeded"


def test_skipped_cleanup_protects_target_credential(admin, fleet):
    worker, remote, original = fleet
    value = payload(admin.get("/api/v1/topology").json())
    target = original["links"][0]["exit_id"]
    credential_id = admin.post(
        "/api/v1/credentials",
        json={
            "name": "retired fixture",
            "kind": "password",
            "secret": "synthetic-private-password",
        },
    ).json()["id"]
    next(server for server in value["servers"] if server["id"] == target)[
        "credential_id"
    ] = credential_id
    assert admin.put("/api/v1/topology", json=value).status_code == 200
    worker.process(worker.claim())
    remote.offline = {target}
    request(admin, original)
    worker.process(worker.claim())
    assert latest(admin)["status"] == "succeeded"
    assert admin.delete(f"/api/v1/credentials/{credential_id}").status_code == 409
    assert "synthetic-private-password" not in json.dumps(admin.get("/api/v1/jobs").json())
