"""custom groups with criteria, "fill" AI tasks, Sift AI token use kept apart

Revision ID: 0012
Revises: 0011

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # a custom group's criteria: a Sift search (free) and/or a description the AI checks
    op.add_column('mail_groups', sa.Column('query', sa.Text(), nullable=True))
    op.add_column('mail_groups', sa.Column('instruction', sa.Text(), nullable=True))
    # "fill": put matching mail into one group or folder (target)
    op.drop_constraint('kind_valid', 'ai_tasks', type_='check')
    op.create_check_constraint('kind_valid', 'ai_tasks', "kind IN ('timelines', 'todos', 'sort', 'fill')")
    op.add_column('ai_tasks', sa.Column('target_group_id', postgresql.UUID(as_uuid=True),
                                        sa.ForeignKey('mail_groups.id', ondelete='CASCADE'), nullable=True))
    # what Sift AI (Ask Sift) spent, apart from everyday work
    op.add_column('ai_tasks', sa.Column('assistant_run_id', postgresql.UUID(as_uuid=True),
                                        sa.ForeignKey('assistant_runs.id', ondelete='SET NULL'), nullable=True))
    op.add_column('token_usage', sa.Column('assistant_run_id', postgresql.UUID(as_uuid=True),
                                           sa.ForeignKey('assistant_runs.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_token_usage_assistant_run_id', 'token_usage', ['assistant_run_id'])


def downgrade() -> None:
    op.drop_index('ix_token_usage_assistant_run_id', table_name='token_usage')
    op.drop_column('token_usage', 'assistant_run_id')
    op.drop_column('ai_tasks', 'assistant_run_id')
    op.drop_column('ai_tasks', 'target_group_id')
    op.execute("DELETE FROM ai_tasks WHERE kind = 'fill'")
    op.drop_constraint('kind_valid', 'ai_tasks', type_='check')
    op.create_check_constraint('kind_valid', 'ai_tasks', "kind IN ('timelines', 'todos', 'sort')")
    op.drop_column('mail_groups', 'instruction')
    op.drop_column('mail_groups', 'query')
