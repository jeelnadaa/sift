"""add unsubscribe fields to messages

Revision ID: 0016
Revises: 0015

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0016'
down_revision: str | None = '0015'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('unsubscribe_url', sa.Text(), nullable=True))
    op.add_column('messages', sa.Column('unsubscribe_mailto', sa.String(length=320), nullable=True))
    op.add_column('messages', sa.Column('unsubscribe_post', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('messages', 'unsubscribe_post')
    op.drop_column('messages', 'unsubscribe_mailto')
    op.drop_column('messages', 'unsubscribe_url')
