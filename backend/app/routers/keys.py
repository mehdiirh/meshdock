import secrets
import time

from fastapi import APIRouter, Depends

from .. import schemas as models
from ..db import audit, connect, uid
from ..security import digest, require

router = APIRouter()


def language(request):
    return request.headers.get("accept-language", "en")


@router.get("/keys")
def keys(actor=Depends(require("admin"))):
    with connect() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT id,name,prefix,scope,created,last_used,revoked FROM api_keys ORDER BY created DESC"
            )
        ]


@router.post("/keys", status_code=201)
def key(body: models.ApiKey, actor=Depends(require("admin"))):
    token = "meshdock_" + secrets.token_urlsafe(40)
    id = uid()
    with connect(True) as db:
        db.execute(
            "INSERT INTO api_keys(id,name,prefix,token_hash,scope,created) VALUES(?,?,?,?,?,?)",
            (id, body.name, token[:16], digest(token), body.scope, time.time()),
        )
        audit(db, actor, "key_created", id)
    return {"id": id, "token": token}


@router.delete("/keys/{id}")
def revoke(id: str, actor=Depends(require("admin"))):
    with connect(True) as db:
        db.execute("UPDATE api_keys SET revoked=1 WHERE id=?", (id,))
        audit(db, actor, "key_revoked", id)
    return {"ok": True}


@router.get("/audit")
def audit_list(actor=Depends(require("admin"))):
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200")]
