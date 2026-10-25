"""create message_attachments table

Revision ID: 0014
Revises: 0013

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0014'
down_revision: str | None = '0013'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'message_attachments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('message_id', sa.UUID(), nullable=False),
        sa.Column('gmail_id', sa.String(length=64), nullable=False),
        sa.Column('attachment_id', sa.Text(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('mime', sa.String(length=120), nullable=False),
        sa.Column('size', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('content_id', sa.String(length=255), nullable=True),
        sa.Column('sender', sa.String(length=320), nullable=True),
        sa.Column('sender_name', sa.String(length=200), nullable=True),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['gmail_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_message_attachments_user_received', 'message_attachments', ['user_id', 'received_at'])
    op.create_index('ix_message_attachments_user_mime', 'message_attachments', ['user_id', 'mime'])
    op.create_index('ix_message_attachments_user_filename', 'message_attachments', ['user_id', 'filename'])
    op.create_index('ix_message_attachments_message', 'message_attachments', ['message_id'])


def downgrade() -> None:
    op.drop_index('ix_message_attachments_message', table_name='message_attachments')
    op.drop_index('ix_message_attachments_user_filename', table_name='message_attachments')
    op.drop_index('ix_message_attachments_user_mime', table_name='message_attachments')
    op.drop_index('ix_message_attachments_user_received', table_name='message_attachments')
    op.drop_table('message_attachments')
