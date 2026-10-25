"""Ask Sift (the general assistant): its runs, and AI tasks over a search instead of a folder

Revision ID: 0011
Revises: 0010

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('ai_tasks', sa.Column('query', sa.Text(), nullable=True))
    op.create_table(
        'assistant_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('reply', sa.Text()),
        sa.Column('steps', postgresql.JSONB(), server_default='[]', nullable=False),
        sa.Column('results', postgresql.JSONB(), server_default='[]', nullable=False),
        sa.Column('status', sa.String(10), server_default='planned', nullable=False),
        sa.Column('tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('planned', 'running', 'done', 'failed', 'cancelled')", name='status_valid'),
    )
    op.create_index('ix_assistant_runs_user_created', 'assistant_runs', ['user_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_assistant_runs_user_created', table_name='assistant_runs')
    op.drop_table('assistant_runs')
    op.drop_column('ai_tasks', 'query')
