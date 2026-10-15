import base64
import json
import secrets
import time

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from .changes import affected_links
from .db import audit, uid
from .methods import REGISTRY
from .ports import contains, overlaps
from .security import AppError, seal, unseal
from .tls import create_identity


def material():
    noise = x25519.X25519PrivateKey.generate()
    client = ed25519.Ed25519PrivateKey.generate()
    host = ed25519.Ed25519PrivateKey.generate()

    def pem(key):
        return key.private_bytes(
            ser.Encoding.PEM, ser.PrivateFormat.OpenSSH, ser.NoEncryption()
        ).decode()

    def pub(key):
        return (
            key.public_key().public_bytes(ser.Encoding.OpenSSH, ser.PublicFormat.OpenSSH).decode()
        )

    return {
        **create_identity(),
        "token": secrets.token_urlsafe(32),
        "noise_private": base64.b64encode(noise.private_bytes_raw()).decode(),
        "noise_public": base64.b64encode(noise.public_key().public_bytes_raw()).decode(),
        "client_private": pem(client),
        "client_public": pub(client),
        "host_private": pem(host),
        "host_public": pub(host),
    }


def desired(db, private=False):
    state = dict(db.execute("SELECT * FROM state WHERE id=1").fetchone())
    servers = []
    for row in db.execute("SELECT * FROM servers WHERE deleted=0 ORDER BY created,id"):
        s = dict(row)
        s["position"] = json.loads(s["position"])
        s["ssh_jump"] = json.loads(s["ssh_jump"])
        s.pop("deleted")
        s.pop("created")
        servers.append(s)
    links = []
    for row in db.execute("SELECT * FROM links ORDER BY created,id"):
        link = dict(row)
        link["ports"] = json.loads(link["ports"])
        link["settings"] = json.loads(link["settings"])
        link["enabled"] = bool(link["enabled"])
        link.pop("created")
        if not private:
            link.pop("encrypted")
            link.pop("slot")
        links.append(link)
    return {
        "revision": state["revision"],
        "applied_revision": state["applied_revision"],
        "namespace": state["namespace"],
        **(
            {"method_versions": {key: adapter.plan_version for key, adapter in REGISTRY.items()}}
            if private
            else {}
        ),
        "servers": servers,
        "links": links,
    }


def validate(db, body):
    servers = {s.id: s for s in body.servers}
    if len(servers) != len(body.servers) or len({link.id for link in body.links}) != len(
        body.links
    ):
        raise AppError("invalid_topology")
    if len({s.address for s in body.servers}) != len(servers) or len(
        {(s.host, s.ssh_port) for s in body.servers}
    ) != len(servers):
        raise AppError("duplicate_host")
    credentials = {r[0] for r in db.execute("SELECT id FROM credentials")}
    if any(
        s.credential_id not in credentials
        or (s.ssh_jump and s.ssh_jump.credential_id not in credentials)
        for s in body.servers
    ):
        raise AppError("not_found", 404)
    ports = {}
    graph = {}
    for link in body.links:
        if link.method not in REGISTRY:
            raise AppError("invalid_topology")
        a, b = servers.get(link.entry_id), servers.get(link.exit_id)
        if not a or not b or a.id == b.id or a.role == "exit" or b.role == "entry":
            raise AppError("invalid_topology")
        adapter = REGISTRY[link.method]
        adapter.options(link.model_dump())
        adapter.validate_mappings(link.model_dump())
        mappings = [p.model_dump() for p in link.ports]
        for index, mapping in enumerate(mappings):
            if any(overlaps(mapping, other) for other in mappings[:index]):
                raise AppError("port_conflict")
        if not link.enabled:
            continue
        graph.setdefault(a.id, set()).add(b.id)
        native = adapter.compact_mapping(link.model_dump())
        for mapping in mappings:
            if contains(mapping, a.ssh_port):
                raise AppError("ssh_port_conflict")
            for other, policy, compact in ports.get(a.id, []):
                if overlaps(mapping, other):
                    if compact or native:
                        raise AppError("range_pool_conflict")
                    if policy != link.policy:
                        raise AppError("pool_policy")
            ports.setdefault(a.id, []).append((mapping, link.policy, native))

    control_ports = set()
    for link in body.links:
        if not link.enabled or link.control_port is None:
            continue
        adapter = REGISTRY[link.method]
        protocols = adapter.control_protocols(link.model_dump())
        if not protocols:
            raise AppError("invalid_topology")
        server_id = (
            link.entry_id if adapter.metadata["direction"] == "exit-to-entry" else link.exit_id
        )
        port = link.control_port
        for protocol in protocols:
            if protocol == "tcp" and port == servers[server_id].ssh_port:
                raise AppError("ssh_port_conflict")
            listener = (server_id, protocol, port)
            if listener in control_ports or (
                protocol == "tcp"
                and any(contains(mapping, port) for mapping, _, _ in ports.get(server_id, []))
            ):
                raise AppError("control_port_conflict")
            control_ports.add(listener)

    visiting, visited = set(), set()

    def walk(node):
        if node in visiting:
            raise AppError("topology_cycle")
        if node in visited:
            return
        visiting.add(node)
        for neighbor in graph.get(node, ()):
            walk(neighbor)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        walk(node)


def enqueue(db, actor, kind="deploy"):
    from .force_removals import require_idle

    require_idle(db)
    snapshot = desired(db, True)
    applied = json.loads(db.execute("SELECT applied FROM state WHERE id=1").fetchone()[0])
    snapshot["affected_link_ids"] = affected_links(applied, snapshot)
    job = uid()
    now = time.time()
    db.execute(
        "UPDATE jobs SET status='superseded',finished=? WHERE status IN ('queued','retrying')",
        (now,),
    )
    db.execute(
        "INSERT INTO jobs(id,revision,kind,status,snapshot,created) VALUES(?,?,?,'queued',?,?)",
        (job, snapshot["revision"], kind, json.dumps(snapshot), now),
    )
    audit(db, actor, kind, job)
    return job


def save(db, body, actor):
    from .force_removals import require_idle, retained_snapshots

    require_idle(db)
    state = db.execute("SELECT * FROM state WHERE id=1").fetchone()
    if state["revision"] != body.revision:
        raise AppError("revision_conflict", 409)
    if db.execute("SELECT 1 FROM jobs WHERE status='recovery_required'").fetchone():
        raise AppError("recovery_required", 409)
    validate(db, body)
    # Restoring a removed link must retain its slot and encrypted tunnel identity.
    old = {link["id"]: link for link in json.loads(state["applied"]).get("links", [])}
    old.update({r["id"]: dict(r) for r in db.execute("SELECT * FROM links")})
    # Do not recycle slots while old generations / recovery snapshots can reference them.
    snapshots = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT snapshot FROM jobs WHERE status IN ('running','queued','retrying','recovering','recovery_required')"
        )
    ]
    snapshots.extend(retained_snapshots(db))
    snapshots.append(json.loads(state["applied"]))
    used = {link["slot"] for s in snapshots for link in s.get("links", [])} | {
        v["slot"] for v in old.values()
    }
    db.execute("UPDATE servers SET deleted=1")
    for s in body.servers:
        v = s.model_dump()
        pos = json.dumps(v.pop("position"))
        db.execute(
            """INSERT INTO servers(id,name,host,ssh_port,role,address,credential_id,fingerprint,region,position,created,ssh_jump)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,host=excluded.host,ssh_port=excluded.ssh_port,role=excluded.role,address=excluded.address,credential_id=excluded.credential_id,fingerprint=excluded.fingerprint,region=excluded.region,position=excluded.position,ssh_jump=excluded.ssh_jump,deleted=0""",
            (
                s.id,
                s.name,
                s.host,
                s.ssh_port,
                s.role,
                s.address,
                s.credential_id,
                s.fingerprint,
                s.region,
                pos,
                time.time(),
                json.dumps(s.ssh_jump.model_dump() if s.ssh_jump else None),
            ),
        )
    db.execute("DELETE FROM links")
    for link in body.links:
        if link.id in old:
            slot = old[link.id]["slot"]
            encrypted = old[link.id]["encrypted"]
            stored = unseal(encrypted)
            if "tls_cert" not in stored:
                encrypted = seal({**stored, **create_identity()})
        else:
            slot = next((i for i in range(1, 1001) if i not in used), None)
            if slot is None:
                raise AppError("capacity")
            used.add(slot)
            encrypted = seal(material())
        db.execute(
            "INSERT INTO links(id,entry_id,exit_id,method,enabled,ports,policy,weight,slot,encrypted,created,control_port,settings) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                link.id,
                link.entry_id,
                link.exit_id,
                link.method,
                int(link.enabled),
                json.dumps([p.model_dump() for p in link.ports]),
                link.policy,
                link.weight,
                slot,
                encrypted,
                time.time(),
                link.control_port,
                json.dumps(link.settings),
            ),
        )
    # Compile before committing: switching adapters must validate capacity and bindings.
    from .board import reveal_required
    from .planner import build

    build(desired(db, True))
    reveal_required(db, desired(db))
    db.execute("UPDATE state SET revision=revision+1 WHERE id=1")
    return {"revision": body.revision + 1, "job_id": enqueue(db, actor)}
