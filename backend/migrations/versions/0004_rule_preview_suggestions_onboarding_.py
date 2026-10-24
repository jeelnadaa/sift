"""rule preview, suggestions, onboarding scans

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24 08:58:34.895905
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('onboarding_scans',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='queued', nullable=False),
    sa.Column('scanned', sa.Integer(), server_default='0', nullable=False),
    sa.Column('senders', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name='status_valid'),
    sa.ForeignKeyConstraint(['account_id'], ['gmail_accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_onboarding_scans_account_id'), 'onboarding_scans', ['account_id'], unique=False)
    op.create_index(op.f('ix_onboarding_scans_user_id'), 'onboarding_scans', ['user_id'], unique=False)
    op.add_column('fingerprints', sa.Column('domain', sa.String(length=253), nullable=True))
    op.add_column('fingerprints', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('messages', sa.Column('header_names', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'header_names')
    op.drop_column('fingerprints', 'created_at')
    op.drop_column('fingerprints', 'domain')
    op.drop_index(op.f('ix_onboarding_scans_user_id'), table_name='onboarding_scans')
    op.drop_index(op.f('ix_onboarding_scans_account_id'), table_name='onboarding_scans')
    op.drop_table('onboarding_scans')
