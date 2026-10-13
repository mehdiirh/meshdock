import secrets
import time

from fastapi import APIRouter, Depends, Request, Response

from .. import schemas as models
from .. import settings
from ..db import audit, connect
from ..security import DUMMY, AppError, digest, hasher, require, verify

router = APIRouter()


def language(request):
    return request.headers.get("accept-language", "en")


@router.post("/auth/login")
def login(body: models.Login, request: Request, response: Response):
    if request.headers.get("origin") and request.headers["origin"] != settings.ORIGIN:
        raise AppError("csrf", 403)
    # Both username and connection address have limits. Never trust a client-supplied forwarding header.
    buckets = [
        "user:" + digest(body.username.lower()),
        "ip:" + digest(request.client.host if request.client else "unknown"),
    ]
    with connect(True) as db:
        for bucket in buckets:
            row = db.execute("SELECT * FROM login_attempts WHERE bucket=?", (bucket,)).fetchone()
            if row and row["until"] > time.time() and row["count"] >= 10:
                raise AppError("rate_limit", 429)
        user = db.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
        ok = verify(user["password_hash"] if user else DUMMY, body.password)
        if not ok:
            for bucket in buckets:
                db.execute(
                    """INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=CASE WHEN until<? THEN 1 ELSE count+1 END,until=CASE WHEN until<? THEN excluded.until ELSE until END""",
                    (bucket, time.time() + 300, time.time(), time.time()),
                )
        else:
            for bucket in buckets:
                db.execute("DELETE FROM login_attempts WHERE bucket=?", (bucket,))
            token = secrets.token_urlsafe(40)
            csrf = secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?,?)",
                (
                    digest(token),
                    user["id"],
                    csrf,
                    time.time() + settings.SESSION_HOURS * 3600,
                ),
            )
            audit(db, "user:" + user["id"], "login")
    if not ok:
        raise AppError("invalid_login", 401)
    response.set_cookie(
        "tm_session",
        token,
        max_age=settings.SESSION_HOURS * 3600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="strict",
        path="/api",
    )
    return {"username": user["username"], "csrf": csrf, "demo": settings.DEMO}


@router.get("/auth/me")
def me(request: Request, actor=Depends(require("read"))):
    with connect() as db:
        if actor.startswith("user:"):
            row = db.execute("SELECT username FROM users WHERE id=?", (actor[5:],)).fetchone()
            session = db.execute(
                "SELECT csrf FROM sessions WHERE token_hash=?",
                (digest(request.cookies.get("tm_session", "")),),
            ).fetchone()
            return {
                "username": row["username"],
                "csrf": session["csrf"],
                "demo": settings.DEMO,
            }
    return {"username": "API", "csrf": "", "demo": settings.DEMO}


@router.post("/auth/logout")
def logout(request: Request, response: Response, actor=Depends(require("read"))):
    with connect(True) as db:
        db.execute(
            "DELETE FROM sessions WHERE token_hash=?",
            (digest(request.cookies.get("tm_session", "")),),
        )
    response.delete_cookie("tm_session", path="/api")
    return {"ok": True}


@router.post("/auth/password")
def password(body: models.Password, actor=Depends(require("admin"))):
    if not actor.startswith("user:"):
        raise AppError("forbidden", 403)
    with connect(True) as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (actor[5:],)).fetchone()
        if not verify(user["password_hash"], body.current):
            raise AppError("invalid_login", 401)
        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (hasher.hash(body.password), user["id"]),
        )
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        audit(db, actor, "password_changed")
    return {"ok": True}
