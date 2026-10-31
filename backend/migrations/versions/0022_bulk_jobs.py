"""bulk jobs: big changes to many conversations, run in the worker with progress

Revision ID: 0022
Revises: 0021

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0022'
down_revision: str | None = '0021'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'bulk_jobs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('message_ids', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('status', sa.String(length=10), server_default='queued', nullable=False),
        sa.Column('total', sa.Integer(), server_default='0', nullable=False),
        sa.Column('done', sa.Integer(), server_default='0', nullable=False),
        sa.Column('changed', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('failed_accounts', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name='status_valid'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bulk_jobs_user_created', 'bulk_jobs', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_bulk_jobs_user_created', table_name='bulk_jobs')
    op.drop_table('bulk_jobs')
