"""Assistant reply status: answer, clarify, or unknown.

Adds the envelope columns to stored messages plus the per-conversation clarification streak
used to stop the assistant from asking the same kind of question forever.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_assistant_status"
down_revision = "0008_workflow_cron"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_messages",
        sa.Column("status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("clarify_options", sa.JSON(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("clarify_streak", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("conversations", "clarify_streak")
    op.drop_column("conversation_messages", "clarify_options")
    op.drop_column("conversation_messages", "status")
