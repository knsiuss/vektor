"""Add assigned_agent_id column to channel_sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_inbox_assignment"
down_revision: str | None = "0019_evals_and_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("channel_sessions")}
    if "assigned_agent_id" in columns:
        return
    op.add_column(
        "channel_sessions",
        sa.Column("assigned_agent_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_channel_sessions_assigned_agent_id",
        "channel_sessions",
        ["assigned_agent_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_channel_sessions_assigned_agent_id", table_name="channel_sessions")
    op.drop_column("channel_sessions", "assigned_agent_id")
