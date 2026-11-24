"""Baseline: conversations and knowledge tables (skips tables that already exist).

Revision ID: 0001_baseline
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _has(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _has("conversations"):
        op.create_table(
            "conversations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if not _has("conversation_messages"):
        op.create_table(
            "conversation_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "conversation_id",
                sa.String(36),
                sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(32), nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("provider", sa.String(64), nullable=True),
            sa.Column("model", sa.String(128), nullable=True),
            sa.Column("prompt_tokens", sa.Integer, nullable=False),
            sa.Column("completion_tokens", sa.Integer, nullable=False),
            sa.Column("total_tokens", sa.Integer, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_conversation_messages_conversation_id",
            "conversation_messages",
            ["conversation_id"],
        )
        op.create_index(
            "ix_conversation_messages_created_at", "conversation_messages", ["created_at"]
        )
    if not _has("knowledge_documents"):
        op.create_table(
            "knowledge_documents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("source", sa.String(255), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("embedding_model", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_knowledge_documents_content_hash",
            "knowledge_documents",
            ["content_hash"],
            unique=True,
        )
    if not _has("knowledge_chunks"):
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "document_id",
                sa.String(36),
                sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("chunk_index", sa.Integer, nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("embedding_json", sa.Text, nullable=False),
        )
        op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])


def downgrade() -> None:
    for table in (
        "knowledge_chunks",
        "knowledge_documents",
        "conversation_messages",
        "conversations",
    ):
        if _has(table):
            op.drop_table(table)
