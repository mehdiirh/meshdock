"""Real generation files/journals with simulated host commands; no network access."""

import json
from types import SimpleNamespace

import pytest
from app import remote_agent
from app.db import connect
from app.remote_agent import Agent
from app.security import AppError
from app.worker import Worker
from test_method_settings import CUSTOM
from test_topology import payload, seeded

CASES = [(method, {}, settings) for method, settings in CUSTOM.items()]
for method, transports in {
    "backhaul": ["tcp", "tcpmux", "ws", "wss", "wsmux", "wssmux"],
    "rathole": ["noise", "tcp", "tls", "ws", "wss"],
    "frp_wss": ["wss", "tcp", "kcp", "quic", "websocket"],
}.items():
    for index, transport in enumerate(transports):
        CASES.append((method, {"transport": transports[index - 1]}, {"transport": transport}))


@pytest.mark.parametrize("method,initial,changed", CASES)
def test_settings_deployment_health_failure_rollback_and_retry(
    admin, tmp_path, monkeypatch, method, initial, changed, changed_protocol=None
):
    agents = {}
    fail_health = False

    def local_switch(agent, target):
        pointer = agent.root / "current"
        pointer.unlink(missing_ok=True)
        if target:
            pointer.symlink_to(target)

    monkeypatch.setattr(Agent, "switch", local_switch)
    monkeypatch.setattr(Agent, "preflight", lambda *args: None)
    monkeypatch.setattr(Agent, "dependencies", lambda *args: None)
    monkeypatch.setattr(remote_agent.shutil, "which", lambda _: "/test/ss")
    monkeypatch.setattr(remote_agent, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr("app.worker.time.sleep", lambda _: None)

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
            body = dict(body)
            self.agent.accept_fence(body.pop("fence"))
            if action == "health":
                if fail_health:
                    raise AppError("health_failed")
            else:
                getattr(self.agent, action)(**body)
            return {"ok": True}

    value = seeded(admin)
    value["links"] = value["links"][:1]
    value["links"][0].update(method=method, settings=initial)
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    worker = Worker(LocalRemote)
    assert worker.acquire()
    worker.process(worker.claim())
    assert admin.get("/api/v1/jobs").json()[0]["status"] == "succeeded"
    previous = {key: agent.current() for key, agent in agents.items()}
    manifests = {key: (path / "manifest.json").read_bytes() for key, path in previous.items()}
    value = admin.get("/api/v1/topology").json()
    applied_revision = value["applied_revision"]
    value["links"][0]["settings"] = changed
    if changed_protocol:
        for mapping in value["links"][0]["ports"]:
            mapping["protocol"] = changed_protocol
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    fail_health = True
    worker.process(worker.claim())
    assert admin.get("/api/v1/jobs").json()[0]["status"] == "retrying"
    assert admin.get("/api/v1/topology").json()["applied_revision"] == applied_revision
    for key, agent in agents.items():
        assert agent.current() == previous[key]
        assert (agent.current() / "manifest.json").read_bytes() == manifests[key]
        for name, contents in agent.manifest(agent.current())["files"].items():
            assert (agent.current() / name).read_text() == contents
    with connect() as database:
        applied = json.loads(database.execute("SELECT applied FROM state").fetchone()[0])
        assert applied["links"][0]["settings"] == initial
    fail_health = False
    with connect(True) as database:
        database.execute("UPDATE jobs SET next_run=0 WHERE status='retrying'")
    worker.process(worker.claim())
    assert admin.get("/api/v1/jobs").json()[0]["status"] == "succeeded"
    with connect() as database:
        applied = json.loads(database.execute("SELECT applied FROM state").fetchone()[0])
        assert applied["links"][0]["settings"] == changed
    assert any(
        (agent.current() / "manifest.json").read_bytes() != manifests[key]
        for key, agent in agents.items()
    )


@pytest.mark.parametrize(
    "method,settings,protocol",
    [
        ("gre", {}, "both"),
        ("backhaul", {"transport": "tcp"}, "both"),
        ("backhaul", {"transport": "udp"}, "udp"),
        ("rathole", {"transport": "tls"}, "both"),
        ("frp_wss", {"transport": "quic"}, "both"),
        ("hysteria2", {}, "both"),
    ],
)
def test_udp_deployment_failure_restores_tcp_generation_then_retries(
    admin, tmp_path, monkeypatch, method, settings, protocol
):
    test_settings_deployment_health_failure_rollback_and_retry(
        admin, tmp_path, monkeypatch, method, {}, settings, changed_protocol=protocol
    )
