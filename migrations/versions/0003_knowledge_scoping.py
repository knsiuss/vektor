"""Knowledge scoping: tenant/owner/visibility on documents, tenant on chunks, grants table.

Existing documents are backfilled to tenant 'default', owner 'legacy', visibility 'tenant' so
they stay searchable for everyone in the default tenant. The global unique index on
content_hash becomes unique per tenant.

Revision ID: 0003_knowledge_scoping
Revises: 0002_multi_tenant
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_knowledge_scoping"
down_revision = "0002_multi_tenant"
branch_labels = None
depends_on = None

_HASH_IDX = "ix_knowledge_documents_content_hash"
_UQ = "uq_knowledge_documents_tenant_hash"
_VIS_IDX = "ix_knowledge_documents_tenant_visibility"


def _insp() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    doc_cols = {c["name"] for c in _insp().get_columns("knowledge_documents")}
    if "tenant_id" not in doc_cols:
        with op.batch_alter_table("knowledge_documents") as batch:
            batch.add_column(sa.Column("tenant_id", sa.String(64), nullable=True))
            batch.add_column(sa.Column("owner_id", sa.String(128), nullable=True))
            batch.add_column(sa.Column("visibility", sa.String(16), nullable=True))
        op.execute(
            "UPDATE knowledge_documents SET tenant_id = 'default', owner_id = 'legacy', "
            "visibility = 'tenant' WHERE tenant_id IS NULL"
        )
        with op.batch_alter_table("knowledge_documents") as batch:
            batch.alter_column("tenant_id", existing_type=sa.String(64), nullable=False)
            batch.alter_column("owner_id", existing_type=sa.String(128), nullable=False)
            batch.alter_column("visibility", existing_type=sa.String(16), nullable=False)

    hash_idx = {i["name"]: i for i in _insp().get_indexes("knowledge_documents")}
    if _HASH_IDX in hash_idx and hash_idx[_HASH_IDX].get("unique"):
        op.drop_index(_HASH_IDX, table_name="knowledge_documents")
        op.create_index(_HASH_IDX, "knowledge_documents", ["content_hash"], unique=False)

    uniques = {u["name"] for u in _insp().get_unique_constraints("knowledge_documents")}
    unique_idx = {
        i["name"] for i in _insp().get_indexes("knowledge_documents") if i.get("unique")
    }
    if _UQ not in uniques and _UQ not in unique_idx:
        with op.batch_alter_table("knowledge_documents") as batch:
            batch.create_unique_constraint(_UQ, ["tenant_id", "content_hash"])

    if _VIS_IDX not in {i["name"] for i in _insp().get_indexes("knowledge_documents")}:
        op.create_index(_VIS_IDX, "knowledge_documents", ["tenant_id", "visibility"])

    chunk_cols = {c["name"] for c in _insp().get_columns("knowledge_chunks")}
    if "tenant_id" not in chunk_cols:
        with op.batch_alter_table("knowledge_chunks") as batch:
            batch.add_column(sa.Column("tenant_id", sa.String(64), nullable=True))
        op.execute(
            "UPDATE knowledge_chunks SET tenant_id = COALESCE("
            "(SELECT d.tenant_id FROM knowledge_documents d "
            "WHERE d.id = knowledge_chunks.document_id), 'default') WHERE tenant_id IS NULL"
        )
        with op.batch_alter_table("knowledge_chunks") as batch:
            batch.alter_column("tenant_id", existing_type=sa.String(64), nullable=False)
        op.create_index("ix_knowledge_chunks_tenant_id", "knowledge_chunks", ["tenant_id"])

    if "document_grants" not in set(_insp().get_table_names()):
        op.create_table(
            "document_grants",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "document_id",
                sa.String(36),
                sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("grantee_id", sa.String(128), nullable=False),
            sa.Column("permission", sa.String(16), nullable=False),
            sa.Column("created_by", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("document_id", "grantee_id", name="uq_document_grants_doc_grantee"),
        )
        op.create_index("ix_document_grants_document_id", "document_grants", ["document_id"])
        op.create_index("ix_document_grants_grantee_id", "document_grants", ["grantee_id"])


def downgrade() -> None:
    op.drop_table("document_grants")
    op.drop_index("ix_knowledge_chunks_tenant_id", table_name="knowledge_chunks")
    with op.batch_alter_table("knowledge_chunks") as batch:
        batch.drop_column("tenant_id")
    op.drop_index(_VIS_IDX, table_name="knowledge_documents")
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.drop_constraint(_UQ, type_="unique")
        batch.drop_column("visibility")
        batch.drop_column("owner_id")
        batch.drop_column("tenant_id")
    op.drop_index(_HASH_IDX, table_name="knowledge_documents")
    op.create_index(_HASH_IDX, "knowledge_documents", ["content_hash"], unique=True)
