"""Tenant policies, BYOK provider keys, and versioned model registry.

Revision ID: 0011_gateway_vault
Revises: 0010_provider_profiles
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_gateway_vault"
down_revision = "0010_provider_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "tenant_policies" not in existing:
        op.create_table(
            "tenant_policies",
            sa.Column("tenant_id", sa.String(64), primary_key=True),
            sa.Column("key_mode", sa.String(16), nullable=False, server_default="byok"),
            sa.Column("allowed_models_json", sa.Text, nullable=False, server_default="[]"),
            sa.Column("daily_cap_usd", sa.Float, nullable=True),
            sa.Column("fallback_to_credits", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "provider_keys" not in existing:
        op.create_table(
            "provider_keys",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("label", sa.String(80), nullable=False, server_default="Default"),
            sa.Column("ciphertext", sa.Text, nullable=False),
            sa.Column("wrapped_dek", sa.Text, nullable=False),
            sa.Column("last4", sa.String(8), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("base_url", sa.String(512), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_provider_keys_tenant_provider", "provider_keys", ["tenant_id", "provider"])
        op.create_index("ix_provider_keys_tenant_fp", "provider_keys", ["tenant_id", "fingerprint"])
    if "model_registry" not in existing:
        op.create_table(
            "model_registry",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("tier", sa.String(24), nullable=False, server_default="standard"),
            sa.Column("context_window", sa.Integer, nullable=False, server_default="128000"),
            sa.Column("caps_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("price_in_micros", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("price_out_micros", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("price_cache_write_micros", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("price_cache_read_micros", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="verified"),
            sa.Column("eval_score", sa.Float, nullable=True),
            sa.Column("eval_date", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("model_registry")
    op.drop_table("provider_keys")
    op.drop_table("tenant_policies")
