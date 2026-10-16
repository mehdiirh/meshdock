"""Make legacy desired port mappings explicitly TCP without rewriting job history."""

import json

import sqlalchemy as sa
from alembic import op

revision = "c81f6e902a14"
down_revision = "b74d8ea93021"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    for row in connection.execute(sa.text("SELECT id,ports FROM links")).mappings():
        mappings = json.loads(row["ports"])
        for mapping in mappings:
            mapping.setdefault("protocol", "tcp")
        connection.execute(
            sa.text("UPDATE links SET ports=:ports WHERE id=:id"),
            {"id": row["id"], "ports": json.dumps(mappings)},
        )


def has_datagrams(value):
    if isinstance(value, dict):
        if "public" in value and "target" in value and value.get("protocol") in ("udp", "both"):
            return True
        return any(has_datagrams(item) for item in value.values())
    return isinstance(value, list) and any(has_datagrams(item) for item in value)


def downgrade():
    connection = op.get_bind()
    for query in (
        "SELECT ports FROM links",
        "SELECT applied FROM state",
        "SELECT snapshot FROM jobs",
    ):
        for row in connection.execute(sa.text(query)):
            if has_datagrams(json.loads(row[0])):
                raise RuntimeError(
                    "UDP mappings require a matching database backup to downgrade safely"
                )
    for row in connection.execute(sa.text("SELECT id,ports FROM links")).mappings():
        mappings = json.loads(row["ports"])
        for mapping in mappings:
            mapping.pop("protocol", None)
        connection.execute(
            sa.text("UPDATE links SET ports=:ports WHERE id=:id"),
            {"id": row["id"], "ports": json.dumps(mappings)},
        )
