import hashlib
import json
import os
import re
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet
from fastapi import Request

from . import settings
from .db import connect, uid

hasher = PasswordHasher()
DUMMY = hasher.hash(secrets.token_hex(20))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def cipher():
    settings.KEY.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not settings.KEY.exists():
        import tempfile

        fd, name = tempfile.mkstemp(dir=settings.KEY.parent, prefix=".key-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(name, settings.KEY)
            except FileExistsError:
                pass
        finally:
            os.unlink(name)
    return Fernet(settings.KEY.read_bytes().strip())


def seal(value):
    return cipher().encrypt(json.dumps(value).encode()).decode()


def unseal(value):
    return json.loads(cipher().decrypt(value.encode()))


def verify(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def bootstrap():
    cipher()
    with connect(True) as db:
        if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            password = os.getenv("TM_ADMIN_PASSWORD", "")
            path = os.getenv("TM_ADMIN_PASSWORD_FILE")
            if path:
                password = open(path).read().strip()
            if len(password) < 12:
                raise RuntimeError(
                    "Set TM_ADMIN_PASSWORD or TM_ADMIN_PASSWORD_FILE (minimum 12 characters) for first startup."
                )
            db.execute(
                "INSERT INTO users VALUES(?,?,?,?)",
                (
                    uid(),
                    os.getenv("TM_ADMIN_USERNAME", "admin"),
                    hasher.hash(password),
                    time.time(),
                ),
            )


class AppError(Exception):
    def __init__(self, code, status=400, details=None):
        self.code = code
        self.status = status
        self.details = details


def principal(request: Request, required="read"):
    rank = {"read": 0, "write": 1, "admin": 2}
    auth = request.headers.get("authorization", "")
    with connect(True) as db:
        if auth.startswith("Bearer "):
            key = db.execute(
                "SELECT * FROM api_keys WHERE token_hash=? AND revoked=0", (digest(auth[7:]),)
            ).fetchone()
            if not key:
                raise AppError("unauthorized", 401)
            if rank.get(key["scope"], -1) < rank[required]:
                raise AppError("forbidden", 403)
            db.execute("UPDATE api_keys SET last_used=? WHERE id=?", (time.time(), key["id"]))
            return "key:" + key["id"]
        token = request.cookies.get("tm_session", "")
        session = db.execute(
            "SELECT * FROM sessions WHERE token_hash=? AND expires>?", (digest(token), time.time())
        ).fetchone()
        if not session:
            raise AppError("unauthorized", 401)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session["csrf"]):
                raise AppError("csrf", 403)
            if request.headers.get("origin") and request.headers["origin"] != settings.ORIGIN:
                raise AppError("csrf", 403)
        return "user:" + session["user_id"]


def require(scope):
    def dependency(request: Request):
        return principal(request, scope)

    return dependency


def redact(text, sensitive=()):
    text = str(text)
    for s in sorted((str(s) for s in sensitive if s), key=len, reverse=True):
        text = text.replace(s, "[REDACTED]")
    text = re.sub(
        r"-----BEGIN [\s\S]*?PRIVATE KEY-----[\s\S]*?-----END [\s\S]*?PRIVATE KEY-----",
        "[REDACTED KEY]",
        text,
    )
    text = re.sub(
        r"(?i)(password|token|secret|authorization)(\s*[:=]\s*)[^\s,;]+", r"\1\2[REDACTED]", text
    )
    return text[:4000]
