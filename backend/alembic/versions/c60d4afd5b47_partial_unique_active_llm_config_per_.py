"""partial unique active llm_config per user

Revision ID: c60d4afd5b47
Revises: b4e627609b8f
Create Date: 2026-04-24 10:00:49.329853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c60d4afd5b47'
down_revision: Union[str, Sequence[str], None] = 'b4e627609b8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_llm_config_one_active_per_user",
        "llm_config",
        ["user_id"],
        unique=True,
        postgresql_where="is_active",
    )


def downgrade() -> None:
    op.drop_index("uq_llm_config_one_active_per_user", table_name="llm_config")
