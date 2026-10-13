#!/usr/bin/env python3
"""Validate MeshDock's effective configuration before building or starting Docker services."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-p", "--project-name", help="Compose project name (and data volume namespace)"
    )
    parser.add_argument(
        "--env-file", action="append", default=[], help="Compose environment file; repeatable"
    )
    parser.add_argument(
        "--profile", action="append", default=[], help="Compose profile, e.g. tls; repeatable"
    )
    parser.add_argument(
        "--no-build", action="store_true", help="Start existing images without rebuilding"
    )
    parser.add_argument(
        "--check", action="store_true", help="Validate only; do not build or start containers"
    )
    return parser.parse_args()


def error(message):
    print(f"MeshDock startup cancelled: {message}", file=sys.stderr)
    print("No images were built or containers started by this command.", file=sys.stderr)
    return 2


def main():
    options = arguments()
    compose = [
        "docker",
        "compose",
        "--project-directory",
        str(PROJECT),
        "-f",
        str(PROJECT / "compose.yaml"),
    ]
    if options.project_name:
        compose.extend(["--project-name", options.project_name])
    for env_file in options.env_file:
        compose.extend(["--env-file", str(Path(env_file).resolve())])
    for profile in options.profile:
        compose.extend(["--profile", profile])

    # Compose resolves quoting, interpolation, env files, and shell overrides.
    # Capture its output: the rendered configuration contains credentials.
    try:
        result = subprocess.run(
            [*compose, "config", "--format", "json"],
            cwd=PROJECT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return error("Docker was not found. Install Docker with Compose v2 and try again.")
    except subprocess.TimeoutExpired:
        return error("Docker Compose configuration validation timed out. Try again.")
    if result.returncode:
        # Compose errors may quote interpolated values. Do not expose them.
        return error(
            "Could not load Compose configuration. Check your .env / --env-file and shell variables; "
            "MESHDOCK_ADMIN_PASSWORD must be set to at least 12 characters. "
            "For a fresh checkout, run python3 scripts/setup.py --demo. "
            "Docker Compose v2 is required."
        )
    try:
        config = json.loads(result.stdout)
        password = config["services"]["api"]["environment"].get("MESHDOCK_ADMIN_PASSWORD")
    except (ValueError, KeyError, TypeError, AttributeError):
        return error("Could not read the API configuration returned by Docker Compose.")
    if not isinstance(password, str) or len(password) < 12:
        return error(
            "MESHDOCK_ADMIN_PASSWORD must contain at least 12 characters. "
            "Update .env (or your --env-file). An exported shell variable overrides that file; "
            "update or unset it too."
        )

    print("MeshDock configuration validated.", flush=True)
    if options.check:
        return 0
    command = [*compose, "up", "-d", "--no-build" if options.no_build else "--build"]
    return subprocess.run(command, cwd=PROJECT).returncode


if __name__ == "__main__":
    sys.exit(main())
