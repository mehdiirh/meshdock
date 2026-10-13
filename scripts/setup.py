#!/usr/bin/env python3
"""Generate MeshDock local configuration without overwriting existing secrets."""

import argparse
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlparse

parser = argparse.ArgumentParser(description="Generate MeshDock configuration.")
parser.add_argument("--origin", default="http://localhost:8080")
parser.add_argument("--demo", action="store_true")
arguments = parser.parse_args()
origin = urlparse(arguments.origin)
if (
    origin.scheme not in ("http", "https")
    or not origin.hostname
    or origin.path not in ("", "/")
    or origin.username is not None
    or origin.password is not None
    or origin.query
    or origin.fragment
    or not re.fullmatch(r"https?://[A-Za-z0-9.-]+(?::[0-9]{1,5})?/?", arguments.origin)
):
    parser.error("Use an HTTP(S) origin without a path.")
if origin.port is not None and not 1 <= origin.port <= 65535:
    parser.error("Use a valid port between 1 and 65535.")
if origin.scheme == "http" and origin.hostname not in ("localhost", "127.0.0.1"):
    parser.error("Use HTTPS for a remotely accessible deployment.")
project = Path(__file__).resolve().parents[1]
password = secrets.token_urlsafe(24)
content = "\n".join(
    [
        "TM_ADMIN_USERNAME=admin",
        "TM_ADMIN_PASSWORD=" + password,
        "TM_PUBLIC_ORIGIN=" + arguments.origin.rstrip("/"),
        "TM_DOMAIN=" + origin.hostname,
        "TM_COOKIE_SECURE=" + str(origin.scheme == "https").lower(),
        "TM_DEMO=" + str(arguments.demo).lower(),
        "TM_PORT=8080",
        "",
    ]
)
try:
    fd = os.open(project / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    parser.exit("Configuration already exists; refusing to overwrite .env.\n")
with os.fdopen(fd, "w") as output:
    output.write(content)
print("Created MeshDock .env (owner-only). Read TM_ADMIN_PASSWORD there to sign in as admin.")
