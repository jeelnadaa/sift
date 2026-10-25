"""add index on messages(user_id, sender)

Revision ID: 0015
Revises: 0014

"""
from collections.abc import Sequence

from alembic import op

revision: str = '0015'
down_revision: str | None = '0014'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index('ix_messages_user_sender', 'messages', ['user_id', 'sender'])


def downgrade() -> None:
    op.drop_index('ix_messages_user_sender', table_name='messages')
