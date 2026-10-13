"""Test Docker startup validation without a daemon, services, or real credentials."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def launcher(tmp_path):
    project = tmp_path / "project with spaces"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(PROJECT / "scripts/start.py", scripts / "start.py")
    records = tmp_path / "commands.jsonl"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(f"#!{sys.executable}\n" """import json
import os
import sys
from pathlib import Path

with Path(os.environ["COMMAND_RECORDS"]).open("a") as output:
    output.write(json.dumps(sys.argv[1:]) + "\\n")
if "config" in sys.argv:
    print(os.environ["COMPOSE_RESULT"])
    if os.environ.get("CONFIG_FAILURE"):
        print("secret-that-must-not-be-printed", file=sys.stderr)
        sys.exit(1)
else:
    sys.exit(int(os.environ.get("UP_EXIT_CODE", "0")))
""")
    docker.chmod(0o755)

    def run(*arguments, password="valid-test-password", config_failure=False, raw=None, up_exit=0):
        configuration = {
            "services": {"api": {"environment": {"MESHDOCK_ADMIN_PASSWORD": password}}}
        }
        result = subprocess.run(
            [sys.executable, str(scripts / "start.py"), *arguments],
            cwd=tmp_path,
            env={
                **os.environ,
                "PATH": str(binaries),
                "COMMAND_RECORDS": str(records),
                "COMPOSE_RESULT": json.dumps(configuration) if raw is None else raw,
                "CONFIG_FAILURE": "yes" if config_failure else "",
                "UP_EXIT_CODE": str(up_exit),
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
        calls = (
            [json.loads(line) for line in records.read_text().splitlines()]
            if records.exists()
            else []
        )
        return result, calls

    return project, run


@pytest.mark.parametrize("password", [None, "", "private-123", "a" * 11])
def test_invalid_password_never_builds_or_starts(launcher, password):
    _, run = launcher
    result, calls = run(password=password)
    assert result.returncode == 2
    assert "at least 12 characters" in result.stderr
    assert "shell variable overrides" in result.stderr
    assert len(calls) == 1 and calls[0][-3:] == ["config", "--format", "json"]
    if password:
        assert password not in result.stdout + result.stderr


@pytest.mark.parametrize("password", ["a" * 12, "رمز" * 4, "space $ # ' secret"])
def test_valid_effective_password_starts_without_exposing_it(launcher, password):
    _, run = launcher
    result, calls = run(password=password)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2
    assert calls[1][:-3] == calls[0][:-3]
    assert calls[1][-3:] == ["up", "-d", "--build"]
    assert password not in result.stdout + result.stderr + json.dumps(calls)


def test_compose_options_are_identical_for_validation_and_start(launcher):
    project, run = launcher
    result, calls = run(
        "-p",
        "meshdock-demo",
        "--env-file",
        "demo env",
        "--env-file",
        "override.env",
        "--profile",
        "tls",
        "--no-build",
    )
    assert result.returncode == 0
    assert calls[1][:-3] == calls[0][:-3]
    assert calls[1][-3:] == ["up", "-d", "--no-build"]
    assert calls[0][1:5] == [
        "--project-directory",
        str(project),
        "-f",
        str(project / "compose.yaml"),
    ]
    assert calls[0][5:-3] == [
        "--project-name",
        "meshdock-demo",
        "--env-file",
        str(project.parent / "demo env"),
        "--env-file",
        str(project.parent / "override.env"),
        "--profile",
        "tls",
    ]


def test_check_only_does_not_start_services(launcher):
    _, run = launcher
    result, calls = run("--check")
    assert result.returncode == 0
    assert len(calls) == 1


def test_configuration_error_does_not_leak_diagnostics(launcher):
    _, run = launcher
    result, calls = run(config_failure=True)
    assert result.returncode == 2
    assert "Could not load Compose configuration" in result.stderr
    assert "secret-that-must-not-be-printed" not in result.stdout + result.stderr
    assert "valid-test-password" not in result.stdout + result.stderr
    assert len(calls) == 1


@pytest.mark.parametrize("raw", ["not JSON", "{}", '{"services": []}', "null"])
def test_unexpected_configuration_cancels_start(launcher, raw):
    _, run = launcher
    result, calls = run(raw=raw)
    assert result.returncode == 2
    assert "Could not read the API configuration" in result.stderr
    assert len(calls) == 1


@pytest.mark.parametrize("argument, code", [("--help", 0), ("--typo", 2)])
def test_help_and_unknown_options_do_not_call_docker(launcher, argument, code):
    _, run = launcher
    result, calls = run(argument)
    assert result.returncode == code
    assert calls == []


def test_docker_start_failure_is_reported(launcher):
    _, run = launcher
    result, _ = run(up_exit=17)
    assert result.returncode == 17
