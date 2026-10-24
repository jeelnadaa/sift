"""folder AI filing and sorting, AI tasks, token use per task

Revision ID: 0010
Revises: 0009

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('folders', sa.Column('ai_rule', postgresql.JSONB(), nullable=True))
    op.add_column('folders', sa.Column('auto_sort', sa.String(10), nullable=True))
    op.add_column('folders', sa.Column('auto_sort_instruction', sa.Text(), nullable=True))
    op.create_table(
        'ai_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('folder_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('folders.id', ondelete='SET NULL')),
        sa.Column('folder_name', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('include_subfolders', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('instruction', sa.Text()),
        sa.Column('status', sa.String(10), server_default='queued', nullable=False),
        sa.Column('total', sa.Integer(), server_default='0', nullable=False),
        sa.Column('done', sa.Integer(), server_default='0', nullable=False),
        sa.Column('changed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('note', sa.String(300)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('timelines', 'todos', 'sort')", name='kind_valid'),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'stopped', 'failed')", name='status_valid'),
    )
    op.create_index('ix_ai_tasks_user_created', 'ai_tasks', ['user_id', 'created_at'])
    op.add_column('token_usage', sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ai_tasks.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_token_usage_task_id', 'token_usage', ['task_id'])


def downgrade() -> None:
    op.drop_index('ix_token_usage_task_id', table_name='token_usage')
    op.drop_column('token_usage', 'task_id')
    op.drop_table('ai_tasks')
    op.drop_column('folders', 'auto_sort_instruction')
    op.drop_column('folders', 'auto_sort')
    op.drop_column('folders', 'ai_rule')
