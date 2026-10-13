import copy
import json
from unittest.mock import Mock

import paramiko
import pytest
from alembic import command
from app import settings, ssh, topology
from app.db import connect
from app.migrate import configuration, migrate
from app.security import AppError
from app.worker import Worker, targets
from test_topology import payload, seeded


def jump_config(credential_id="c" * 32):
    return {
        "host": "192.0.2.50",
        "ssh_port": 2222,
        "username": "operator",
        "credential_id": credential_id,
        "fingerprint": "SHA256:" + "J" * 43,
    }


def endpoint(jump=True):
    return {
        "id": "a" * 32,
        "host": "target.internal",
        "ssh_port": 22,
        "fingerprint": "SHA256:" + "T" * 43,
        "ssh_jump": jump_config() if jump else None,
    }


@pytest.fixture
def sessions(monkeypatch):
    jump, target, channel = Mock(), Mock(), Mock()
    jump.get_remote_server_key.return_value = "SHA256:" + "J" * 43
    target.get_remote_server_key.return_value = "SHA256:" + "T" * 43
    jump.open_channel.return_value = channel
    monkeypatch.setattr(ssh, "fingerprint", lambda key: key)
    factory = Mock(side_effect=[jump, target])
    monkeypatch.setattr(ssh, "transport", factory)
    credentials = {
        "kind": "password",
        "secret": "target-password",
        "jump": {"kind": "password", "secret": "jump-password"},
    }
    return jump, target, channel, factory, credentials


def test_jump_opens_pinned_end_to_end_session_and_closes_every_hop(sessions):
    jump, target, channel, factory, credentials = sessions
    remote = ssh.Remote(endpoint(), credentials, "test")
    jump.auth_password.assert_called_once_with("operator", "jump-password")
    target.auth_password.assert_called_once_with("root", "target-password")
    jump.open_channel.assert_called_once_with(
        "direct-tcpip", dest_addr=("target.internal", 22), src_addr=("127.0.0.1", 0), timeout=15
    )
    assert factory.call_args_list[1].args == ("target.internal", 22, channel)
    remote.close()
    remote.close()
    for resource in (jump, target, channel):
        resource.close.assert_called_once()


@pytest.mark.parametrize(
    "hop,code", [("jump", "ssh_jump_host_key_changed"), ("target", "host_key_changed")]
)
def test_wrong_key_never_sends_that_hops_credentials(sessions, hop, code):
    jump, target, channel, factory, credentials = sessions
    bad = jump if hop == "jump" else target
    bad.get_remote_server_key.return_value = "unexpected-key"
    with pytest.raises(AppError) as exc:
        ssh.Remote(endpoint(), credentials, "test")
    assert exc.value.code == code
    assert exc.value.details == {"server_id": "a" * 32}
    bad.auth_password.assert_not_called()
    bad.close.assert_called_once()
    jump.close.assert_called_once()
    if hop == "jump":
        assert factory.call_count == 1
        target.auth_password.assert_not_called()
    else:
        channel.close.assert_called_once()


@pytest.mark.parametrize(
    "failure,code",
    [
        ("unreachable", "ssh_jump_unreachable"),
        ("auth", "ssh_jump_auth"),
        ("forward", "ssh_jump_forward_failed"),
        ("target", "ssh_unreachable"),
        ("target_auth", "ssh_auth"),
    ],
)
def test_jump_failures_are_specific_and_release_resources(sessions, failure, code):
    jump, target, channel, factory, credentials = sessions
    if failure == "unreachable":
        factory.side_effect = OSError("private network detail")
    elif failure == "auth":
        jump.auth_password.side_effect = paramiko.AuthenticationException("secret")
    elif failure == "forward":
        jump.open_channel.side_effect = paramiko.ChannelException(1, "secret")
    elif failure == "target":
        factory.side_effect = [jump, OSError("secret")]
    else:
        target.auth_password.side_effect = paramiko.AuthenticationException("secret")
    with pytest.raises(AppError) as exc:
        ssh.Remote(endpoint(), credentials, "test")
    assert exc.value.code == code and "secret" not in str(exc.value.details)
    if failure != "unreachable":
        jump.close.assert_called_once()
    if failure in ("target", "target_auth"):
        channel.close.assert_called_once()


def test_discovery_uses_jump_but_does_not_authenticate_target(sessions, monkeypatch):
    jump, target, channel, factory, credentials = sessions
    key = Mock()
    key.get_name.return_value = "ssh-ed25519"
    target.get_remote_server_key.return_value = key
    monkeypatch.setattr(ssh, "fingerprint", lambda k: "target-pin" if k is key else k)
    result = ssh.discover("target.internal", 22, jump_config(), credentials["jump"])
    assert result == {"fingerprint": "target-pin", "algorithm": "ssh-ed25519"}
    target.auth_password.assert_not_called()
    jump.auth_password.assert_called_once()
    for resource in (jump, target, channel):
        resource.close.assert_called_once()


def test_direct_connections_remain_direct_and_support_keys(sessions, monkeypatch):
    jump, target, channel, factory, credentials = sessions
    factory.side_effect = [target]
    monkeypatch.setattr(ssh, "private_key", lambda secret, passphrase: "parsed-key")
    remote = ssh.Remote(
        endpoint(False), {"kind": "key", "secret": "pem", "passphrase": "pass"}, "test"
    )
    target.auth_publickey.assert_called_once_with("root", "parsed-key")
    factory.assert_called_once_with("target.internal", 22)
    jump.open_channel.assert_not_called()
    remote.close()


def test_migration_preserves_servers_is_repeatable_and_failure_atomic(admin, monkeypatch):
    from app import migrate as migration_module

    before = seeded(admin)["servers"]
    command.downgrade(configuration(), "92bfc04e31ad")
    upgrade = command.upgrade

    def fail(*args, **kwargs):
        upgrade(*args, **kwargs)
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(migration_module.command, "upgrade", fail)
    with pytest.raises(RuntimeError):
        migrate()
    with connect() as db:
        assert "ssh_jump" not in {r[1] for r in db.execute("PRAGMA table_info(servers)")}
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "92bfc04e31ad"
    monkeypatch.setattr(migration_module.command, "upgrade", upgrade)
    migrate()
    migrate()
    assert admin.get("/api/v1/topology").json()["servers"] == before
    command.check(configuration())


def configure_jump(admin):
    value = seeded(admin)
    credential = admin.post(
        "/api/v1/credentials",
        json={"name": "jump", "kind": "password", "secret": "synthetic-jump-password"},
    ).json()["id"]
    value["servers"][0]["ssh_jump"] = jump_config(credential)
    response = admin.put("/api/v1/topology", json=payload(value))
    assert response.status_code == 200, response.text
    return value, credential, response.json()


def test_jump_persists_but_does_not_change_data_plane_plans(admin):
    value, credential, result = configure_jump(admin)
    exposed = admin.get("/api/v1/topology").json()
    assert exposed["servers"][0]["ssh_jump"] == value["servers"][0]["ssh_jump"]
    assert "synthetic-jump-password" not in json.dumps(exposed)
    assert admin.delete(f"/api/v1/credentials/{credential}").status_code == 409
    with connect() as db:
        after = topology.desired(db, True)
    before = copy.deepcopy(after)
    before["servers"][0].pop("ssh_jump")
    assert targets(before, after) == []
    # Changes of access path alone do not restart tunnel services.


def test_discover_jump_validates_credentials_and_preserves_errors(admin, monkeypatch):
    value, credential, result = configure_jump(admin)
    monkeypatch.setattr(settings, "DEMO", False)
    discover = Mock(side_effect=AppError("ssh_jump_forward_failed", 502))
    monkeypatch.setattr(ssh, "discover", discover)
    jump = value["servers"][0]["ssh_jump"]
    response = admin.post(
        "/api/v1/servers/discover", json={"host": "target.internal", "ssh_jump": jump}
    )
    assert response.status_code == 502 and response.json()["code"] == "ssh_jump_forward_failed"
    assert discover.call_args.args[3]["secret"] == "synthetic-jump-password"
    jump["credential_id"] = "f" * 32
    response = admin.post(
        "/api/v1/servers/discover", json={"host": "target.internal", "ssh_jump": jump}
    )
    assert response.status_code == 404
    assert discover.call_count == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"host": "bad; command"},
        {"ssh_port": 0},
        {"username": "root;id"},
        {"fingerprint": "unknown"},
        {"ssh_jump": {}},
    ],
)
def test_jump_options_reject_invalid_or_nested_hops(admin, patch):
    jump = {**jump_config(), **patch}
    response = admin.post(
        "/api/v1/servers/discover", json={"host": "target.internal", "ssh_jump": jump}
    )
    assert response.status_code == 422


def test_jump_cannot_point_at_target_or_missing_credential(admin):
    value = seeded(admin)
    server = value["servers"][0]
    server["ssh_jump"] = {**jump_config(), "host": server["host"], "ssh_port": server["ssh_port"]}
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 422
    server["ssh_jump"] = jump_config()
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 404


def test_worker_uses_jump_for_apply_rollback_and_old_endpoint_cleanup(admin, monkeypatch):
    value, credential, result = configure_jump(admin)
    old_host = value["servers"][0]["host"]
    calls = []
    failure = False

    class Recording:
        def __init__(self, server, secrets, namespace):
            self.server = server
            if server.get("ssh_jump"):
                assert secrets["jump"]["secret"] == "synthetic-jump-password"
            self.jump = server.get("ssh_jump")

        def install_agent(self):
            pass

        def close(self):
            pass

        def call(self, action, payload):
            calls.append((self.server["host"], action, self.jump))
            if failure and action == "apply":
                raise AppError("remote_failed")
            return {"ok": True}

    worker = Worker(Recording)
    assert worker.acquire()
    worker.process(worker.claim())
    value = admin.get("/api/v1/topology").json()
    value["servers"][0].update(host="192.0.2.199", address="192.0.2.199", ssh_jump=None)
    assert admin.put("/api/v1/topology", json=payload(value)).status_code == 200
    failure = True
    worker.process(worker.claim())
    assert any(host == old_host and action == "rollback" and jump for host, action, jump in calls)
    assert any(
        host == "192.0.2.199" and action == "prepare" and jump is None
        for host, action, jump in calls
    )
    # Applied snapshots protect jump credentials even after the new desired path stops using them.
    assert admin.delete(f"/api/v1/credentials/{credential}").status_code == 409
    with connect() as db:
        snapshot = json.loads(
            db.execute("SELECT snapshot FROM jobs WHERE id=?", (result["job_id"],)).fetchone()[0]
        )
    assert "synthetic-jump-password" not in json.dumps(snapshot)


def test_close_releases_other_hops_when_one_resource_raises(sessions):
    jump, target, channel, factory, credentials = sessions
    connection = ssh.SSHConnection(endpoint(), credentials)
    target.close.side_effect = OSError("already disconnected")
    connection.close()
    connection.close()
    for resource in (target, channel, jump):
        resource.close.assert_called_once()
    assert connection.target is connection.channel is connection.jump is None
