import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from . import settings


@contextmanager
def connect(write=False):
    settings.DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(settings.DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    try:
        if write:
            db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    from .migrate import migrate

    migrate()
    with connect(True) as db:
        db.execute(
            "INSERT OR IGNORE INTO state VALUES(1,?,0,0,?)",
            (uuid.uuid4().hex[:10], json.dumps({"servers": [], "links": []})),
        )


def uid():
    return uuid.uuid4().hex


def audit(db, actor, action, detail=""):
    db.execute(
        "INSERT INTO audit(actor,action,detail,created) VALUES(?,?,?,?)",
        (actor, action, detail, time.time()),
    )


def log(job, code, detail="", server=None, level="info"):
    with connect(True) as db:
        db.execute(
            "INSERT INTO logs(job_id,server_id,level,code,detail,created) VALUES(?,?,?,?,?,?)",
            (job, server, level, code, detail[:4000], time.time()),
        )
