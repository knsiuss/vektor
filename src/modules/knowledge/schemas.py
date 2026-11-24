from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Visibility = Literal["private", "tenant", "shared"]


class DocumentIngestInput(BaseModel):
    """Payload for ingesting a raw text or markdown document into Vektor."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=200_000)
    source: str = Field(default="manual", min_length=1, max_length=255)
    visibility: Visibility = "private"
    source_url: str | None = Field(default=None, max_length=512)


class DocumentSummary(BaseModel):
    """Serialized metadata for an ingested knowledge document."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source: str
    embedding_model: str
    chunk_count: int
    created_at: datetime
    owner_id: str = ""
    visibility: str = "private"
    source_url: str | None = None
    last_synced_at: datetime | None = None
    is_stale: bool = False


class VisibilityUpdate(BaseModel):
    """Payload for changing who can see an existing document."""

    model_config = ConfigDict(frozen=True)

    visibility: Literal["private", "tenant"]


class DocumentGrantIn(BaseModel):
    """Payload for sharing a document with one user."""

    model_config = ConfigDict(frozen=True)

    grantee_id: str = Field(min_length=1, max_length=128)


class DocumentGrantOut(BaseModel):
    """Serialized grant entry for a shared document."""

    model_config = ConfigDict(from_attributes=True)

    document_id: str
    grantee_id: str
    permission: str
    created_at: datetime


class KnowledgeSearchInput(BaseModel):
    """Payload for directly querying the hybrid knowledge retriever."""

    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=4, ge=1, le=20)
    min_score: float = Field(default=0.2, ge=0.0, le=1.0)
    document_ids: list[str] | None = None


class RetrievedChunk(BaseModel):
    """Single ranked knowledge segment returned by hybrid retrieval."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    document_title: str
    chunk_index: int
    content: str
    semantic_score: float
    lexical_score: float
    score: float
    # Web pages reuse this shape so citations, grounding checks and the UI share one path.
    kind: Literal["document", "web"] = "document"
    url: str | None = None
    retrieved_at: str | None = None
    # Populated by retrieval merges; optional so older callers keep working.
    section: str | None = None
    updated_at: datetime | None = None
