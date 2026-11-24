"""Add eval_cases and action_approvals tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_evals_and_approvals"
down_revision: str | None = "0018_widgets_and_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("eval_cases"):
        # Provisioned out-of-band (metadata.create_all); keep the migration re-runnable.
        return
    op.create_table(
        "eval_cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("bot_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_facts", sa.JSON(), nullable=False),
        sa.Column("forbidden_claims", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "action_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, index=True),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("action_approvals")
    op.drop_table("eval_cases")
