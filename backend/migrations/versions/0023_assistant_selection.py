"""Ask Sift remembers what was selected when the user asked ("these").

Revision ID: 0023
Revises: 0022
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assistant_runs", sa.Column("selection", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("assistant_runs", "selection")
