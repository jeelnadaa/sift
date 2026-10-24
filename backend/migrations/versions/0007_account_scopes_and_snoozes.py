"""account scopes and snoozes

Revision ID: 0007
Revises: 0006

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('snoozes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('thread_id', sa.String(length=64), nullable=False),
    sa.Column('message_id', sa.UUID(), nullable=True),
    sa.Column('until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('archived_in_gmail', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('done', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('woke_reason', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['gmail_accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_snoozes_due', 'snoozes', ['done', 'until'], unique=False)
    op.create_index(op.f('ix_snoozes_user_id'), 'snoozes', ['user_id'], unique=False)
    op.create_index('uq_snoozes_active_thread', 'snoozes', ['account_id', 'thread_id'], unique=True, postgresql_where=sa.text('NOT done'))
    op.add_column('gmail_accounts', sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('gmail_accounts', 'scopes')
    op.drop_index('uq_snoozes_active_thread', table_name='snoozes', postgresql_where=sa.text('NOT done'))
    op.drop_index(op.f('ix_snoozes_user_id'), table_name='snoozes')
    op.drop_index('ix_snoozes_due', table_name='snoozes')
    op.drop_table('snoozes')
