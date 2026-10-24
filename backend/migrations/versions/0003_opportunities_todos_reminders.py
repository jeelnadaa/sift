"""opportunities, todos, reminders (Phase 2a)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24 08:41:16.274430
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_KINDS = "kind IN ('announcement', 'registration', 'assessment', 'interview', 'result', 'update')"


def upgrade() -> None:
    op.create_table('todos',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('message_id', sa.UUID(), nullable=True),
        sa.Column('opportunity_id', sa.UUID(), nullable=True),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('done', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source', sa.String(length=10), server_default='manual', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_todos_user_done_due', 'todos', ['user_id', 'done', 'due_at'], unique=False)
    op.create_index(op.f('ix_todos_user_id'), 'todos', ['user_id'], unique=False)

    op.add_column('opportunities', sa.Column('domains', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_opportunities_user_status', 'opportunities', ['user_id', 'status'], unique=False)
    op.create_check_constraint('status_valid', 'opportunities', "status IN ('active', 'closed')")

    op.add_column('opportunity_events', sa.Column('matched_by', sa.String(length=20), server_default='user', nullable=False))
    op.create_unique_constraint('opportunity_events_message_id_key', 'opportunity_events', ['message_id'])
    op.create_check_constraint('kind_valid', 'opportunity_events', EVENT_KINDS)

    op.add_column('reminders', sa.Column('todo_id', sa.UUID(), nullable=True))
    op.add_column('reminders', sa.Column('kind', sa.String(length=20), server_default='custom', nullable=False))
    op.add_column('reminders', sa.Column('dedupe_key', sa.String(length=200), nullable=True))
    op.create_unique_constraint('reminders_user_id_dedupe_key_key', 'reminders', ['user_id', 'dedupe_key'])
    op.create_foreign_key('reminders_todo_id_fkey', 'reminders', 'todos', ['todo_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('reminders_todo_id_fkey', 'reminders', type_='foreignkey')
    op.drop_constraint('reminders_user_id_dedupe_key_key', 'reminders', type_='unique')
    op.drop_column('reminders', 'dedupe_key')
    op.drop_column('reminders', 'kind')
    op.drop_column('reminders', 'todo_id')
    op.drop_constraint('kind_valid', 'opportunity_events', type_='check')
    op.drop_constraint('opportunity_events_message_id_key', 'opportunity_events', type_='unique')
    op.drop_column('opportunity_events', 'matched_by')
    op.drop_constraint('status_valid', 'opportunities', type_='check')
    op.drop_index('ix_opportunities_user_status', table_name='opportunities')
    op.drop_column('opportunities', 'domains')
    op.drop_index(op.f('ix_todos_user_id'), table_name='todos')
    op.drop_index('ix_todos_user_done_due', table_name='todos')
    op.drop_table('todos')
