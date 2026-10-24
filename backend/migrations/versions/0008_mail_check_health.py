"""mail check health

Revision ID: 0008
Revises: 0007

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('gmail_accounts', sa.Column('last_check_ok_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('gmail_accounts', sa.Column('check_failing_since', sa.DateTime(timezone=True), nullable=True))
    op.add_column('gmail_accounts', sa.Column('last_check_error', sa.String(length=200), nullable=True))
    op.add_column('gmail_accounts', sa.Column('intake_alerted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('gmail_accounts', 'intake_alerted_at')
    op.drop_column('gmail_accounts', 'last_check_error')
    op.drop_column('gmail_accounts', 'check_failing_since')
    op.drop_column('gmail_accounts', 'last_check_ok_at')
