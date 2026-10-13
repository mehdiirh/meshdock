import os
from pathlib import Path

DATA = Path(os.getenv("MESHDOCK_DATA_DIR", "./.data")).resolve()
DB = DATA / "meshdock.sqlite3"
KEY = Path(os.getenv("MESHDOCK_MASTER_KEY_FILE", str(DATA / "master.key")))
COOKIE_SECURE = os.getenv("MESHDOCK_COOKIE_SECURE", "true").lower() == "true"
ORIGIN = os.getenv("MESHDOCK_PUBLIC_ORIGIN", "http://localhost:8080").rstrip("/")
DEMO = os.getenv("MESHDOCK_DEMO", "false").lower() == "true"
SESSION_HOURS = 12
MAX_ATTEMPTS = 3
LEASE_SECONDS = 600
