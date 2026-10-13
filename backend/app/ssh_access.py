"""Resolve encrypted SSH credentials without placing secrets in job snapshots."""

import json

from .security import AppError, unseal


def credential_ids(server):
    ids = {server["credential_id"]}
    jump = server.get("ssh_jump")
    if isinstance(jump, str):
        jump = json.loads(jump)
    if jump:
        ids.add(jump["credential_id"])
    return ids


def credential(db, credential_id):
    row = db.execute("SELECT encrypted FROM credentials WHERE id=?", (credential_id,)).fetchone()
    if not row:
        raise AppError("not_found", 404)
    return unseal(row["encrypted"])


def access_credentials(db, server):
    result = credential(db, server["credential_id"])
    if server.get("ssh_jump"):
        result["jump"] = credential(db, server["ssh_jump"]["credential_id"])
    return result
