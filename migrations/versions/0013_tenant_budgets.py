"""Tenant-wide monthly token budget.

Revision ID: 0013_tenant_budgets
Revises: 0012_billing_ledger
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_tenant_budgets"
down_revision = "0012_billing_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "tenant_budgets" in tables:
        return
    op.create_table(
        "tenant_budgets",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("monthly_token_limit", sa.Integer(), nullable=False),
        sa.Column("warn_ratio", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tenant_budgets")
