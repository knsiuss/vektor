"""Add optional cron_expr column to workflows.

Revision ID: 0008_workflow_cron
Revises: 0007_workflows
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_workflow_cron"
down_revision = "0007_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("workflows")}
    if "cron_expr" not in cols:
        op.add_column("workflows", sa.Column("cron_expr", sa.String(64), nullable=True))


def downgrade() -> None:
    cols = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("workflows")}
    if "cron_expr" in cols:
        op.drop_column("workflows", "cron_expr")
