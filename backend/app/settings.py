import os
from pathlib import Path

DATA = Path(os.getenv("TM_DATA_DIR", "./.data")).resolve()
DB = DATA / "manager.sqlite3"
KEY = Path(os.getenv("TM_MASTER_KEY_FILE", str(DATA / "master.key")))
COOKIE_SECURE = os.getenv("TM_COOKIE_SECURE", "true").lower() == "true"
ORIGIN = os.getenv("TM_PUBLIC_ORIGIN", "http://localhost:8080").rstrip("/")
DEMO = os.getenv("TM_DEMO", "false").lower() == "true"
SESSION_HOURS = 12
MAX_ATTEMPTS = 3
LEASE_SECONDS = 600
