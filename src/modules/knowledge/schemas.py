from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentIngestInput(BaseModel):
    """Payload for ingesting a raw text or markdown document into Vektor."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=200_000)
    source: str = Field(default="manual", min_length=1, max_length=255)


class DocumentSummary(BaseModel):
    """Serialized metadata for an ingested knowledge document."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source: str
    embedding_model: str
    chunk_count: int
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
