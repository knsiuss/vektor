"""Multi-tenant: tenant/owner on conversations, api_keys and audit_logs tables.

Existing conversations are backfilled to tenant 'default' and owner 'legacy'. They are then
visible only to a tenant admin (audited) until reassigned.

Revision ID: 0002_multi_tenant
Revises: 0001_baseline
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_multi_tenant"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_INDEX = "ix_conversations_tenant_owner_updated"


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    columns = {col["name"] for col in _inspector().get_columns("conversations")}
    if "tenant_id" not in columns:
        with op.batch_alter_table("conversations") as batch:
            batch.add_column(sa.Column("tenant_id", sa.String(64), nullable=True))
            batch.add_column(sa.Column("owner_id", sa.String(128), nullable=True))
        op.execute(
            "UPDATE conversations SET tenant_id = 'default', owner_id = 'legacy' "
            "WHERE tenant_id IS NULL"
        )
        with op.batch_alter_table("conversations") as batch:
            batch.alter_column("tenant_id", existing_type=sa.String(64), nullable=False)
            batch.alter_column("owner_id", existing_type=sa.String(128), nullable=False)

    if _INDEX not in {idx["name"] for idx in _inspector().get_indexes("conversations")}:
        op.create_index(_INDEX, "conversations", ["tenant_id", "owner_id", "updated_at"])

    tables = set(_inspector().get_table_names())
    if "api_keys" not in tables:
        op.create_table(
            "api_keys",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.String(128), nullable=False),
            sa.Column("key_hash", sa.String(64), nullable=False),
            sa.Column("roles", sa.String(128), nullable=False),
            sa.Column("label", sa.String(128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
        op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    if "audit_logs" not in tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("actor_id", sa.String(128), nullable=False),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("resource_id", sa.String(64), nullable=True),
            sa.Column("resource_owner_id", sa.String(128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
        op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("api_keys")
    op.drop_index(_INDEX, table_name="conversations")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("owner_id")
        batch.drop_column("tenant_id")
