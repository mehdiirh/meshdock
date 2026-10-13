"""Allow explicit transport control ports without changing existing deployments.

Revision ID: 8d4af912ab63
Revises: 334353843c4e
"""

import sqlalchemy as sa
from alembic import op

revision = "8d4af912ab63"
down_revision = "334353843c4e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("links", sa.Column("control_port", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("links", "control_port")
