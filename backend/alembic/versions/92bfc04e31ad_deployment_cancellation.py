"""Durable cooperative deployment cancellation."""

import sqlalchemy as sa
from alembic import op

revision = "92bfc04e31ad"
down_revision = "6f3c98a12d04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "jobs", sa.Column("cancel_requested", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade():
    op.drop_column("jobs", "cancel_requested")
