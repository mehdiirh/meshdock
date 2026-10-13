"""Persist per-link method settings without changing existing defaults."""

import sqlalchemy as sa
from alembic import op

revision = "6f3c98a12d04"
down_revision = "8d4af912ab63"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("links", sa.Column("settings", sa.Text(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("links", "settings")
