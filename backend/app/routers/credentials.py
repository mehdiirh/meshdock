import json
import time

from fastapi import APIRouter, Depends

from .. import schemas as models
from .. import settings, ssh
from ..db import audit, connect, uid
from ..security import AppError, require, seal

router = APIRouter()


def language(request):
    return request.headers.get("accept-language", "en")


@router.get("/credentials")
def credentials(actor=Depends(require("admin"))):
    with connect() as db:
        return [
            dict(r)
            for r in db.execute("SELECT id,name,kind,created FROM credentials ORDER BY created")
        ]


@router.post("/credentials", status_code=201)
def credential(body: models.Credential, actor=Depends(require("admin"))):
    if body.kind == "key":
        ssh.private_key(body.secret, body.passphrase)
    id = uid()
    with connect(True) as db:
        db.execute(
            "INSERT INTO credentials VALUES(?,?,?,?,?)",
            (id, body.name, body.kind, seal(body.model_dump()), time.time()),
        )
        audit(db, actor, "credential_created", id)
    return {"id": id, "name": body.name, "kind": body.kind}


@router.delete("/credentials/{id}")
def delete_credential(id: str, actor=Depends(require("admin"))):
    with connect(True) as db:
        refs = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT snapshot FROM jobs WHERE status IN ('running','queued','retrying','recovery_required')"
            )
        ]
        refs.append(json.loads(db.execute("SELECT applied FROM state WHERE id=1").fetchone()[0]))
        if db.execute(
            "SELECT 1 FROM servers WHERE credential_id=? AND deleted=0", (id,)
        ).fetchone() or any(s["credential_id"] == id for r in refs for s in r.get("servers", [])):
            raise AppError("credential_in_use", 409)
        db.execute("DELETE FROM servers WHERE credential_id=? AND deleted=1", (id,))
        db.execute("DELETE FROM credentials WHERE id=?", (id,))
        audit(db, actor, "credential_deleted", id)
    return {"ok": True}


@router.post("/servers/discover")
def discover(body: models.Host, actor=Depends(require("admin"))):
    if settings.DEMO:
        return {"fingerprint": "SHA256:" + "A" * 43, "algorithm": "ssh-ed25519", "simulated": True}
    try:
        return ssh.discover(body.host, body.ssh_port)
    except Exception:
        raise AppError("ssh_unreachable", 502)
