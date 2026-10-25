"""add pinned column and index to messages

Revision ID: 0013
Revises: 0012

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0013'
down_revision: str | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('pinned', sa.Boolean(), server_default='false', nullable=False))
    op.create_index('ix_messages_user_pinned', 'messages', ['user_id', 'pinned'])


def downgrade() -> None:
    op.drop_index('ix_messages_user_pinned', table_name='messages')
    op.drop_column('messages', 'pinned')
