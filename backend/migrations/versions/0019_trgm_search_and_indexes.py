"""add pg_trgm extension and trigram indexes on messages

Revision ID: 0019
Revises: 0018

"""
from collections.abc import Sequence

from alembic import op

revision: str = '0019'
down_revision: str | None = '0018'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_messages_subject_trgm ON messages USING gin (subject gin_trgm_ops);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_messages_sender_trgm ON messages USING gin (sender gin_trgm_ops);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_messages_sender_name_trgm ON messages USING gin (sender_name gin_trgm_ops);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_sender_name_trgm;")
    op.execute("DROP INDEX IF EXISTS ix_messages_sender_trgm;")
    op.execute("DROP INDEX IF EXISTS ix_messages_subject_trgm;")
