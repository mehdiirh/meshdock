from fastapi import APIRouter, Depends

from .. import schemas as models
from .. import topology
from ..db import connect
from ..security import AppError, require

router = APIRouter()


def language(request):
    return request.headers.get("accept-language", "en")


@router.get("/topology")
def get_topology(actor=Depends(require("read"))):
    with connect() as db:
        return topology.desired(db)


@router.put("/topology")
def put_topology(body: models.Topology, actor=Depends(require("admin"))):
    with connect(True) as db:
        return topology.save(db, body, actor)


@router.patch("/positions")
def positions(body: models.Positions, actor=Depends(require("write"))):
    with connect(True) as db:
        for id, p in body.positions.items():
            db.execute(
                "UPDATE servers SET position=? WHERE id=? AND deleted=0", (p.model_dump_json(), id)
            )
    return {"ok": True}


@router.get("/methods")
def methods(actor=Depends(require("read"))):
    from ..methods import REGISTRY

    return [m.metadata for m in REGISTRY.values()]


@router.get("/preview")
def preview(actor=Depends(require("read"))):
    from ..planner import build

    with connect() as db:
        snapshot = topology.desired(db, True)
    plans = build(snapshot)
    return [
        {
            "server_id": id,
            "units": list(p["units"]),
            "files": list(p["files"]),
            "ports": p["listeners"],
            "method_count": p["method_count"],
        }
        for id, p in plans.items()
    ]


@router.post("/reconcile", status_code=202)
def reconcile(body: models.Revision, actor=Depends(require("admin"))):
    with connect(True) as db:
        if db.execute("SELECT revision FROM state WHERE id=1").fetchone()[0] != body.revision:
            raise AppError("revision_conflict", 409)
        if db.execute("SELECT 1 FROM jobs WHERE status='recovery_required'").fetchone():
            raise AppError("recovery_required", 409)
        return {"job_id": topology.enqueue(db, actor)}


@router.post("/cleanup", status_code=202)
def cleanup(body: models.Revision, actor=Depends(require("admin"))):
    with connect(True) as db:
        current = topology.desired(db)
        # Disable edges: removes all managed tunnel resources while retaining the inventory.
        for l in current["links"]:
            l["enabled"] = False
        return topology.save(
            db,
            models.Topology(
                revision=body.revision, servers=current["servers"], links=current["links"]
            ),
            actor,
        )
