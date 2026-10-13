import json
import time

from fastapi import APIRouter, Depends

from .. import schemas as models
from .. import settings, ssh
from ..db import audit, connect, uid
from ..force_removals import retained_snapshots
from ..security import AppError, require, seal
from ..ssh_access import credential, credential_ids

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
def create_credential(body: models.Credential, actor=Depends(require("admin"))):
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
                "SELECT snapshot FROM jobs WHERE status IN ('running','queued','retrying','recovering','recovery_required')"
            )
        ]
        refs.extend(retained_snapshots(db))
        refs.append(json.loads(db.execute("SELECT applied FROM state WHERE id=1").fetchone()[0]))
        active = [dict(row) for row in db.execute("SELECT * FROM servers WHERE deleted=0")]
        referenced = active + [
            server for snapshot in refs for server in snapshot.get("servers", [])
        ]
        if any(id in credential_ids(server) for server in referenced):
            raise AppError("credential_in_use", 409)
        db.execute("DELETE FROM servers WHERE credential_id=? AND deleted=1", (id,))
        db.execute("DELETE FROM credentials WHERE id=?", (id,))
        audit(db, actor, "credential_deleted", id)
    return {"ok": True}


@router.post("/servers/discover")
def discover(body: models.AccessHost, actor=Depends(require("admin"))):
    jump = body.ssh_jump.model_dump() if body.ssh_jump else None
    with connect() as db:
        jump_credential = credential(db, jump["credential_id"]) if jump else None
    if settings.DEMO:
        return {
            "fingerprint": "SHA256:" + "A" * 43,
            "algorithm": "ssh-ed25519",
            "simulated": True,
        }
    try:
        return ssh.discover(body.host, body.ssh_port, jump, jump_credential)
    except AppError:
        raise
    except Exception:
        raise AppError("ssh_unreachable", 502) from None
