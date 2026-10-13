import base64
import json
import secrets
import time

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from .db import audit, uid
from .methods import REGISTRY
from .security import AppError, seal
from .tls import create_identity


def material():
    noise = x25519.X25519PrivateKey.generate()
    client = ed25519.Ed25519PrivateKey.generate()
    host = ed25519.Ed25519PrivateKey.generate()
    pem = lambda k: k.private_bytes(
        ser.Encoding.PEM, ser.PrivateFormat.OpenSSH, ser.NoEncryption()
    ).decode()
    pub = (
        lambda k: k.public_key()
        .public_bytes(ser.Encoding.OpenSSH, ser.PublicFormat.OpenSSH)
        .decode()
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
        s.pop("deleted")
        s.pop("created")
        servers.append(s)
    links = []
    for row in db.execute("SELECT * FROM links ORDER BY created,id"):
        link = dict(row)
        link["ports"] = json.loads(link["ports"])
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
        "servers": servers,
        "links": links,
    }


def validate(db, body):
    servers = {s.id: s for s in body.servers}
    if len(servers) != len(body.servers) or len({l.id for l in body.links}) != len(body.links):
        raise AppError("invalid_topology")
    if len({s.address for s in body.servers}) != len(servers) or len(
        {(s.host, s.ssh_port) for s in body.servers}
    ) != len(servers):
        raise AppError("duplicate_host")
    credentials = {r[0] for r in db.execute("SELECT id FROM credentials")}
    if any(s.credential_id not in credentials for s in body.servers):
        raise AppError("not_found", 404)
    ports = {}
    graph = {}
    for l in body.links:
        if l.method not in REGISTRY:
            raise AppError("invalid_topology")
        a, b = servers.get(l.entry_id), servers.get(l.exit_id)
        if not a or not b or a.id == b.id or a.role == "exit" or b.role == "entry":
            raise AppError("invalid_topology")
        if len({p.public for p in l.ports}) != len(l.ports):
            raise AppError("port_conflict")
        if not l.enabled:
            continue
        graph.setdefault(a.id, set()).add(b.id)
        for p in l.ports:
            # Internal ports are deterministic and reserved; don't collide with management SSH.
            if 20000 <= p.public <= 60999 or p.public == a.ssh_port:
                raise AppError("reserved_port")
            k = (a.id, p.public)
            if k in ports and ports[k] != l.policy:
                raise AppError("pool_policy")
            ports[k] = l.policy

    def walk(node, path):
        if node in path:
            raise AppError("topology_cycle")
        for n in graph.get(node, ()):
            walk(n, path | {node})

    for n in graph:
        walk(n, set())


def enqueue(db, actor, kind="deploy"):
    snapshot = desired(db, True)
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
    state = db.execute("SELECT * FROM state WHERE id=1").fetchone()
    if state["revision"] != body.revision:
        raise AppError("revision_conflict", 409)
    if db.execute("SELECT 1 FROM jobs WHERE status='recovery_required'").fetchone():
        raise AppError("recovery_required", 409)
    validate(db, body)
    old = {r["id"]: dict(r) for r in db.execute("SELECT * FROM links")}
    # Do not recycle slots while old generations / recovery snapshots can reference them.
    snapshots = [json.loads(r[0]) for r in db.execute("SELECT snapshot FROM jobs")]
    used = {l["slot"] for s in snapshots for l in s.get("links", [])} | {
        v["slot"] for v in old.values()
    }
    db.execute("UPDATE servers SET deleted=1")
    for s in body.servers:
        v = s.model_dump()
        pos = json.dumps(v.pop("position"))
        db.execute(
            """INSERT INTO servers(id,name,host,ssh_port,role,address,credential_id,fingerprint,region,position,created)
          VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,host=excluded.host,ssh_port=excluded.ssh_port,role=excluded.role,address=excluded.address,credential_id=excluded.credential_id,fingerprint=excluded.fingerprint,region=excluded.region,position=excluded.position,deleted=0""",
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
            ),
        )
    db.execute("DELETE FROM links")
    for l in body.links:
        if l.id in old:
            slot = old[l.id]["slot"]
            encrypted = old[l.id]["encrypted"]
        else:
            slot = next((i for i in range(1, 1001) if i not in used), None)
            if slot is None:
                raise AppError("capacity")
            used.add(slot)
            encrypted = seal(material())
        db.execute(
            "INSERT INTO links VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                l.id,
                l.entry_id,
                l.exit_id,
                l.method,
                int(l.enabled),
                json.dumps([p.model_dump() for p in l.ports]),
                l.policy,
                l.weight,
                slot,
                encrypted,
                time.time(),
            ),
        )
    db.execute("UPDATE state SET revision=revision+1 WHERE id=1")
    return {"revision": body.revision + 1, "job_id": enqueue(db, actor)}
