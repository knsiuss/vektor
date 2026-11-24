"""PostgreSQL pgvector and tsvector full-text search columns.

Revision ID: 0006_pgvector_fts
Revises: 0005_provider_settings
"""
from alembic import op

revision = "0006_pgvector_fts"
down_revision = "0005_provider_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector")
    op.execute(
        "ALTER TABLE knowledge_chunks "
        "ADD COLUMN IF NOT EXISTS search_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_search_tsv "
        "ON knowledge_chunks USING GIN (search_tsv)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_search_tsv")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS search_tsv")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding_vec")
