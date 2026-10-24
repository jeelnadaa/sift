"""outbox (undo send, send later) and follow-up reminders

Revision ID: 0009
Revises: 0008

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'outbox',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('gmail_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('draft_id', sa.String(64), nullable=False),
        sa.Column('thread_id', sa.String(64)),
        sa.Column('subject', sa.Text()),
        sa.Column('recipients', sa.Text()),
        sa.Column('send_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('later', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('follow_up_days', sa.Integer()),
        sa.Column('status', sa.String(10), server_default='scheduled', nullable=False),
        sa.Column('sending_since', sa.DateTime(timezone=True)),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('sent_gmail_id', sa.String(64)),
        sa.Column('sent_at', sa.DateTime(timezone=True)),
        sa.Column('error', sa.String(300)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('scheduled', 'sending', 'sent', 'cancelled', 'failed')", name='status_valid'),
    )
    op.create_index('ix_outbox_user_id', 'outbox', ['user_id'])
    op.create_index('ix_outbox_due', 'outbox', ['status', 'send_at'])
    op.create_index('uq_outbox_pending_draft', 'outbox', ['account_id', 'draft_id'], unique=True,
                    postgresql_where=sa.text("status IN ('scheduled', 'sending')"))
    op.create_table(
        'follow_ups',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('gmail_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('thread_id', sa.String(64), nullable=False),
        sa.Column('sent_gmail_id', sa.String(64)),
        sa.Column('subject', sa.Text()),
        sa.Column('recipients', sa.Text()),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(10), server_default='waiting', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('waiting', 'replied', 'reminded', 'cancelled')", name='status_valid'),
    )
    op.create_index('ix_follow_ups_user_id', 'follow_ups', ['user_id'])
    op.create_index('ix_follow_ups_due', 'follow_ups', ['status', 'due_at'])
    op.create_index('ix_follow_ups_thread', 'follow_ups', ['account_id', 'thread_id'])


def downgrade() -> None:
    op.drop_table('follow_ups')
    op.drop_table('outbox')
