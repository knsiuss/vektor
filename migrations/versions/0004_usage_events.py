"""Usage events: per-call upstream model usage attributed to tenant and user.

Revision ID: 0004_usage_events
Revises: 0003_knowledge_scoping
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_usage_events"
down_revision = "0003_knowledge_scoping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "usage_events" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=False),
        sa.Column("completion_tokens", sa.Integer, nullable=False),
        sa.Column("total_tokens", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_usage_events_tenant_created", "usage_events", ["tenant_id", "created_at"])
    op.create_index(
        "ix_usage_events_tenant_user_created",
        "usage_events",
        ["tenant_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("usage_events")
