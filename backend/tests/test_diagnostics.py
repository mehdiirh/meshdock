import json
from types import SimpleNamespace

import pytest
from app import remote_agent
from app.db import connect
from app.remote_agent import Agent, OperationError
from app.security import AppError
from app.ssh import Remote, progress_event
from app.worker import Worker
from test_topology import seeded


def test_backhaul_exit_installs_only_required_dependencies(tmp_path, monkeypatch):
    commands = []

    def command(args, **kw):
        commands.append(args)
        return SimpleNamespace(stdout=b"install ok installed", returncode=0)

    monkeypatch.setattr(remote_agent, "run", command)
    Agent("a" * 10, root=tmp_path).dependencies(
        {"units": {"transport": "backhaul"}, "files": {"link.toml": "test"}, "binaries": []}, {}
    )
    assert all("haproxy" not in args and "openssh-server" not in args for args in commands)
    assert not any("apt-get" in args for args in commands)


@pytest.mark.parametrize(
    "text,code",
    [
        (b"E: Could not get lock SECRET", "package_lock"),
        (b"Temporary failure resolving SECRET", "package_dns"),
        (b"No space left on device SECRET", "disk_full"),
        (b"404  Not Found SECRET", "package_repository"),
    ],
)
def test_remote_errors_keep_cause_without_raw_output(monkeypatch, text, code):
    monkeypatch.setattr(
        remote_agent.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=100, stdout=b"", stderr=text),
    )
    with pytest.raises(OperationError) as error:
        remote_agent.run(["apt-get", "update"])
    assert str(error.value) == code
    assert error.value.detail == {"command": "apt-get", "exit_code": 100}
    assert "SECRET" not in str(error.value.detail)


def test_progress_events_only_accept_known_fields():
    assert progress_event(
        json.dumps(
            {"event": "binary_verified", "detail": {"binary": "backhaul", "token": "SECRET"}}
        )
    ) == ("binary_verified", {"binary": "backhaul"})
    assert progress_event('{"event":"SECRET","detail":{}}') is None
    assert progress_event("not JSON") is None


def test_worker_persists_live_progress_and_failure_server(admin):
    seeded(admin)

    class ProgressRemote(Remote):
        def __init__(self, server, credential, namespace):
            self.server = server

        def install_agent(self):
            pass

        def close(self):
            pass

        def call(self, action, body):
            if action == "prepare":
                self.on_progress("dependencies_checking", {})
                self.on_progress("packages_installing", {"packages": ["haproxy"]})
                raise AppError("package_dns")
            return {"ok": True}

    worker = Worker(ProgressRemote)
    assert worker.acquire()
    worker.process(worker.claim())
    job = admin.get("/api/v1/jobs").json()[0]
    assert job["failure"]["server_id"]
    assert json.loads(job["failure"]["detail"])["phase"] == "preparing"
    assert "resolve" in job["error_message"]
    events = admin.get(f'/api/v1/jobs/{job["id"]}/logs').json()
    assert any(event["code"] == "packages_installing" for event in events)
    assert any(event["code"] == "dependencies_checking" for event in events)
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM logs WHERE job_id=?", (job["id"],)).fetchone()[
            0
        ] == len(events)


def test_ssh_progress_is_delivered_before_command_finishes():
    chunks = [
        b'{"event":"dependencies_checking","detail":{}}\n',
        b'{"event":"binary_verified","detail":{"binary":"backhaul"}}\n',
        b'{"ok":true}\n',
    ]

    class Channel:
        def settimeout(self, value):
            pass

        def exec_command(self, command):
            pass

        def shutdown_write(self):
            pass

        def recv_ready(self):
            return bool(chunks)

        def recv_stderr_ready(self):
            return False

        def recv(self, size):
            return chunks.pop(0)

        def recv_stderr(self, size):
            return b""

        def exit_status_ready(self):
            return not chunks

        def recv_exit_status(self):
            return 0

        def close(self):
            pass

    remote = Remote.__new__(Remote)
    remote.t = SimpleNamespace(open_session=lambda **kwargs: Channel())
    delivered = []

    def progress(code, detail):
        assert chunks, "Progress must arrive before the final reply"
        delivered.append(code)

    remote.on_progress = progress
    assert json.loads(remote.command("fixture", stream=True)) == {"ok": True}
    assert delivered == ["dependencies_checking", "binary_verified"]
