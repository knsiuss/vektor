"""add_user_memories

Revision ID: 43d9721ac8ef
Revises: 1b6e4a9d3c02
Create Date: 2026-11-24 12:49:42.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "43d9721ac8ef"
down_revision: Union[str, Sequence[str], None] = "0015_oauth_login"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("user_memories"):
        # Provisioned out-of-band (metadata.create_all); keep the migration re-runnable.
        return
    op.create_table(
        "user_memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_memories_owner", "user_memories", ["tenant_id", "user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_memories_owner", table_name="user_memories")
    op.drop_table("user_memories")
