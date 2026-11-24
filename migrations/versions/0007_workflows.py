"""Workflow definitions and execution runs.

Revision ID: 0007_workflows
Revises: 0006_pgvector_fts
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_workflows"
down_revision = "0006_pgvector_fts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "workflows" not in existing:
        op.create_table(
            "workflows",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("owner_id", sa.String(128), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text, nullable=False, server_default=""),
            sa.Column("trigger_type", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("steps_json", sa.Text, nullable=False),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_workflows_tenant_created", "workflows", ["tenant_id", "created_at"])

    if "workflow_runs" not in existing:
        op.create_table(
            "workflow_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "workflow_id",
                sa.String(36),
                sa.ForeignKey("workflows.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("triggered_by", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("current_step_index", sa.Integer, nullable=False, server_default="0"),
            sa.Column("input_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("context_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("step_logs_json", sa.Text, nullable=False, server_default="[]"),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_workflow_runs_tenant_status",
            "workflow_runs",
            ["tenant_id", "status"],
        )


def downgrade() -> None:
    op.drop_table("workflow_runs")
    op.drop_table("workflows")
