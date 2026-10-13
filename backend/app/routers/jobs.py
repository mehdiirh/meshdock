import asyncio
import json
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from .. import force_removals
from ..changes import affected_links
from ..db import audit, connect
from ..i18n import translate
from ..security import AppError, principal, require

router = APIRouter()


def language(request):
    return request.headers.get("accept-language", "en")


@router.get("/jobs")
def jobs(request: Request, actor=Depends(require("read"))):
    with connect() as db:
        rows = db.execute(
            "SELECT id,revision,kind,status,attempt,created,started,finished,error_code,cancel_requested,snapshot,receipt "
            "FROM jobs ORDER BY revision DESC,created DESC,id DESC LIMIT 100"
        ).fetchall()
        applied = json.loads(db.execute("SELECT applied FROM state WHERE id=1").fetchone()[0])
        result = []
        for row in rows:
            job = dict(row)
            if job["kind"] == force_removals.KIND:
                job["force_delete"] = force_removals.report(row)
                for host in job["force_delete"]["hosts"]:
                    host["error_message"] = (
                        translate(host["error_code"], language(request))
                        if host["error_code"]
                        else None
                    )
            job.pop("receipt")
            snapshot = json.loads(job.pop("snapshot"))
            job["link_ids"] = snapshot.get("affected_link_ids")
            if job["link_ids"] is None:
                # Older snapshots predate explicit change attribution.
                job["link_ids"] = affected_links(applied, snapshot)
            job["error_message"] = (
                translate(job["error_code"], language(request)) if job["error_code"] else None
            )
            failure = db.execute(
                "SELECT server_id,code,detail FROM logs WHERE job_id=? AND level='error' ORDER BY id DESC LIMIT 1",
                (job["id"],),
            ).fetchone()
            job["failure"] = dict(failure) if failure else None
            result.append(job)
        return result


@router.post("/jobs/{id}/cancel", status_code=202)
def cancel(id: str, actor=Depends(require("admin"))):
    with connect(True) as db:
        row = db.execute(
            "SELECT kind,status,cancel_requested FROM jobs WHERE id=?", (id,)
        ).fetchone()
        if not row:
            raise AppError("not_found", 404)
        if row["kind"] == force_removals.KIND:
            raise AppError("force_delete_busy", 409)
        if row["status"] == "cancelled" or row["cancel_requested"]:
            return {"job_id": id}
        if row["status"] not in ("queued", "retrying", "running"):
            raise AppError("invalid_state", 409)
        if row["status"] in ("queued", "retrying"):
            db.execute(
                "UPDATE jobs SET cancel_requested=1,status='cancelled',finished=?,error_code='deployment_cancelled' WHERE id=?",
                (time.time(), id),
            )
        else:
            db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (id,))
        audit(db, actor, "deployment_cancel_requested", id)
    return {"job_id": id}


@router.post("/jobs/{id}/recover", status_code=202)
def recover(id: str, actor=Depends(require("admin"))):
    with connect(True) as db:
        force_removals.require_idle(db)
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
                "cancelled",
                "failed",
                "superseded",
                "recovery_required",
                "waiting_cleanup",
            ):
                yield "event: done\ndata: {}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )
