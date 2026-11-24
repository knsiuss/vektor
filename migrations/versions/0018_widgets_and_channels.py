"""Add public chat widgets and omnichannel bot connector tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_widgets_and_channels"
down_revision: str | None = "43d9721ac8ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_widgets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("public_key", sa.String(length=64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("allowed_domains", sa.JSON(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("welcome_message", sa.String(length=500), nullable=False),
        sa.Column("theme", sa.JSON(), nullable=False),
        sa.Column("knowledge_scope", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "widget_visitor_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "widget_id",
            sa.String(length=36),
            sa.ForeignKey("chat_widgets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("visitor_token_hash", sa.String(length=64), nullable=False, index=True),
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "channel_connectors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("channel_type", sa.String(length=32), nullable=False, index=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("webhook_secret", sa.String(length=64), nullable=False, index=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("auto_handover_threshold", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("knowledge_scope", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "channel_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "connector_id",
            sa.String(length=36),
            sa.ForeignKey("channel_connectors.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("external_user_id", sa.String(length=128), nullable=False, index=True),
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("handover_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("unknown_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("channel_sessions")
    op.drop_table("channel_connectors")
    op.drop_table("widget_visitor_sessions")
    op.drop_table("chat_widgets")
