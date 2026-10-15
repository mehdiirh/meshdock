import copy
import json
from types import SimpleNamespace

import pytest
from app import topology
from app.changes import affected_links
from app.db import connect
from app.planner import build
from app.remote_agent import Agent, atomic_json
from app.worker import targets
from test_topology import seeded


def test_adding_link_skips_unchanged_exit_and_attributes_only_new_link(admin):
    seeded(admin)
    with connect() as db:
        desired = topology.desired(db, True)
    desired["links"] = desired["links"][:2]
    desired["links"][1]["ports"][0]["public"] = 9443
    desired["links"][0]["method"] = "gre"
    desired["links"][1].update(method="backhaul", settings={"transport": "wss"})
    previous = copy.deepcopy(desired)
    previous["links"] = previous["links"][:1]
    changed = targets(previous, desired)
    assert {target.server["id"] for target in changed} == {
        desired["links"][1]["entry_id"],
        desired["links"][1]["exit_id"],
    }
    assert affected_links(previous, desired) == [desired["links"][1]["id"]]
    assert targets(desired, desired) == []


@pytest.mark.parametrize("native", [False, True])
def test_shared_entry_preserves_unchanged_gre_during_apply_and_rollback(
    admin, tmp_path, monkeypatch, native
):
    seeded(admin)
    with connect() as db:
        new = topology.desired(db, True)
    new["links"] = new["links"][:2]
    new["links"][1]["ports"][0]["public"] = 9443
    new["links"][0]["method"] = "gre"
    if native:
        new["links"][0]["ports"] = [
            {"public": "1148-1149", "target": "1148-1149", "host": "127.0.0.1"}
        ]
    new["links"][1].update(method="backhaul", settings={"transport": "wss"})
    old = copy.deepcopy(new)
    old["links"] = old["links"][:1]
    server = old["links"][0]["entry_id"]
    plans = [build(snapshot)[server] for snapshot in (old, new)]
    agent = Agent(new["namespace"], root=tmp_path / "agent")
    agent.units = tmp_path / "units"
    agent.units.mkdir()
    commands = []
    monkeypatch.setattr(
        "app.remote_agent.run",
        lambda args, **kw: commands.append(args) or SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr("app.remote_agent.shutil.which", lambda _: True)
    monkeypatch.setattr(agent, "network_down", lambda: commands.append(["network_down"]))
    monkeypatch.setattr(agent, "firewall", lambda _: None)
    generations = []
    for index, plan in enumerate(plans):
        # Match actual owned paths for recursive unit dependency comparison.
        production = f'/var/lib/meshdock/{new["namespace"]}'
        plan = json.loads(json.dumps(plan).replace(production, str(agent.root)))
        directory = agent.generation(str(index + 1) * 32)
        directory.mkdir(parents=True)
        atomic_json(directory / "manifest.json", plan)
        generations.append(directory)
    agent.switch(generations[0])
    commands.clear()
    agent.switch(generations[1])
    assert not any(
        "-gre.service" in str(cmd) or "-network.service" in str(cmd) or cmd == ["network_down"]
        for cmd in commands
    )
    assert any("-router.service" in str(cmd) for cmd in commands)
    commands.clear()
    agent.switch(generations[0])
    assert not any(
        "-gre.service" in str(cmd) or "-network.service" in str(cmd) or cmd == ["network_down"]
        for cmd in commands
    )

    if native:
        updated = agent.manifest(generations[0])
        script = next(name for name in updated["files"] if name.endswith("-gre.sh"))
        updated["files"][script] = updated["files"][script].replace("mtu 1400", "mtu 1300")
        third = agent.generation("3" * 32)
        third.mkdir()
        atomic_json(third / "manifest.json", updated)
        commands.clear()
        agent.switch(third)
        assert ["network_down"] not in commands
        assert any(
            cmd[:2] == ["systemctl", "start"] and cmd[-1].endswith("-router.service")
            for cmd in commands
        )


def test_unit_signature_tracks_referenced_tls_material(tmp_path):
    agent = Agent("a" * 10, root=tmp_path)
    root = str(tmp_path / "current")
    plan = {
        "units": {"test": f"ExecStart=haproxy -f {root}/haproxy.cfg"},
        "files": {"haproxy.cfg": f"bind :443 ssl crt {root}/tls.pem", "tls.pem": "old"},
    }
    new = copy.deepcopy(plan)
    new["files"]["tls.pem"] = "new"
    assert agent.unit_signature(plan, "test") != agent.unit_signature(new, "test")
