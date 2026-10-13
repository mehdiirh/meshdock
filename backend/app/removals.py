"""Expose pending removals without leaking private deployment snapshots."""

import json

from . import schemas
from .db import audit
from .security import AppError


def public_link(link):
    return schemas.Link.model_validate(
        {key: value for key, value in link.items() if key in schemas.Link.model_fields}
    ).model_dump()


def public_server(server):
    return schemas.Server.model_validate(
        {key: value for key, value in server.items() if key in schemas.Server.model_fields}
    ).model_dump()


def removed_links(applied, desired):
    enabled = {link["id"] for link in desired["links"] if link["enabled"]}
    return [
        link for link in applied.get("links", []) if link["enabled"] and link["id"] not in enabled
    ]


def view(db, desired):
    applied = json.loads(db.execute("SELECT applied FROM state WHERE id=1").fetchone()[0])
    links = removed_links(applied, desired)
    if not links:
        return {"pending_removals": [], "removal_servers": []}
    unresolved = db.execute(
        "SELECT status FROM jobs WHERE status IN ('recovery_required','recovering','running') "
        "ORDER BY created DESC LIMIT 1"
    ).fetchone()
    latest = db.execute(
        "SELECT status FROM jobs WHERE revision=? ORDER BY created DESC,id DESC LIMIT 1",
        (desired["revision"],),
    ).fetchone()
    status = (unresolved or latest or {"status": "queued"})["status"]
    if status in ("recovering", "recovery_required"):
        status = "recovery_required"
    elif status == "running":
        status = "removing"
    elif status not in ("failed", "cancelled", "retrying"):
        status = "pending"
    endpoints = {link[key] for link in links for key in ("entry_id", "exit_id")}
    present = {server["id"] for server in desired["servers"]}
    return {
        "pending_removals": [{"link": public_link(link), "status": status} for link in links],
        "removal_servers": [
            public_server(server)
            for server in applied.get("servers", [])
            if server["id"] in endpoints - present
        ],
    }


def resolve(db, link_id, revision, actor, *, restore):
    from . import topology
    from .force_removals import require_idle

    require_idle(db)
    state = db.execute("SELECT * FROM state WHERE id=1").fetchone()
    if state["revision"] != revision:
        raise AppError("revision_conflict", 409)
    if db.execute(
        "SELECT 1 FROM jobs WHERE status IN ('recovery_required','recovering')"
    ).fetchone():
        raise AppError("recovery_required", 409)
    if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','retrying','running')").fetchone():
        raise AppError("removal_busy", 409)
    desired = topology.desired(db)
    applied = json.loads(state["applied"])
    link = next((link for link in removed_links(applied, desired) if link["id"] == link_id), None)
    if link is None:
        raise AppError("not_found", 404)
    if not restore:
        audit(db, actor, "removal_retried", link_id)
        return {"revision": revision, "job_id": topology.enqueue(db, actor)}

    servers = {server["id"]: server for server in desired["servers"]}
    for server in applied["servers"]:
        if server["id"] not in (link["entry_id"], link["exit_id"]):
            continue
        current = servers.get(server["id"])
        if current and any(
            current.get(key) != server.get(key)
            for key in (
                "host",
                "ssh_port",
                "address",
                "credential_id",
                "fingerprint",
                "role",
                "ssh_jump",
            )
        ):
            raise AppError("restore_endpoint_changed", 409)
        servers.setdefault(server["id"], public_server(server))
    body = schemas.Topology(
        revision=revision,
        servers=list(servers.values()),
        links=[item for item in desired["links"] if item["id"] != link_id] + [public_link(link)],
    )
    result = topology.save(db, body, actor)
    audit(db, actor, "removal_restored", link_id)
    return result
