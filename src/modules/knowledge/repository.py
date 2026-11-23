import hashlib
import json
import math
import re
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.knowledge.chunker import chunk_text
from modules.knowledge.models import KnowledgeChunk, KnowledgeDocument
from modules.knowledge.schemas import DocumentSummary, RetrievedChunk
from modules.model_gateway.embeddings import EmbeddingProvider

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_SEMANTIC_WEIGHT = 0.75
_LEXICAL_WEIGHT = 0.25


class DuplicateDocumentError(Exception):
    """Raised when a document with identical content already exists."""

    def __init__(self, existing_id: str, title: str) -> None:
        super().__init__(f"Document '{title}' already exists with id '{existing_id}'.")
        self.existing_id = existing_id


class KnowledgeRepository:
    """Async repository for ingesting documents and executing hybrid vector retrieval."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._session = session
        self._embeddings = embedding_provider

    async def ingest_document(
        self,
        *,
        title: str,
        content: str,
        source: str = "manual",
    ) -> DocumentSummary:
        """Chunk, embed, and persist a document with SHA-256 deduplication."""
        clean_title = title.strip()[:255] or "Untitled Document"
        normalized_content = content.strip()
        content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()

        existing = await self._find_by_hash(content_hash)
        if existing is not None:
            raise DuplicateDocumentError(existing_id=existing.id, title=existing.title)

        segments = chunk_text(normalized_content, document_title=clean_title)
        vectors = await self._embeddings.embed_texts(segments)

        document = KnowledgeDocument(
            title=clean_title,
            source=source.strip()[:255] or "manual",
            content_hash=content_hash,
            embedding_model=self._embeddings.embedding_model,
            chunks=[],
        )
        self._session.add(document)
        await self._session.flush()

        for idx, (segment, vector) in enumerate(zip(segments, vectors, strict=True)):
            chunk = KnowledgeChunk(
                document_id=document.id,
                chunk_index=idx,
                content=segment,
                embedding_json=json.dumps(vector),
            )
            self._session.add(chunk)

        await self._session.flush()
        return DocumentSummary(
            id=document.id,
            title=document.title,
            source=document.source,
            embedding_model=document.embedding_model,
            chunk_count=len(segments),
            created_at=document.created_at,
        )

    async def list_documents(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DocumentSummary]:
        """List ingested documents along with their indexed chunk counts."""
        stmt = (
            select(
                KnowledgeDocument,
                func.count(KnowledgeChunk.id).label("chunk_count"),
            )
            .outerjoin(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .group_by(KnowledgeDocument.id)
            .order_by(KnowledgeDocument.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            DocumentSummary(
                id=doc.id,
                title=doc.title,
                source=doc.source,
                embedding_model=doc.embedding_model,
                chunk_count=int(count),
                created_at=doc.created_at,
            )
            for doc, count in rows
        ]

    async def delete_document(self, document_id: str) -> bool:
        """Delete a knowledge document and cascade-remove its chunks."""
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        doc = (await self._session.execute(stmt)).scalar_one_or_none()
        if doc is None:
            return False
        await self._session.delete(doc)
        await self._session.flush()
        return True

    async def hybrid_search(
        self,
        *,
        query: str,
        top_k: int = 4,
        min_score: float = 0.2,
        document_ids: Sequence[str] | None = None,
    ) -> list[RetrievedChunk]:
        """Rank chunks using a weighted blend of cosine similarity and lexical overlap."""
        clean_query = query.strip()
        if not clean_query:
            return []

        stmt = select(KnowledgeChunk, KnowledgeDocument.title).join(
            KnowledgeDocument,
            KnowledgeDocument.id == KnowledgeChunk.document_id,
        )
        if document_ids:
            stmt = stmt.where(KnowledgeChunk.document_id.in_(list(document_ids)))

        rows = (await self._session.execute(stmt)).all()
        if not rows:
            return []

        query_vectors = await self._embeddings.embed_texts([clean_query])
        query_vector = query_vectors[0]
        query_tokens = set(_TOKEN_RE.findall(clean_query.lower()))

        scored: list[RetrievedChunk] = []
        for chunk, doc_title in rows:
            chunk_vector = _parse_vector(chunk.embedding_json)
            semantic = max(0.0, _cosine_similarity(query_vector, chunk_vector))
            lexical = _lexical_overlap(query_tokens, chunk.content)
            combined = round(
                (_SEMANTIC_WEIGHT * semantic) + (_LEXICAL_WEIGHT * lexical),
                4,
            )
            if combined >= min_score:
                scored.append(
                    RetrievedChunk(
                        document_id=chunk.document_id,
                        document_title=doc_title,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        semantic_score=round(semantic, 4),
                        lexical_score=round(lexical, 4),
                        score=combined,
                    )
                )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]

    async def _find_by_hash(self, content_hash: str) -> KnowledgeDocument | None:
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.content_hash == content_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()


def _parse_vector(raw_json: str) -> list[float]:
    parsed = json.loads(raw_json)
    if not isinstance(parsed, list):
        return []
    return [float(val) for val in parsed]


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    if not vec_a or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _lexical_overlap(query_tokens: set[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    doc_tokens = set(_TOKEN_RE.findall(content.lower()))
    if not doc_tokens:
        return 0.0
    matched = len(query_tokens & doc_tokens)
    return matched / len(query_tokens)
