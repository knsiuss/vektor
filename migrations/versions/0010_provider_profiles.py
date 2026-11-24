"""Multi-provider API profiles per user.

Revision ID: 0010_provider_profiles
Revises: 0009_assistant_status
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_provider_profiles"
down_revision = "0009_assistant_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "provider_profiles" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "provider_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("api_key_encrypted", sa.String(1024), nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_provider_profiles_tenant_user",
        "provider_profiles",
        ["tenant_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_table("provider_profiles")
