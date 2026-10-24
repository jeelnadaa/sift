"""message embeddings for semantic search

Revision ID: 0006
Revises: 0005

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('message_embeddings',
    sa.Column('message_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('dims', sa.Integer(), nullable=False),
    sa.Column('vector', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id')
    )
    op.create_index(op.f('ix_message_embeddings_user_id'), 'message_embeddings', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_message_embeddings_user_id'), table_name='message_embeddings')
    op.drop_table('message_embeddings')
