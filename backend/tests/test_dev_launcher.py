"""Exercise the launcher with fake tools; never start services or contact hosts."""

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
    (project / "backend").mkdir()
    (project / "frontend").mkdir()
    for name in ("dev.sh", "setup.py"):
        shutil.copy2(PROJECT / "scripts" / name, scripts / name)

    binaries = tmp_path / "bin"
    binaries.mkdir()
    # The fake frontend waits for both fake background services to record their
    # environments before exiting, so cleanup cannot race these assertions.
    stub = f"#!{sys.executable}\n" + """import json
import os
import sys
import time
from pathlib import Path

records = Path(os.environ["LAUNCHER_RECORDS"])
records.mkdir(exist_ok=True)
arguments = sys.argv[1:]
if Path(sys.argv[0]).name == "npm":
    role = "frontend" if "dev" in arguments else "install"
elif "uvicorn" in arguments:
    role = "api"
elif "app.worker" in arguments:
    role = "worker"
else:
    role = "locales" if "backend/compile_locales.py" in arguments else "sync"
values = {key: os.environ.get(key) for key in (
    "TM_DEMO", "TM_DATA_DIR", "TM_MASTER_KEY_FILE", "TM_PUBLIC_ORIGIN", "TM_COOKIE_SECURE"
)}
(records / (role + ".json")).write_text(json.dumps(values))
if role == "frontend":
    deadline = time.monotonic() + 5
    while not all((records / (name + ".json")).exists() for name in ("api", "worker")):
        if time.monotonic() >= deadline:
            sys.exit("Background services did not launch")
        time.sleep(0.01)
"""
    for name in ("uv", "npm"):
        path = binaries / name
        path.write_text(stub)
        path.chmod(0o755)
    (binaries / "python3").symlink_to(sys.executable)

    environment = os.environ.copy()
    environment.update(
        PATH=f"{binaries}:/usr/bin:/bin",
        LAUNCHER_RECORDS=str(tmp_path / "records"),
        TM_DATA_DIR=str(tmp_path / "must-not-use"),
        TM_MASTER_KEY_FILE=str(tmp_path / "must-not-use.key"),
    )

    def run(*arguments, inherited_demo="false"):
        return subprocess.run(
            ["/bin/sh", str(scripts / "dev.sh"), *arguments],
            cwd=tmp_path,
            env={**environment, "TM_DEMO": inherited_demo},
            capture_output=True,
            text=True,
            timeout=15,
        )

    return project, tmp_path / "records", run


@pytest.mark.parametrize(
    ("arguments", "configured_demo", "inherited_demo", "expected_mode"),
    [
        ([], "false", "false", "demo"),
        ([], "true", "true", "demo"),
        (["--prod"], "true", "true", "prod"),
        (["--prod"], "false", "false", "prod"),
    ],
)
def test_explicit_flag_controls_all_processes(
    launcher, arguments, configured_demo, inherited_demo, expected_mode
):
    project, records, run = launcher
    config = project / ".env"
    original = (
        f"TM_DEMO={configured_demo}\n"
        "TM_DATA_DIR=/must-not-use\n"
        "TM_MASTER_KEY_FILE=/must-not-use.key\n"
    )
    config.write_text(original)
    result = run(*arguments, inherited_demo=inherited_demo)
    assert result.returncode == 0, result.stderr
    assert config.read_text() == original
    assert f"Mode: {expected_mode}" in result.stdout
    assert {path.stem for path in records.iterdir()} == {
        "sync",
        "locales",
        "install",
        "api",
        "worker",
        "frontend",
    }
    for path in records.iterdir():
        assert json.loads(path.read_text()) == {
            "TM_DEMO": "true" if expected_mode == "demo" else "false",
            "TM_DATA_DIR": str(project / ".data" / expected_mode),
            "TM_MASTER_KEY_FILE": str(project / ".data" / expected_mode / "master.key"),
            "TM_PUBLIC_ORIGIN": "http://127.0.0.1:5177",
            "TM_COOKIE_SECURE": "false",
        }


@pytest.mark.parametrize("arguments", [[], ["--prod"]])
def test_fresh_configuration_stays_safe_on_disk(launcher, arguments):
    project, records, run = launcher
    result = run(*arguments)
    assert result.returncode == 0, result.stderr
    config = project / ".env"
    assert "TM_DEMO=true\n" in config.read_text()
    assert config.stat().st_mode & 0o777 == 0o600
    expected_demo = "false" if arguments else "true"
    assert json.loads((records / "worker.json").read_text())["TM_DEMO"] == expected_demo


@pytest.mark.parametrize(
    ("arguments", "expected_code"),
    [(["--help"], 0), (["-h"], 0), (["--real"], 2), (["--prod", "--typo"], 2)],
)
def test_help_and_invalid_arguments_have_no_side_effects(launcher, arguments, expected_code):
    project, records, run = launcher
    result = run(*arguments)
    assert result.returncode == expected_code
    assert "Usage:" in result.stdout + result.stderr
    assert not (project / ".env").exists()
    assert not records.exists()


def test_environment_templates_match_and_default_to_demo():
    sample = (PROJECT / "sample.env").read_text()
    assert sample == (PROJECT / ".env.example").read_text()
    assert "\nTM_DEMO=true\n" in sample
