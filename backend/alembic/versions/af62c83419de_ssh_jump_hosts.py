"""Persist optional pinned SSH jump-host settings per server."""

import sqlalchemy as sa
from alembic import op

revision = "af62c83419de"
down_revision = "92bfc04e31ad"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "servers", sa.Column("ssh_jump", sa.Text(), nullable=False, server_default="null")
    )


def downgrade():
    op.drop_column("servers", "ssh_jump")
