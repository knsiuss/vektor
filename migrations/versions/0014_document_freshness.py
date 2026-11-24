"""Document freshness: source_url and last_synced_at.

Revision ID: 0014_document_freshness
Revises: 0013_tenant_budgets
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_document_freshness"
down_revision = "0013_tenant_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("knowledge_documents")
    }
    if "source_url" not in columns:
        with op.batch_alter_table("knowledge_documents") as batch:
            batch.add_column(sa.Column("source_url", sa.String(512), nullable=True))
    if "last_synced_at" not in columns:
        with op.batch_alter_table("knowledge_documents") as batch:
            batch.add_column(
                sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True)
            )
        op.execute(
            "UPDATE knowledge_documents SET last_synced_at = created_at "
            "WHERE last_synced_at IS NULL"
        )
        with op.batch_alter_table("knowledge_documents") as batch:
            batch.alter_column(
                "last_synced_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.drop_column("last_synced_at")
        batch.drop_column("source_url")
