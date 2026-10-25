"""add vip_senders and muted_threads tables

Revision ID: 0020
Revises: 0019

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0020'
down_revision: str | None = '0019'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'vip_senders',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('sender_name', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'email', name='uq_vip_sender_user_email'),
    )
    op.create_index('ix_vip_senders_user_email', 'vip_senders', ['user_id', 'email'])

    op.create_table(
        'muted_threads',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('thread_id', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'thread_id', name='uq_muted_thread_user_thread'),
    )
    op.create_index('ix_muted_threads_user_thread', 'muted_threads', ['user_id', 'thread_id'])


def downgrade() -> None:
    op.drop_index('ix_muted_threads_user_thread', table_name='muted_threads')
    op.drop_table('muted_threads')
    op.drop_index('ix_vip_senders_user_email', table_name='vip_senders')
    op.drop_table('vip_senders')
