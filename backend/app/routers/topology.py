from fastapi import APIRouter, Depends

from .. import force_removals, removals, topology
from .. import schemas as models
from ..db import connect
from ..security import AppError, require

router = APIRouter()


def language(request):
    return request.headers.get("accept-language", "en")


@router.get("/topology")
def get_topology(actor=Depends(require("read"))):
    with connect() as db:
        desired = topology.desired(db)
        return {**desired, **removals.view(db, desired)}


@router.put("/topology")
def put_topology(body: models.Topology, actor=Depends(require("admin"))):
    with connect(True) as db:
        return topology.save(db, body, actor)


@router.patch("/positions")
def positions(body: models.Positions, actor=Depends(require("write"))):
    with connect(True) as db:
        for id, p in body.positions.items():
            db.execute(
                "UPDATE servers SET position=? WHERE id=? AND deleted=0",
                (p.model_dump_json(), id),
            )
    return {"ok": True}


@router.get("/methods")
def methods(actor=Depends(require("read"))):
    from ..methods import REGISTRY

    return [
        {
            **m.metadata,
            "control_protocol": m.control_protocol,
            "mapping": m.mapping_capabilities,
            "settings_schema": m.options_model.schema(),
            "transports": m.transports,
        }
        for m in REGISTRY.values()
    ]


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
            "udp_ports": p["udp_listeners"],
            "method_count": p["method_count"],
            "forwarded_ranges": p["forwarded_ranges"],
            "resources": p["resources"],
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
        for link in current["links"]:
            link["enabled"] = False
        return topology.save(
            db,
            models.Topology(
                revision=body.revision,
                servers=current["servers"],
                links=current["links"],
            ),
            actor,
        )


@router.post("/links/{id}/retry-removal", status_code=202)
def retry_removal(id: str, body: models.Revision, actor=Depends(require("admin"))):
    with connect(True) as db:
        return removals.resolve(db, id, body.revision, actor, restore=False)


@router.post("/links/{id}/restore", status_code=202)
def restore_removal(id: str, body: models.Revision, actor=Depends(require("admin"))):
    with connect(True) as db:
        return removals.resolve(db, id, body.revision, actor, restore=True)


@router.post("/servers/{id}/force-delete", status_code=202)
def force_delete_server(id: str, body: models.Revision, actor=Depends(require("admin"))):
    with connect(True) as db:
        return force_removals.start(db, id, body.revision, actor)


@router.post("/jobs/{id}/retry-cleanup", status_code=202)
def retry_force_cleanup(id: str, body: models.Revision, actor=Depends(require("admin"))):
    with connect(True) as db:
        return force_removals.resume(db, id, body.revision, actor)


@router.post("/jobs/{id}/skip-cleanup", status_code=202)
def skip_force_cleanup(id: str, body: models.Revision, actor=Depends(require("admin"))):
    with connect(True) as db:
        return force_removals.resume(db, id, body.revision, actor, skip=True)
