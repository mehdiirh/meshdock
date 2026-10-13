import json

import pytest
from app.remote_agent import Agent, OperationError, atomic_json


def test_stale_controller_is_fenced(tmp_path):
    agent = Agent("a" * 10, root=tmp_path)
    agent.accept_fence(9)
    with pytest.raises(OperationError, match="stale_worker"):
        agent.accept_fence(8)
    agent.accept_fence(9)
    agent.accept_fence(10)
    assert json.loads((tmp_path / "fence.json").read_text())["epoch"] == 10


def test_paths_cannot_escape_owned_namespace(tmp_path):
    agent = Agent("a" * 10, root=tmp_path)
    with pytest.raises(OperationError):
        agent.generation("../../etc")
    (tmp_path / "current").symlink_to("/etc")
    with pytest.raises(OperationError):
        agent.current()


def test_rollback_uses_persisted_previous_generation(tmp_path, monkeypatch):
    agent = Agent("a" * 10, root=tmp_path)
    generation = "b" * 32
    previous = "c" * 32
    directory = agent.generation(generation)
    directory.mkdir(parents=True)
    atomic_json(directory / "journal.json", {"previous": previous, "phase": "applying"})
    switched = []
    monkeypatch.setattr(agent, "switch", lambda path: switched.append(path))
    agent.rollback(generation)
    agent.rollback(generation)
    assert switched == [agent.generation(previous)]
    assert json.loads((directory / "journal.json").read_text())["phase"] == "rolled_back"


def test_prepared_but_not_activated_generation_does_not_replace_current(tmp_path, monkeypatch):
    agent = Agent("a" * 10, root=tmp_path)
    generation = "b" * 32
    directory = agent.generation(generation)
    directory.mkdir(parents=True)
    atomic_json(directory / "journal.json", {"previous": None, "phase": "prepared"})
    monkeypatch.setattr(
        agent, "switch", lambda _: pytest.fail("An unapplied generation must not switch services")
    )
    agent.rollback(generation)


def test_orphaned_package_policy_cleanup_preserves_host_policy(tmp_path):
    agent = Agent("a" * 10, root=tmp_path / "owned")
    policy = tmp_path / "policy-rc.d"
    lock = tmp_path / "package.lock"
    policy.write_text("#!/bin/sh\n# Existing host policy\nexit 0\n")
    agent.recover_package_policy(policy, lock)
    assert policy.exists()
    policy.write_text(agent.package_policy_text)
    agent.recover_package_policy(policy, lock)
    assert not policy.exists()
