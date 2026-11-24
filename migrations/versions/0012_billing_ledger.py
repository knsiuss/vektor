"""Platform key pool and double-entry credit ledger tables.

Revision ID: 0012_billing_ledger
Revises: 0011_gateway_vault
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_billing_ledger"
down_revision = "0011_gateway_vault"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "platform_keys" not in existing:
        op.create_table(
            "platform_keys",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("label", sa.String(80), nullable=False, server_default="primary"),
            sa.Column("ciphertext", sa.Text, nullable=False),
            sa.Column("wrapped_dek", sa.Text, nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("monthly_limit_micros", sa.BigInteger, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_platform_keys_provider_status", "platform_keys", ["provider", "status"])
    if "credit_ledger" not in existing:
        op.create_table(
            "credit_ledger",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("entry_type", sa.String(24), nullable=False),
            sa.Column("amount_micros", sa.BigInteger, nullable=False),
            sa.Column("ref_id", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_credit_ledger_tenant_created", "credit_ledger", ["tenant_id", "created_at"])
    if "credit_reservations" not in existing:
        op.create_table(
            "credit_reservations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("hold_micros", sa.BigInteger, nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="open"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_credit_reservations_tenant_status",
            "credit_reservations",
            ["tenant_id", "status"],
        )


def downgrade() -> None:
    op.drop_table("credit_reservations")
    op.drop_table("credit_ledger")
    op.drop_table("platform_keys")
