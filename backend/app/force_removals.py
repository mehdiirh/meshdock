"""Durable per-endpoint cleanup before forgetting an unreachable server."""

import copy
import json
import time

from . import settings, topology
from .changes import affected_links
from .db import audit, connect, log, uid
from .planner import build, empty
from .security import AppError

KIND = "force_delete"
PENDING = ("queued", "running", "retrying", "recovering", "waiting_cleanup")
NETWORK_ERRORS = {"ssh_unreachable", "ssh_jump_unreachable", "ssh_jump_forward_failed"}


def active(db):
    return db.execute(
        "SELECT id FROM jobs WHERE kind=? AND status IN (?,?,?,?,?) LIMIT 1", (KIND, *PENDING)
    ).fetchone()


def require_idle(db):
    if active(db):
        raise AppError("force_delete_busy", 409)


def without_server(snapshot, server_id):
    result = copy.deepcopy(snapshot)
    result["servers"] = [s for s in result["servers"] if s["id"] != server_id]
    result["links"] = [
        link for link in result["links"] if server_id not in (link["entry_id"], link["exit_id"])
    ]
    return result


def retained_snapshots(db):
    """Protect credentials and slots for pending cleanup and acknowledged orphans."""
    result = []
    for row in db.execute("SELECT status,snapshot,receipt FROM jobs WHERE kind=?", (KIND,)):
        receipt = json.loads(row["receipt"])
        if row["status"] in PENDING or any(
            host.get("status") == "skipped" for host in receipt.get("hosts", [])
        ):
            metadata = json.loads(row["snapshot"])["force_delete"]
            result.extend((metadata["previous"], metadata["desired_before"]))
    return result


def start(db, server_id, revision, actor):
    require_idle(db)
    state = db.execute("SELECT * FROM state WHERE id=1").fetchone()
    if state["revision"] != revision:
        raise AppError("revision_conflict", 409)
    if db.execute(
        "SELECT 1 FROM jobs WHERE status IN ('queued','retrying','running','recovering')"
    ).fetchone():
        raise AppError("removal_busy", 409)
    desired = topology.desired(db, True)
    previous = json.loads(state["applied"])
    previous.setdefault("namespace", state["namespace"])
    servers = {s["id"]: s for s in previous["servers"] + desired["servers"]}
    if server_id not in servers:
        raise AppError("not_found", 404)
    incident = {
        link["id"]
        for link in previous["links"] + desired["links"]
        if server_id in (link["entry_id"], link["exit_id"])
    }
    recovery = list(db.execute("SELECT * FROM jobs WHERE status='recovery_required'"))
    for job in recovery:
        failed = json.loads(job["snapshot"])
        before_links = {link["id"]: link for link in previous["links"]}
        before_servers = {server["id"]: server for server in previous["servers"]}
        # Take over only a failed removal of this server's links, never unrelated mutations.
        if (
            job["kind"] == KIND
            or not set(affected_links(previous, failed)).issubset(incident)
            or any(
                link["id"] not in before_links
                or {**link, "enabled": True} != {**before_links[link["id"]], "enabled": True}
                or (link["enabled"] and not before_links[link["id"]]["enabled"])
                for link in failed["links"]
            )
            or any(
                any(
                    server.get(key) != before_servers.get(server["id"], {}).get(key)
                    for key in (
                        "host",
                        "ssh_port",
                        "ssh_jump",
                        "address",
                        "credential_id",
                        "fingerprint",
                        "role",
                    )
                )
                for server in failed["servers"]
            )
        ):
            raise AppError("force_delete_recovery_conflict", 409)
    result = without_server(previous, server_id)
    snapshot = {**result, "revision": revision + 1, "affected_link_ids": sorted(incident)}
    snapshot["force_delete"] = {
        "version": 1,
        "server_id": server_id,
        "server_name": servers[server_id]["name"],
        "previous": previous,
        "desired_before": desired,
        "replaced_recovery": [job["id"] for job in recovery],
    }
    now, job_id = time.time(), uid()
    for job in recovery:
        db.execute("UPDATE jobs SET status='superseded',finished=? WHERE id=?", (now, job["id"]))
    db.execute("UPDATE state SET revision=revision+1 WHERE id=1")
    db.execute(
        "INSERT INTO jobs(id,revision,kind,status,snapshot,created) VALUES(?,?,?,'queued',?,?)",
        (job_id, revision + 1, KIND, json.dumps(snapshot), now),
    )
    audit(
        db, actor, "force_delete_requested", json.dumps({"server_id": server_id, "job_id": job_id})
    )
    return {"job_id": job_id, "revision": revision + 1}


def report(job):
    metadata = json.loads(job["snapshot"])["force_delete"]
    receipt = json.loads(job["receipt"])
    return {
        "server_id": metadata["server_id"],
        "server_name": metadata["server_name"],
        "hosts": [
            {
                "server_id": item["server"]["id"],
                "name": item["server"]["name"],
                "host": item["server"]["host"],
                "status": item.get("status", "pending"),
                "error_code": item.get("error_code"),
            }
            for item in receipt.get("hosts", [])
        ],
        "can_skip": job["status"] == "waiting_cleanup"
        and any(item.get("status") == "unreachable" for item in receipt.get("hosts", []))
        and all(
            item.get("status") in ("cleaned", "unreachable") for item in receipt.get("hosts", [])
        ),
    }


def resume(db, job_id, revision, actor, *, skip=False):
    if db.execute("SELECT revision FROM state WHERE id=1").fetchone()[0] != revision:
        raise AppError("revision_conflict", 409)
    row = db.execute("SELECT * FROM jobs WHERE id=? AND kind=?", (job_id, KIND)).fetchone()
    if not row:
        raise AppError("not_found", 404)
    if row["status"] != "waiting_cleanup":
        raise AppError("invalid_state", 409)
    if skip:
        if not report(row)["can_skip"]:
            raise AppError("force_delete_skip_denied", 409)
        receipt = json.loads(row["receipt"])
        receipt["skip_confirmed"] = True
        db.execute("UPDATE jobs SET receipt=? WHERE id=?", (json.dumps(receipt), job_id))
    db.execute("UPDATE jobs SET status='queued',next_run=0,finished=NULL WHERE id=?", (job_id,))
    audit(db, actor, "force_delete_skip_confirmed" if skip else "force_delete_retry", job_id)
    return {"job_id": job_id, "revision": revision}


def make_receipt(job, snapshot):
    from .worker import Target, targets

    metadata = snapshot["force_delete"]
    previous, target_id = metadata["previous"], metadata["server_id"]
    fleet = {target.identity: target for target in targets(previous, snapshot)}
    endpoint_ids = {target_id}
    for link in previous["links"] + metadata["desired_before"]["links"]:
        if target_id in (link["entry_id"], link["exit_id"]):
            endpoint_ids.update((link["entry_id"], link["exit_id"]))
    plans = build(snapshot)
    previous_ids = {server["id"] for server in previous["servers"]}
    candidates = previous["servers"] + [
        server
        for server in metadata["desired_before"]["servers"]
        if server["id"] not in previous_ids or server["id"] == target_id
    ]
    for server in candidates:
        if server["id"] in endpoint_ids:
            candidate = Target(server, plans.get(server["id"], empty()))
            fleet.setdefault(candidate.identity, candidate)
    return {
        "generation": job["id"] + "0001",
        "hosts": [{"server": target.server, "status": "pending"} for target in fleet.values()],
    }


def cleanup_host(worker, job, snapshot, receipt, item, plans, previous_plans):
    from .artifacts import ARTIFACTS

    server, namespace = item["server"], snapshot["namespace"]
    item.pop("error_code", None)
    try:
        worker.require_lease()
        log(job["id"], "force_delete_checking", server=server["id"])
        remote = worker.remote(server, namespace)
        remote.close()
    except Exception as error:
        if worker.lease_lost.is_set():
            raise
        code = error.code if isinstance(error, AppError) else "worker_error"
        item.update(status="unreachable" if code in NETWORK_ERRORS else "failed", error_code=code)
        worker.remember(job, receipt)
        log(job["id"], code, server=server["id"], level="error")
        return
    try:
        metadata = snapshot["force_delete"]
        plan = plans.get(server["id"], empty())
        old = previous_plans.get(server["id"], empty())
        if old.get("units") or plan.get("units") or metadata["replaced_recovery"]:
            body = {"generation": receipt["generation"]}
            for action, phase in (
                ("prepare", "preparing"),
                ("apply", "applying"),
                ("health", "checking"),
                ("commit", "committing"),
            ):
                item.update(status="working", phase=phase)
                worker.remember(job, receipt)
                log(job["id"], phase, server=server["id"])
                worker.operate(
                    server,
                    namespace,
                    action,
                    {**body, "plan": plan, "artifacts": ARTIFACTS} if action == "prepare" else body,
                    install=action == "prepare",
                )
        item.update(status="cleaned", phase="complete")
        worker.remember(job, receipt)
        log(job["id"], "force_delete_cleaned", server=server["id"])
    except Exception as error:
        if worker.lease_lost.is_set():
            raise
        code = error.code if isinstance(error, AppError) else "worker_error"
        item.update(status="failed", error_code=code)
        worker.remember(job, receipt)
        log(job["id"], code, server=server["id"], level="error")
        # Restore only the failed endpoint; never undo completed cleanup on its peers.
        log(job["id"], "rolling_back", server=server["id"])
        try:
            worker.operate(
                server, namespace, "rollback", {"generation": receipt["generation"]}, install=True
            )
            item["phase"] = "rolled_back"
            worker.remember(job, receipt)
        except Exception:
            if worker.lease_lost.is_set():
                raise
            item["phase"] = "uncertain"
            worker.remember(job, receipt)
            log(job["id"], "recovery_required", server=server["id"], level="error")


def finalize(worker, job, snapshot, receipt):
    target_id = snapshot["force_delete"]["server_id"]
    with connect(True) as db:
        if not worker.owns_lease(db):
            worker.lease_lost.set()
            return
        if db.execute("SELECT revision FROM state WHERE id=1").fetchone()[0] != job["revision"]:
            raise AppError("revision_conflict", 409)
        db.execute("DELETE FROM links WHERE entry_id=? OR exit_id=?", (target_id, target_id))
        db.execute("UPDATE servers SET deleted=1 WHERE id=?", (target_id,))
        current = topology.desired(db, True)
        applied = {
            key: value
            for key, value in snapshot.items()
            if key not in ("force_delete", "affected_link_ids")
        }
        same = build(current) == build(applied)
        db.execute(
            "UPDATE state SET applied=?,applied_revision=? WHERE id=1",
            (
                json.dumps(current if same else applied),
                job["revision"] if same else current["applied_revision"],
            ),
        )
        warning = any(item["status"] == "skipped" for item in receipt["hosts"])
        db.execute(
            "UPDATE jobs SET status='succeeded',error_code=?,finished=? WHERE id=? AND owner=?",
            ("force_delete_orphans" if warning else None, time.time(), job["id"], worker.owner),
        )
        audit(
            db,
            "worker",
            "server_force_deleted",
            json.dumps({"server_id": target_id, "job_id": job["id"], "cleanup_skipped": warning}),
        )
    log(
        job["id"],
        "force_delete_orphans" if warning else "force_delete_complete",
        level="warning" if warning else "info",
    )


def process(worker, job):
    snapshot = json.loads(job["snapshot"])
    target_id = snapshot["force_delete"]["server_id"]
    receipt = json.loads(job["receipt"]) or make_receipt(job, snapshot)
    worker.remember(job, receipt)
    plans = build(snapshot)
    previous_plans = build(snapshot["force_delete"]["previous"])
    log(job["id"], "force_delete_started")
    for item in receipt["hosts"]:
        if item["status"] in ("cleaned", "skipped"):
            continue
        if item["status"] == "unreachable" and receipt.get("skip_confirmed"):
            item["status"] = "skipped"
            worker.remember(job, receipt)
            log(job["id"], "force_delete_skipped", server=item["server"]["id"], level="warning")
            continue
        try:
            cleanup_host(worker, job, snapshot, receipt, item, plans, previous_plans)
        except Exception:
            if worker.lease_lost.is_set():
                return
            raise
    blocked = [item for item in receipt["hosts"] if item["status"] not in ("cleaned", "skipped")]
    # Only the selected unavailable server can be forgotten without another confirmation.
    if (
        blocked
        and all(
            item["server"]["id"] == target_id and item["status"] == "unreachable"
            for item in blocked
        )
        and any(item["status"] == "cleaned" for item in receipt["hosts"])
    ):
        for item in blocked:
            item["status"] = "skipped"
            log(job["id"], "force_delete_skipped", server=target_id, level="warning")
        worker.remember(job, receipt)
        blocked = []
    if (
        blocked
        and any(item["status"] == "failed" for item in blocked)
        and job["attempt"] < settings.MAX_ATTEMPTS
    ):
        worker.finish(job, "retrying", "force_delete_attention", delay=5 * 2 ** job["attempt"])
        log(job["id"], "retrying")
        return
    if blocked:
        worker.finish(job, "waiting_cleanup", "force_delete_attention")
        log(job["id"], "force_delete_attention", level="warning")
        return
    finalize(worker, job, snapshot, receipt)
