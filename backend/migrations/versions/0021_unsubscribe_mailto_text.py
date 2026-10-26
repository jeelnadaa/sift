"""widen unsubscribe_mailto to text

Revision ID: 0021
Revises: 0020

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0021'
down_revision: str | None = '0020'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column('messages', 'unsubscribe_mailto', type_=sa.Text(), existing_type=sa.String(length=320), nullable=True)


def downgrade() -> None:
    op.alter_column('messages', 'unsubscribe_mailto', type_=sa.String(length=320), existing_type=sa.Text(), nullable=True)
