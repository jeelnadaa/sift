"""add base_url and fallback provider to llm_credentials

Revision ID: 0018
Revises: 0017

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0018'
down_revision: str | None = '0017'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('llm_credentials', sa.Column('base_url', sa.String(length=255), nullable=True))
    op.add_column('llm_credentials', sa.Column('fallback_provider', sa.String(length=40), nullable=True))
    op.add_column('llm_credentials', sa.Column('fallback_model', sa.String(length=120), nullable=True))
    op.add_column('llm_credentials', sa.Column('fallback_base_url', sa.String(length=255), nullable=True))
    op.add_column('llm_credentials', sa.Column('encrypted_fallback_key', sa.Text(), nullable=True))
    op.add_column('llm_credentials', sa.Column('fallback_key_last4', sa.String(length=4), nullable=True))


def downgrade() -> None:
    op.drop_column('llm_credentials', 'fallback_key_last4')
    op.drop_column('llm_credentials', 'encrypted_fallback_key')
    op.drop_column('llm_credentials', 'fallback_base_url')
    op.drop_column('llm_credentials', 'fallback_model')
    op.drop_column('llm_credentials', 'fallback_provider')
    op.drop_column('llm_credentials', 'base_url')
