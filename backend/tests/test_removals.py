import copy
import json

import pytest
from app import topology
from app.db import connect
from app.planner import build
from app.security import AppError
from app.worker import Worker
from test_topology import payload, seeded


class StatefulRemote:
    """Simulate host generations, including a mutation followed by a lost reply."""

    def __init__(self, server, credential, namespace):
        self.server = server["id"]

    def install_agent(self):
        pass

    def close(self):
        pass

    def call(self, action, payload):
        cls = type(self)
        cls.calls.append((self.server, action))
        key = (self.server, payload["generation"])
        if action == "prepare":
            cls.journals[key] = (copy.deepcopy(cls.active.get(self.server)), payload["plan"])
        elif action == "apply":
            cls.active[self.server] = cls.journals[key][1]
        elif action == "rollback":
            if cls.rollback_offline:
                raise AppError("ssh_unreachable")
            previous = cls.journals.get(key, (None, None))[0]
            if previous is None:
                cls.active.pop(self.server, None)
            else:
                cls.active[self.server] = previous
        if cls.failure == action and self.server == cls.fail_server:
            raise AppError("ssh_unreachable" if action == "prepare" else "remote_failed")
        return {"ok": True}


@pytest.fixture
def deployment(admin, monkeypatch):
    value = seeded(admin)
    value["links"] = value["links"][:1]
    value["links"][0]["method"] = "gre"
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    remote = type(
        "IsolatedRemote",
        (StatefulRemote,),
        {
            "active": {},
            "journals": {},
            "calls": [],
            "failure": None,
            "fail_server": value["links"][0]["exit_id"],
            "rollback_offline": False,
        },
    )
    monkeypatch.setattr("app.worker.settings.MAX_ATTEMPTS", 1)
    worker = Worker(remote)
    assert worker.acquire()
    worker.process(worker.claim())
    with connect() as db:
        original = topology.desired(db, True)
    return worker, remote, original


def remove(admin, original, *, server=False, disable=False):
    value = payload(admin.get("/api/v1/topology").json())
    if disable:
        value["links"][0]["enabled"] = False
    else:
        value["links"] = []
    if server:
        value["servers"] = [
            s for s in value["servers"] if s["id"] != original["links"][0]["exit_id"]
        ]
    response = admin.put("/api/v1/topology", json=value)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("phase", ["prepare", "apply", "health", "commit"])
def test_failed_deletion_rolls_back_both_hosts_and_remains_visible(admin, deployment, phase):
    worker, remote, original = deployment
    before = copy.deepcopy(remote.active)
    result = remove(admin, original)
    assert admin.get("/api/v1/topology").json()["pending_removals"][0]["status"] == "pending"
    remote.failure = phase
    worker.process(worker.claim())
    assert remote.active == before
    value = admin.get("/api/v1/topology").json()
    assert value["links"] == []
    assert value["applied_revision"] == original["revision"]
    pending = value["pending_removals"][0]
    assert pending["link"]["id"] == original["links"][0]["id"]
    assert pending["status"] == "failed"
    assert "encrypted" not in json.dumps(value)
    assert "slot" not in pending["link"]
    assert original["links"][0]["encrypted"] not in json.dumps(value)
    assert admin.get("/api/v1/jobs").json()[0]["status"] == "failed"
    remote.failure = None
    retry = admin.post(
        f'/api/v1/links/{pending["link"]["id"]}/retry-removal',
        json={"revision": result["revision"]},
    )
    assert retry.status_code == 202
    # A repeated click cannot queue a second removal.
    assert (
        admin.post(
            f'/api/v1/links/{pending["link"]["id"]}/retry-removal',
            json={"revision": result["revision"]},
        ).status_code
        == 409
    )
    worker.process(worker.claim())
    assert admin.get("/api/v1/topology").json()["pending_removals"] == []
    assert all(not plan["units"] for plan in remote.active.values())


@pytest.mark.parametrize("mode", ["link", "server", "disable"])
def test_restore_preserves_identity_and_requires_no_remote_change(admin, deployment, mode):
    worker, remote, original = deployment
    result = remove(admin, original, server=mode == "server", disable=mode == "disable")
    remote.failure = "apply"
    worker.process(worker.claim())
    value = admin.get("/api/v1/topology").json()
    assert len(value["removal_servers"]) == (1 if mode == "server" else 0)
    link = original["links"][0]
    path = f'/api/v1/links/{link["id"]}/restore'
    assert admin.post(path, json={"revision": result["revision"] - 1}).status_code == 409
    response = admin.post(path, json={"revision": result["revision"]})
    assert response.status_code == 202, response.text
    with connect() as db:
        restored = topology.desired(db, True)
    assert restored["links"][0]["slot"] == link["slot"]
    assert restored["links"][0]["encrypted"] == link["encrypted"]
    assert build(restored) == build(original)
    remote.calls.clear()
    worker.process(worker.claim())
    assert remote.calls == []
    assert admin.get("/api/v1/topology").json()["pending_removals"] == []


def test_uncertain_rollback_keeps_removal_visible_and_blocks_actions(admin, deployment):
    worker, remote, original = deployment
    result = remove(admin, original)
    remote.failure = "apply"
    remote.rollback_offline = True
    worker.process(worker.claim())
    value = admin.get("/api/v1/topology").json()
    assert value["pending_removals"][0]["status"] == "recovery_required"
    for action in ("restore", "retry-removal"):
        response = admin.post(
            f'/api/v1/links/{original["links"][0]["id"]}/{action}',
            json={"revision": result["revision"]},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "recovery_required"
    job = admin.get("/api/v1/jobs").json()[0]
    remote.rollback_offline = False
    assert admin.post(f'/api/v1/jobs/{job["id"]}/recover').status_code == 202
    worker.process(worker.claim())
    assert remote.active == {key: plan for key, plan in build(original).items() if plan["units"]}
    assert admin.get("/api/v1/topology").json()["pending_removals"][0]["status"] == "failed"


def test_cancelled_deletion_and_actions_require_admin(admin, deployment):
    worker, remote, original = deployment
    result = remove(admin, original)
    assert admin.post(f'/api/v1/jobs/{result["job_id"]}/cancel').status_code == 202
    value = admin.get("/api/v1/topology").json()
    assert value["pending_removals"][0]["status"] == "cancelled"
    admin.cookies.clear()
    for action in ("restore", "retry-removal"):
        assert (
            admin.post(
                f'/api/v1/links/{original["links"][0]["id"]}/{action}',
                json={"revision": result["revision"]},
            ).status_code
            == 401
        )


def test_no_phantom_removal_for_never_applied_link(admin):
    value = seeded(admin)
    assert admin.put("/api/v1/topology", json={**payload(value), "links": []}).status_code == 200
    assert admin.get("/api/v1/topology").json()["pending_removals"] == []


def test_cancellation_after_partial_removal_restores_both_hosts(admin, deployment, monkeypatch):
    worker, remote, original = deployment
    before = copy.deepcopy(remote.active)
    result = remove(admin, original)
    call = remote.call
    cancelled = False

    def cancel_after_apply(self, action, body):
        nonlocal cancelled
        reply = call(self, action, body)
        if action == "apply" and not cancelled:
            cancelled = True
            assert admin.post(f'/api/v1/jobs/{result["job_id"]}/cancel').status_code == 202
        return reply

    monkeypatch.setattr(remote, "call", cancel_after_apply)
    worker.process(worker.claim())
    assert cancelled and remote.active == before
    assert admin.get("/api/v1/topology").json()["pending_removals"][0]["status"] == "cancelled"


@pytest.mark.parametrize("action", ["restore", "retry-removal"])
def test_actions_reject_running_jobs_and_non_admin_keys(admin, deployment, action):
    worker, remote, original = deployment
    result = remove(admin, original)
    path = f'/api/v1/links/{original["links"][0]["id"]}/{action}'
    job = worker.claim()
    assert admin.post(path, json={"revision": result["revision"]}).json()["code"] == "removal_busy"
    assert admin.get("/api/v1/topology").json()["pending_removals"][0]["status"] == "removing"
    remote.failure = "apply"
    worker.process(job)
    key = admin.post("/api/v1/keys", json={"name": "viewer", "scope": "read"}).json()["token"]
    admin.cookies.clear()
    admin.headers["Authorization"] = "Bearer " + key
    assert admin.post(path, json={"revision": result["revision"]}).status_code == 403


def test_restore_rejects_changed_endpoint_atomically(admin, deployment):
    worker, remote, original = deployment
    result = remove(admin, original)
    remote.failure = "apply"
    worker.process(worker.claim())
    server = original["links"][0]["entry_id"]
    with connect(True) as db:
        db.execute("UPDATE servers SET address='192.0.2.199' WHERE id=?", (server,))
    path = f'/api/v1/links/{original["links"][0]["id"]}/restore'
    response = admin.post(path, json={"revision": result["revision"]})
    assert response.status_code == 409
    assert response.json()["code"] == "restore_endpoint_changed"
    value = admin.get("/api/v1/topology").json()
    assert value["revision"] == result["revision"] and not value["links"]
    assert len(value["pending_removals"]) == 1


@pytest.mark.parametrize("native", [False, True])
def test_agent_removal_and_rollback_restore_units_and_network_state(
    admin, deployment, tmp_path, monkeypatch, native
):
    from types import SimpleNamespace

    from app.planner import empty
    from app.remote_agent import Agent, atomic_json

    _, _, original = deployment
    if native:
        original["links"][0]["ports"] = [
            {"public": "1148-1149", "target": "1148-1149", "host": "127.0.0.1"}
        ]
    agent = Agent(original["namespace"], root=tmp_path / "agent")
    agent.units = tmp_path / "units"
    agent.units.mkdir()
    commands = []
    monkeypatch.setattr(
        "app.remote_agent.run",
        lambda args, **kw: commands.append(args) or SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr("app.remote_agent.shutil.which", lambda _: True)
    monkeypatch.setattr(agent, "preflight", lambda _: None)
    monkeypatch.setattr(agent, "network_down", lambda: commands.append(["network_down"]))
    monkeypatch.setattr(agent, "firewall", lambda rules: commands.append(["firewall", rules]))
    plan = build(original)[original["links"][0]["entry_id"]]
    plan = json.loads(
        json.dumps(plan).replace(f'/var/lib/meshdock/{original["namespace"]}', str(agent.root))
    )
    previous = agent.generation("1" * 32)
    previous.mkdir(parents=True)
    for name, content in {**plan["units"], **plan["files"]}.items():
        (previous / name).write_text(content)
    atomic_json(previous / "manifest.json", plan)
    agent.switch(previous)
    removed = agent.generation("2" * 32)
    removed.mkdir()
    atomic_json(removed / "manifest.json", empty())
    atomic_json(removed / "journal.json", {"phase": "prepared", "previous": previous.name})
    commands.clear()
    agent.apply(removed.name)
    assert all(not (agent.units / unit).is_symlink() for unit in plan["units"])
    assert all(["systemctl", "stop", unit] in commands for unit in plan["units"])
    assert ["firewall", []] in commands
    commands.clear()
    agent.rollback(removed.name)
    assert agent.current() == previous
    assert all((agent.units / unit).resolve() == previous / unit for unit in plan["units"])
    assert all(["systemctl", "start", unit] in commands for unit in plan["units"])
    assert ["firewall", plan["firewall"]] in commands
    if native:
        assert ["network_down"] in commands
        assert any(
            command[:2] == ["systemctl", "start"] and command[-1].endswith("-network.service")
            for command in commands
        )
    commands.clear()
    agent.rollback(removed.name)
    assert commands == []


def test_restore_validates_against_other_pending_connections(admin, deployment):
    from app.db import uid

    worker, remote, original = deployment
    remove(admin, original)
    remote.failure = "apply"
    worker.process(worker.claim())
    value = admin.get("/api/v1/topology").json()
    # A new, unapplied connection uses the same public listener with another policy.
    candidate = value["pending_removals"][0]["link"].copy()
    candidate.update(id=uid(), policy="failover")
    value["links"] = [candidate]
    updated = admin.put("/api/v1/topology", json=payload(value)).json()
    assert admin.post(f'/api/v1/jobs/{updated["job_id"]}/cancel').status_code == 202
    response = admin.post(
        f'/api/v1/links/{original["links"][0]["id"]}/restore',
        json={"revision": updated["revision"]},
    )
    assert response.status_code == 400 and response.json()["code"] == "pool_policy"
    after = admin.get("/api/v1/topology").json()
    assert after["links"] == [candidate]
    assert after["revision"] == updated["revision"]
    assert len(after["pending_removals"]) == 1
