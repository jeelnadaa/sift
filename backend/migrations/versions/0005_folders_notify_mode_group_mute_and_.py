"""folders notify mode, group mute and collapse (Phase 2c)

Revision ID: 0005
Revises: 0004
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('folders', sa.Column('notify_mode', sa.String(length=10), server_default='default', nullable=False))
    op.execute("UPDATE folders SET notify_mode = 'always' WHERE notify")
    op.drop_column('folders', 'notify')
    op.create_check_constraint('notify_mode_valid', 'folders', "notify_mode IN ('default', 'always', 'mute')")
    op.add_column('mail_groups', sa.Column('muted', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('mail_groups', sa.Column('collapsed', sa.Boolean(), server_default='true', nullable=False))


def downgrade() -> None:
    op.drop_column('mail_groups', 'collapsed')
    op.drop_column('mail_groups', 'muted')
    op.drop_constraint('notify_mode_valid', 'folders', type_='check')
    op.add_column('folders', sa.Column('notify', sa.Boolean(), server_default='false', nullable=False))
    op.execute("UPDATE folders SET notify = (notify_mode = 'always')")
    op.drop_column('folders', 'notify_mode')
