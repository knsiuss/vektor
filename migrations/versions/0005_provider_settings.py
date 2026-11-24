"""Per-user AI provider settings.

Revision ID: 0005_provider_settings
Revises: 0004_usage_events
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_provider_settings"
down_revision = "0004_usage_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "provider_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "provider_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="openai"),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("api_key_hash", sa.String(64), nullable=True),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("connection_status", sa.String(16), nullable=False, server_default="disconnected"),
        sa.Column("connection_error", sa.String(512), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_provider_settings_tenant_user",
        "provider_settings",
        ["tenant_id", "user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("provider_settings")
