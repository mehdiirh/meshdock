"""Opt-in sample inventory. TEST-NET endpoints are never used by the real worker."""

import time

from fastapi import APIRouter, Depends

from .. import schemas, settings, topology
from ..db import connect, uid
from ..security import AppError, require, seal

router = APIRouter()


@router.post("/demo/seed")
def seed(actor=Depends(require("admin"))):
    if not settings.DEMO:
        raise AppError("forbidden", 403)
    with connect(True) as database:
        current = topology.desired(database)
        if current["servers"]:
            raise AppError("invalid_state", 409)
        credential_id = uid()
        database.execute(
            "INSERT INTO credentials VALUES(?,?,?,?,?)",
            (
                credential_id,
                "Simulation credential",
                "password",
                seal({"kind": "password", "secret": "simulation-only"}),
                time.time(),
            ),
        )
        servers = []
        examples = [
            ("Gateway 01", "entry", "West region"),
            ("Gateway 02", "entry", "East region"),
            ("Edge 01", "exit", "Central Europe"),
            ("Edge 02", "exit", "North America"),
            ("Edge 03", "exit", "Western Asia"),
        ]
        for index, (name, role, region) in enumerate(examples):
            servers.append(
                schemas.Server(
                    id=uid(),
                    name=name,
                    role=role,
                    region=region,
                    host=f"192.0.2.{index+10}",
                    address=f"192.0.2.{index+10}",
                    ssh_port=22,
                    credential_id=credential_id,
                    fingerprint="SHA256:" + "A" * 43,
                    position={
                        "x": 80 if role == "entry" else 520,
                        "y": (100 + index * 240 if role == "entry" else 20 + (index - 2) * 220),
                    },
                )
            )
        links = []
        for entry, exit, method in [
            (0, 2, "frp_wss"),
            (0, 3, "rathole"),
            (1, 3, "hysteria2"),
            (1, 4, "gre"),
        ]:
            links.append(
                schemas.Link(
                    id=uid(),
                    entry_id=servers[entry].id,
                    exit_id=servers[exit].id,
                    method=method,
                    ports=[schemas.Port(public=443, target=8443)],
                )
            )
        return topology.save(
            database,
            schemas.Topology(revision=current["revision"], servers=servers, links=links),
            actor,
        )
