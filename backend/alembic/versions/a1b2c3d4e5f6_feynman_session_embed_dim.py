"""feynman_session embed_dim and started_at index

Revision ID: a1b2c3d4e5f6
Revises: 033233505aa3
Create Date: 2026-04-27 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '033233505aa3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add embed_dim as nullable first so backfill can proceed
    op.add_column('feynman_session', sa.Column('embed_dim', sa.Integer(), nullable=True))
    # Backfill existing rows (1536 is the only dim used so far)
    op.execute("UPDATE feynman_session SET embed_dim = 1536 WHERE embed_dim IS NULL")
    # Now enforce NOT NULL
    op.alter_column('feynman_session', 'embed_dim', nullable=False)
    # Composite index for dashboard queries
    op.create_index(
        'ix_feynman_session_user_started',
        'feynman_session',
        ['user_id', sa.text('started_at DESC')],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_feynman_session_user_started', table_name='feynman_session')
    op.drop_column('feynman_session', 'embed_dim')
