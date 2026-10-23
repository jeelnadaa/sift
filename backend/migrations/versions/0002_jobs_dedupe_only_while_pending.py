"""jobs dedupe only while pending

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24 05:03:29.449764
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f('jobs_dedupe_key_key'), 'jobs', type_='unique')
    op.create_index('ix_jobs_dedupe_pending', 'jobs', ['dedupe_key'], unique=True, postgresql_where=sa.text("status IN ('queued', 'running')"))


def downgrade() -> None:
    op.drop_index('ix_jobs_dedupe_pending', table_name='jobs', postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_unique_constraint(op.f('jobs_dedupe_key_key'), 'jobs', ['dedupe_key'], postgresql_nulls_not_distinct=False)
