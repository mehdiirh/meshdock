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


HEALTH_CASES = [
    {"check": "service", "unit": "meshdock-aaaaaaaaaa-router.service"},
    {"check": "gre_peer", "interface": "mdaaaaaa3", "peer": "10.253.0.13"},
    {"check": "firewall", "table": "nat", "parent": "INPUT", "chain": "MESHDOCK_AAAAAAAAAA_IN"},
    {"check": "listener", "protocol": "udp", "address": "10.253.0.14", "port": 7334, "missing": 2},
    {"check": "listener_scan", "protocol": "tcp"},
    {"check": "connection", "address": "127.0.0.1", "port": 8443},
]


@pytest.mark.parametrize("detail", HEALTH_CASES)
def test_health_details_cross_ssh_boundary_without_raw_output(detail):
    from app.diagnostics import report

    remote = Remote.__new__(Remote)
    remote.ns = "a" * 10
    remote.server = {"id": "b" * 32}
    remote.command = lambda *a, **kw: json.dumps(
        {
            "ok": False,
            "code": "health_failed",
            "detail": {**detail, "stderr": "SECRET", "token": "SECRET"},
        }
    )
    with pytest.raises(AppError) as error:
        remote.call("health", {"generation": "c" * 32})
    assert error.value.code == "health_failed"
    assert error.value.details == {**detail, "server_id": "b" * 32}
    for language in ("en", "fa"):
        result = report(error.value.code, json.dumps(error.value.details), language)
        assert result["hint"]
        assert "{" not in result["message"]
        assert "SECRET" not in str(result)
        assert not result["message"].startswith("health_")
    assert report("health_failed", detail, "en") != report("health_failed", detail, "fa")


@pytest.mark.parametrize(
    "detail",
    [
        None,
        [],
        "SECRET",
        {"check": "gre_peer", "peer": "SECRET"},
        {"check": "service", "unit": "xray-SECRET.service"},
        {"check": "listener", "port": True},
        {"check": "firewall", "chain": "SECRET"},
    ],
)
def test_malformed_or_unknown_health_details_are_not_reported(detail):
    from app.diagnostics import health_details, report

    assert health_details(detail) == {}
    result = report("health_failed", detail)
    assert "SECRET" not in str(result)
    assert "did not record" in result["hint"]


@pytest.mark.parametrize(
    "check", ["service", "gre_peer", "firewall", "listener", "listener_scan", "connection"]
)
def test_agent_identifies_each_failed_health_check(tmp_path, monkeypatch, check):
    agent = Agent("a" * 10, root=tmp_path)
    plan = {"units": {}, "checks": [], "sockets": []}
    if check == "service":
        plan["units"] = {"meshdock-aaaaaaaaaa-router.service": ""}
    elif check == "gre_peer":
        plan["gre_checks"] = [{"interface": "mdaaaaaa3", "peer": "10.253.0.13"}]
    elif check == "firewall":
        plan.update(network_interfaces=["mdaaaaaa3"], network_rules={"input": [["test"]]})
    elif check in ("listener", "listener_scan"):
        plan["sockets"] = [
            {"address": "10.253.0.14", "port": p, "protocol": "udp"} for p in (7334, 7335)
        ]
    else:
        plan["checks"] = [{"host": "127.0.0.1", "port": 8443}]

        def refused(*args, **kwargs):
            raise OSError("SECRET")

        monkeypatch.setattr(remote_agent.socket, "create_connection", refused)
    monkeypatch.setattr(agent, "manifest", lambda _: plan)
    monkeypatch.setattr(
        remote_agent,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout=b"invalid" if check == "listener_scan" else b""
        ),
    )
    with pytest.raises(OperationError) as failure:
        agent.health("b" * 32)
    assert str(failure.value) == "health_failed"
    assert failure.value.detail["check"] == check
    if check == "listener":
        assert failure.value.detail["missing"] == 2
        assert failure.value.detail["port"] == 7334


@pytest.mark.parametrize("persistent", [False, True])
def test_health_retries_stream_diagnostics_and_keep_rollback_semantics(
    admin, monkeypatch, persistent
):
    from app import worker as worker_module
    from app.worker import DemoRemote

    seeded(admin)
    monkeypatch.setattr(worker_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(worker_module.settings, "MAX_ATTEMPTS", 1)
    calls = []
    probes = 0
    detail = {"check": "gre_peer", "interface": "mdaaaaaa3", "peer": "10.253.0.13"}

    class HealthRemote(DemoRemote):
        def call(self, action, payload):
            nonlocal probes
            calls.append(action)
            if action == "health":
                probes += 1
                if persistent or probes <= 2:
                    raise AppError("health_failed", details=detail)
            return {"ok": True}

    worker = Worker(HealthRemote)
    assert worker.acquire()
    worker.process(worker.claim())
    job = admin.get("/api/v1/jobs").json()[0]
    assert job["status"] == ("failed" if persistent else "succeeded")
    assert ("rollback" in calls) == persistent
    logs = admin.get(f'/api/v1/jobs/{job["id"]}/logs').json()
    retries = [row for row in logs if row["code"] == "health_retry"]
    assert len(retries) == (11 if persistent else 2)
    assert "1/12" in retries[0]["message"]
    assert "10.253.0.13" in retries[0]["message"]
    assert "protocol 47" in retries[0]["hint"]
    stream = admin.get(f'/api/v1/jobs/{job["id"]}/events').text
    assert "10.253.0.13" in stream and "event: done" in stream
    if persistent:
        assert "GRE peer" in job["error_message"]
        assert "protocol 47" in job["error_hint"]
        assert json.loads(job["failure"]["detail"])["phase"] == "checking"
        persian = admin.get("/api/v1/jobs", headers={"accept-language": "fa"}).json()[0]
        assert "پاسخ نداد" in persian["error_message"]
        assert "10.253.0.13" in persian["error_message"]
        assert admin.get("/api/v1/topology").json()["applied_revision"] == 0
    else:
        assert job["error_hint"] is None
        assert job["error_message"] is None
