"""Keep board placement separate from deployment snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "b74d8ea93021"
down_revision = "af62c83419de"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "board_inventory",
        sa.Column("server_id", sa.String(32), sa.ForeignKey("servers.id"), primary_key=True),
    )


def downgrade():
    op.drop_table("board_inventory")
