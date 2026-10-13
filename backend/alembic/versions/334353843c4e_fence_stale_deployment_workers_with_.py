"""Fence stale deployment workers with lease epochs

Revision ID: 334353843c4e
Revises: ed9a37d2efc4
"""

import sqlalchemy as sa
from alembic import op

revision = "334353843c4e"
down_revision = "ed9a37d2efc4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "leader", sa.Column("epoch", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade():
    # SQLite >= 3.35 supports DROP COLUMN without rebuilding away the singleton constraint.
    op.drop_column("leader", "epoch")
