import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..db import audit, connect
from ..i18n import translate
from ..security import AppError, principal, require

router = APIRouter()


def language(request):
    return request.headers.get("accept-language", "en")


@router.get("/jobs")
def jobs(actor=Depends(require("read"))):
    with connect() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT id,revision,kind,status,attempt,created,started,finished,error_code FROM jobs ORDER BY created DESC LIMIT 100"
            )
        ]


@router.post("/jobs/{id}/recover", status_code=202)
def recover(id: str, actor=Depends(require("admin"))):
    with connect(True) as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (id,)).fetchone()
        if not row:
            raise AppError("not_found", 404)
        if row["status"] != "recovery_required":
            raise AppError("invalid_state", 409)
        db.execute("UPDATE jobs SET status='recovering',next_run=0 WHERE id=?", (id,))
        audit(db, actor, "recovery_requested", id)
    return {"job_id": id}


@router.get("/jobs/{id}/logs")
def logs(
    id: str,
    request: Request,
    after: int = 0,
    lang: str = "",
    actor=Depends(require("read")),
):
    with connect() as db:
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM logs WHERE job_id=? AND id>? ORDER BY id LIMIT 500",
                (id, after),
            )
        ]
    for r in rows:
        r["message"] = translate(r["code"], lang or language(request))
    return rows


@router.get("/jobs/{id}/events")
async def events(
    id: str,
    request: Request,
    after: int = 0,
    lang: str = "",
    actor=Depends(require("read")),
):
    async def stream():
        cursor = after
        while not await request.is_disconnected():
            # Recheck session/key revocation during long-lived streams.
            try:
                principal(request)
            except AppError:
                break
            with connect() as db:
                rows = [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM logs WHERE job_id=? AND id>? ORDER BY id LIMIT 200",
                        (id, cursor),
                    )
                ]
                row = db.execute("SELECT status FROM jobs WHERE id=?", (id,)).fetchone()
            for r in rows:
                cursor = r["id"]
                r["message"] = translate(r["code"], lang or language(request))
                yield "id: " + str(cursor) + "\ndata: " + json.dumps(r) + "\n\n"
            # Drain every persisted page before closing a completed job's stream.
            if len(rows) == 200:
                continue
            if not row or row[0] in (
                "succeeded",
                "failed",
                "superseded",
                "recovery_required",
            ):
                yield "event: done\ndata: {}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )
