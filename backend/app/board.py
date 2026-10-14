"""Presentation-only inventory placement and SSH management relationships."""

import hashlib
import json

from .db import audit
from .security import AppError

ACTIVE_JOBS = "'queued','running','retrying','recovering','recovery_required','waiting_cleanup'"


def endpoint_key(host, port):
    return host.lower().rstrip("."), port


def relationships(db, desired):
    inventory = desired["servers"]
    locked = set()
    jumps = {}
    aliases = {}
    for server in inventory:
        for host in (server["host"], server["address"]):
            aliases.setdefault(endpoint_key(host, server["ssh_port"]), set()).add(server["id"])

    def include(snapshot, retained=False):
        links = snapshot.get("links", [])
        endpoints = {
            link[key]
            for link in links
            if not retained or link["enabled"]
            for key in ("entry_id", "exit_id")
        }
        locked.update(endpoints)
        for server in snapshot.get("servers", []):
            jump = server.get("ssh_jump")
            if not jump or (retained and server["id"] not in endpoints):
                continue
            key = endpoint_key(jump["host"], jump["ssh_port"])
            matches = aliases.get(key, set())
            locked.update(matches)
            locked.add(server["id"])
            # Ambiguous aliases stay visibly external rather than guessing a server.
            source = next(iter(matches)) if len(matches) == 1 else None
            identity = (source, server["id"], *key)
            if identity in jumps:
                continue
            jumps[identity] = {
                "id": "jump-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24],
                "source_id": source,
                "target_id": server["id"],
                "host": jump["host"],
                "ssh_port": jump["ssh_port"],
                "retained": retained,
            }

    include(desired)
    applied = json.loads(db.execute("SELECT applied FROM state WHERE id=1").fetchone()[0])
    include(applied, retained=True)
    for row in db.execute(f"SELECT snapshot FROM jobs WHERE status IN ({ACTIVE_JOBS})"):
        snapshot = json.loads(row[0])
        include(snapshot, retained=True)
        if forced := snapshot.get("force_delete"):
            locked.add(forced["server_id"])
            include(forced["previous"], retained=True)
            include(forced["desired_before"], retained=True)
    return locked, list(jumps.values())


def view(db, desired):
    locked, jumps = relationships(db, desired)
    present = {server["id"] for server in desired["servers"]}
    hidden = {row[0] for row in db.execute("SELECT server_id FROM board_inventory")}
    return {
        "hidden_server_ids": sorted((hidden & present) - locked),
        "board_locked_server_ids": sorted(locked),
        "jump_connections": jumps,
    }


def reveal_required(db, desired):
    locked, _ = relationships(db, desired)
    db.executemany("DELETE FROM board_inventory WHERE server_id=?", [(id,) for id in locked])


def set_visibility(db, server_id, body, actor):
    from .topology import desired

    current = desired(db)
    if current["revision"] != body.revision:
        raise AppError("revision_conflict", 409)
    if server_id not in {server["id"] for server in current["servers"]}:
        raise AppError("not_found", 404)
    locked, _ = relationships(db, current)
    if body.hidden and server_id in locked:
        raise AppError("board_server_in_use", 409)
    if body.hidden:
        db.execute("INSERT OR IGNORE INTO board_inventory(server_id) VALUES(?)", (server_id,))
    else:
        db.execute("DELETE FROM board_inventory WHERE server_id=?", (server_id,))
    if body.position is not None:
        db.execute(
            "UPDATE servers SET position=? WHERE id=?",
            (body.position.model_dump_json(), server_id),
        )
    audit(db, actor, "board_hidden" if body.hidden else "board_shown", server_id)
    return view(db, current)
