import json
from types import SimpleNamespace

import pytest
from alembic import command
from app import migrate as migration_module
from app.db import connect
from app.migrate import configuration, migrate
from app.remote_agent import Agent
from app.security import AppError
from app.worker import Worker
from test_topology import payload, seeded


def test_cancel_queued_job_never_contacts_servers(admin):
    seeded(admin)
    job = admin.get("/api/v1/jobs").json()[0]
    assert admin.post(f'/api/v1/jobs/{job["id"]}/cancel').status_code == 202
    assert admin.post(f'/api/v1/jobs/{job["id"]}/cancel').status_code == 202
    result = admin.get("/api/v1/jobs").json()[0]
    assert result["status"] == "cancelled" and result["cancel_requested"] == 1
    assert "snapshot" not in result and "encrypted" not in str(result)
    worker = Worker(lambda *_: pytest.fail("Cancelled job contacted a server"))
    assert worker.acquire() and worker.claim() is None


@pytest.mark.parametrize("cancel_during", ["prepare", "apply", "health", "commit"])
def test_cancel_at_safe_boundary_restores_real_generations(
    admin, tmp_path, monkeypatch, cancel_during
):
    agents, calls = {}, []
    cancel_id = None
    fired = False

    def switch(agent, target):
        pointer = agent.root / "current"
        pointer.unlink(missing_ok=True)
        if target:
            pointer.symlink_to(target)

    monkeypatch.setattr(Agent, "switch", switch)
    monkeypatch.setattr(Agent, "preflight", lambda *a: None)
    monkeypatch.setattr(Agent, "dependencies", lambda *a: None)
    monkeypatch.setattr("app.remote_agent.shutil.which", lambda _: "/test/ss")
    monkeypatch.setattr("app.remote_agent.run", lambda *a, **kw: SimpleNamespace(returncode=0))

    class LocalRemote:
        def __init__(self, server, credential, namespace):
            self.agent = agents.setdefault(
                server["id"], Agent(namespace, root=tmp_path / server["id"])
            )

        def install_agent(self):
            pass

        def close(self):
            pass

        def call(self, action, body):
            nonlocal fired
            calls.append(action)
            body = dict(body)
            self.agent.accept_fence(body.pop("fence"))
            if action != "health":
                getattr(self.agent, action)(**body)
            if cancel_id and action == cancel_during and not fired:
                # Cancellation arrives while an operation is in flight; finish
                # the operation first, then compensate at the next boundary.
                assert admin.post(f"/api/v1/jobs/{cancel_id}/cancel").status_code == 202
                fired = True
            return {"ok": True}

    value = seeded(admin)
    worker = Worker(LocalRemote)
    assert worker.acquire()
    worker.process(worker.claim())
    previous = {id: agent.current() for id, agent in agents.items()}
    value = admin.get("/api/v1/topology").json()
    revision = value["applied_revision"]
    value["links"][0].update(method="backhaul", settings={"transport": "wssmux"})
    response = admin.put("/api/v1/topology", json=payload(value))
    assert response.status_code == 200
    cancel_id = response.json()["job_id"]
    calls.clear()
    worker.process(worker.claim())
    result = admin.get("/api/v1/jobs").json()[0]
    assert result["status"] == "cancelled"
    assert fired and "rollback" in calls
    assert all(agent.current() == previous[id] for id, agent in agents.items())
    assert admin.get("/api/v1/topology").json()["applied_revision"] == revision
    assert worker.claim() is None
    with connect() as db:
        applied = json.loads(db.execute("SELECT applied FROM state").fetchone()[0])
    assert applied["revision"] == revision


def test_cancel_with_unreachable_rollback_requires_recovery(admin):
    seeded(admin)
    job_id = admin.get("/api/v1/jobs").json()[0]["id"]

    class Unreachable:
        def __init__(self, *args):
            pass

        def install_agent(self):
            pass

        def close(self):
            pass

        def call(self, action, body):
            if action == "apply":
                admin.post(f"/api/v1/jobs/{job_id}/cancel")
            if action == "rollback":
                raise AppError("ssh_unreachable")
            return {"ok": True}

    worker = Worker(Unreachable)
    assert worker.acquire()
    worker.process(worker.claim())
    assert admin.get("/api/v1/jobs").json()[0]["status"] == "recovery_required"
    assert worker.claim() is None


def test_cancel_migration_is_repeatable_and_failure_atomic(admin, monkeypatch):
    seeded(admin)
    job_id = admin.get("/api/v1/jobs").json()[0]["id"]
    command.downgrade(configuration(), "6f3c98a12d04")
    upgrade = command.upgrade

    def fail(*args, **kwargs):
        upgrade(*args, **kwargs)
        raise RuntimeError("injected cancellation migration failure")

    monkeypatch.setattr(migration_module.command, "upgrade", fail)
    with pytest.raises(RuntimeError):
        migrate()
    with connect() as db:
        assert "cancel_requested" not in {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "6f3c98a12d04"
    monkeypatch.setattr(migration_module.command, "upgrade", upgrade)
    migrate()
    migrate()
    with connect() as db:
        assert "cancel_requested" in {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
        row = db.execute(
            "SELECT status,cancel_requested FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        assert tuple(row) == ("queued", 0)


def test_cancel_requires_admin_scope(admin):
    seeded(admin)
    job = admin.get("/api/v1/jobs").json()[0]
    key = admin.post("/api/v1/keys", json={"name": "reader", "scope": "read"}).json()["token"]
    admin.cookies.clear()
    admin.headers["Authorization"] = "Bearer " + key
    assert admin.post(f'/api/v1/jobs/{job["id"]}/cancel').status_code == 403


def test_cancelled_worker_crash_recovers_before_new_work(admin):
    seeded(admin)
    worker = Worker()
    assert worker.acquire()
    job = worker.claim()
    admin.post(f'/api/v1/jobs/{job["id"]}/cancel')
    with connect(True) as db:
        db.execute("UPDATE leader SET until=0")
    replacement = Worker()
    assert replacement.acquire()
    recovering = replacement.claim()
    assert recovering["status"] == "recovering"
    replacement.process(recovering)
    assert admin.get("/api/v1/jobs").json()[0]["status"] == "cancelled"
