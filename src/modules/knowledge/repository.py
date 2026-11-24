import hashlib
import json
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, bindparam, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from core.config.settings import get_settings
from modules.identity.principal import DEV_PRINCIPAL, Principal
from modules.knowledge.chunker import chunk_text, semantic_chunk_text
from modules.knowledge.models import DocumentGrant, KnowledgeChunk, KnowledgeDocument
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


class DocumentNotFoundError(Exception):
    """Raised when a document does not exist or is not visible to the caller."""


class DocumentAccessDeniedError(Exception):
    """Raised when the caller can read a document but may not change it."""


class KnowledgeRepository:
    """Async repository for ingesting documents and executing hybrid vector retrieval."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        principal: Principal | None = None,
    ) -> None:
        # A missing principal still scopes to the local development tenant; it never
        # means "no scoping", so a forgotten call site cannot expose every document.
        self._session = session
        self._embeddings = embedding_provider
        self._principal = principal or DEV_PRINCIPAL

    def _visible_filter(self) -> ColumnElement[bool]:
        """Documents the caller may read: own, tenant-wide, or explicitly granted."""
        principal = self._principal
        granted = (
            select(DocumentGrant.id)
            .where(
                DocumentGrant.document_id == KnowledgeDocument.id,
                DocumentGrant.grantee_id == principal.user_id,
            )
            .exists()
        )
        return and_(
            KnowledgeDocument.tenant_id == principal.tenant_id,
            or_(
                KnowledgeDocument.owner_id == principal.user_id,
                KnowledgeDocument.visibility == "tenant",
                and_(KnowledgeDocument.visibility == "shared", granted),
            ),
        )

    def _can_manage(self, document: KnowledgeDocument) -> bool:
        """Owners and tenant admins may change sharing and delete a document."""
        if document.tenant_id != self._principal.tenant_id:
            return False
        return document.owner_id == self._principal.user_id or self._principal.is_admin

    async def ingest_document(
        self,
        *,
        title: str,
        content: str,
        source: str = "manual",
        visibility: str = "private",
        source_url: str | None = None,
    ) -> DocumentSummary:
        """Chunk, embed, and persist a document with per-tenant SHA-256 deduplication."""
        clean_title = title.strip()[:255] or "Untitled Document"
        normalized_content = content.strip()
        content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
        principal = self._principal

        existing = await self._find_by_hash(content_hash)
        if existing is not None:
            raise DuplicateDocumentError(existing_id=existing.id, title=existing.title)

        if get_settings().knowledge_chunking_strategy == "semantic":
            segments = await semantic_chunk_text(
                normalized_content,
                embed_fn=self._embeddings.embed_texts,
                document_title=clean_title,
            )
        else:
            segments = chunk_text(normalized_content, document_title=clean_title)
        vectors = await self._embeddings.embed_texts(segments)

        document = KnowledgeDocument(
            title=clean_title,
            source=source.strip()[:255] or "manual",
            content_hash=content_hash,
            embedding_model=self._embeddings.embedding_model,
            tenant_id=principal.tenant_id,
            owner_id=principal.user_id,
            visibility=visibility,
            source_url=source_url,
            last_synced_at=datetime.now(UTC),
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
                tenant_id=principal.tenant_id,
            )
            self._session.add(chunk)

        await self._session.flush()
        if self._is_postgres() and vectors:
            await self._sync_pgvectors(document.id, vectors)
        return DocumentSummary(
            id=document.id,
            title=document.title,
            source=document.source,
            embedding_model=document.embedding_model,
            chunk_count=len(segments),
            created_at=document.created_at,
            owner_id=document.owner_id,
            visibility=document.visibility,
            source_url=document.source_url,
            last_synced_at=document.last_synced_at,
            is_stale=False,
        )

    async def list_documents(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DocumentSummary]:
        """List documents the caller may read, with their indexed chunk counts."""
        stmt = (
            select(
                KnowledgeDocument,
                func.count(KnowledgeChunk.id).label("chunk_count"),
            )
            .outerjoin(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(self._visible_filter())
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
                owner_id=doc.owner_id,
                visibility=doc.visibility,
                source_url=doc.source_url,
                last_synced_at=doc.last_synced_at,
                is_stale=self._is_stale(doc),
            )
            for doc, count in rows
        ]

    async def get_document(self, document_id: str) -> KnowledgeDocument:
        """Return a visible document, or raise when it does not exist for this caller."""
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            self._visible_filter(),
        )
        document = (await self._session.execute(stmt)).scalar_one_or_none()
        if document is None:
            raise DocumentNotFoundError(document_id)
        return document

    def _is_stale(self, document: KnowledgeDocument) -> bool:
        """True when the document has not been re-indexed within the freshness window."""
        synced = document.last_synced_at or document.created_at
        if synced.tzinfo is None:
            synced = synced.replace(tzinfo=UTC)
        return (datetime.now(UTC) - synced).days > get_settings().retrieval_stale_days

    async def reindex_document(self, document_id: str) -> DocumentSummary:
        """Re-embed the stored chunks, for example after switching embedding models."""
        document = await self.get_document(document_id)
        if not self._can_manage(document):
            raise DocumentAccessDeniedError(document_id)

        stmt = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document.id)
            .order_by(KnowledgeChunk.chunk_index)
        )
        chunks = list((await self._session.execute(stmt)).scalars().all())
        if not chunks:
            raise DocumentNotFoundError(document_id)

        vectors = await self._embeddings.embed_texts([chunk.content for chunk in chunks])
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding_json = json.dumps(vector)
        document.embedding_model = self._embeddings.embedding_model
        document.last_synced_at = datetime.now(UTC)
        await self._session.flush()

        if self._is_postgres():
            await self._sync_pgvectors(document.id, vectors)
        return await self._summary_for(document)

    async def delete_document(self, document_id: str) -> KnowledgeDocument:
        """Delete a document the caller manages and return it so callers can audit."""
        document = await self.get_document(document_id)
        if not self._can_manage(document):
            raise DocumentAccessDeniedError(document_id)
        await self._session.delete(document)
        await self._session.flush()
        return document

    async def set_visibility(self, document_id: str, visibility: str) -> DocumentSummary:
        """Change who can read a document the caller manages."""
        document = await self.get_document(document_id)
        if not self._can_manage(document):
            raise DocumentAccessDeniedError(document_id)
        document.visibility = visibility
        await self._session.flush()
        return await self._summary_for(document)

    async def add_grant(self, document_id: str, grantee_id: str) -> DocumentGrant:
        """Share a document with one user and switch it to shared visibility."""
        document = await self.get_document(document_id)
        if not self._can_manage(document):
            raise DocumentAccessDeniedError(document_id)

        existing = (
            await self._session.execute(
                select(DocumentGrant).where(
                    DocumentGrant.document_id == document_id,
                    DocumentGrant.grantee_id == grantee_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        grant = DocumentGrant(
            document_id=document.id,
            tenant_id=document.tenant_id,
            grantee_id=grantee_id,
            permission="read",
            created_by=self._principal.user_id,
        )
        self._session.add(grant)
        document.visibility = "shared"
        await self._session.flush()
        return grant

    async def list_grants(self, document_id: str) -> list[DocumentGrant]:
        """List the people a document is shared with."""
        document = await self.get_document(document_id)
        if not self._can_manage(document):
            raise DocumentAccessDeniedError(document_id)
        rows = await self._session.execute(
            select(DocumentGrant)
            .where(DocumentGrant.document_id == document_id)
            .order_by(DocumentGrant.created_at)
        )
        return list(rows.scalars().all())

    async def remove_grant(self, document_id: str, grantee_id: str) -> None:
        """Revoke one user's access, raising when no such grant exists."""
        document = await self.get_document(document_id)
        if not self._can_manage(document):
            raise DocumentAccessDeniedError(document_id)
        grant = (
            await self._session.execute(
                select(DocumentGrant).where(
                    DocumentGrant.document_id == document_id,
                    DocumentGrant.grantee_id == grantee_id,
                )
            )
        ).scalar_one_or_none()
        if grant is None:
            raise DocumentNotFoundError(grantee_id)
        await self._session.delete(grant)
        await self._session.flush()

    async def hybrid_search(
        self,
        *,
        query: str,
        top_k: int = 4,
        min_score: float = 0.2,
        document_ids: Sequence[str] | None = None,
        service: str | None = None,
        environment: str | None = None,
        doc_type: str | None = None,
    ) -> list[RetrievedChunk]:
        """Rank chunks using a weighted blend of cosine similarity and lexical overlap.

        The service/environment/doc_type filters are accepted for callers that pass
        retrieval hints, but documents carry no metadata columns yet, so they do not
        narrow the result set today.
        """
        _ = (service, environment, doc_type)
        clean_query = query.strip()
        if not clean_query:
            return []

        query_vector = await self._embed_query(clean_query)
        if self._is_postgres():
            return await self._postgres_hybrid_search(
                query=clean_query,
                query_vector=query_vector,
                top_k=top_k,
                min_score=min_score,
                document_ids=document_ids,
            )

        stmt = select(KnowledgeChunk, KnowledgeDocument.title).join(
            KnowledgeDocument,
            KnowledgeDocument.id == KnowledgeChunk.document_id,
        ).where(self._visible_filter())
        if document_ids:
            stmt = stmt.where(KnowledgeChunk.document_id.in_(list(document_ids)))

        rows = (await self._session.execute(stmt)).all()
        if not rows:
            return []

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
        """Dedupe within the tenant: identical content is allowed in another tenant."""
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.content_hash == content_hash,
            KnowledgeDocument.tenant_id == self._principal.tenant_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _summary_for(self, document: KnowledgeDocument) -> DocumentSummary:
        chunk_count = (
            await self._session.execute(
                select(func.count(KnowledgeChunk.id)).where(
                    KnowledgeChunk.document_id == document.id
                )
            )
        ).scalar_one()
        return DocumentSummary(
            id=document.id,
            title=document.title,
            source=document.source,
            embedding_model=document.embedding_model,
            chunk_count=int(chunk_count),
            created_at=document.created_at,
            owner_id=document.owner_id,
            visibility=document.visibility,
            source_url=document.source_url,
            last_synced_at=document.last_synced_at,
            is_stale=self._is_stale(document),
        )

    def _is_postgres(self) -> bool:
        bind = self._session.get_bind()
        return bind is not None and bind.dialect.name == "postgresql"

    async def _embed_query(self, query: str) -> list[float]:
        embed_query_fn = getattr(self._embeddings, "embed_query", None)
        if callable(embed_query_fn):
            vec: list[float] = await embed_query_fn(query)
            return vec
        vectors = await self._embeddings.embed_texts([query])
        return vectors[0]

    async def _sync_pgvectors(self, document_id: str, vectors: list[list[float]]) -> None:
        stmt = text(
            "UPDATE knowledge_chunks "
            "SET embedding_vec = CAST(:vec AS vector) "
            "WHERE document_id = :doc_id AND chunk_index = :idx"
        )
        for idx, vector in enumerate(vectors):
            vec_literal = "[" + ",".join(f"{v:.8f}" for v in vector) + "]"
            await self._session.execute(
                stmt,
                {"vec": vec_literal, "doc_id": document_id, "idx": idx},
            )

    async def _postgres_hybrid_search(
        self,
        *,
        query: str,
        query_vector: list[float],
        top_k: int,
        min_score: float,
        document_ids: Sequence[str] | None,
    ) -> list[RetrievedChunk]:
        vec_literal = "[" + ",".join(f"{v:.8f}" for v in query_vector) + "]"
        dims = len(query_vector)
        doc_filter = "AND c.document_id IN :doc_ids" if document_ids else ""
        scope_filter = (
            "AND d.tenant_id = :tenant_id "
            "AND (d.owner_id = :user_id OR d.visibility = 'tenant' "
            "OR (d.visibility = 'shared' AND EXISTS ("
            "SELECT 1 FROM document_grants g "
            "WHERE g.document_id = d.id AND g.grantee_id = :user_id)))"
        )
        sql = text(
            f"""
            WITH scored AS (
                SELECT
                    c.document_id,
                    d.title AS document_title,
                    c.chunk_index,
                    c.content,
                    CASE
                        WHEN c.embedding_vec IS NOT NULL AND vector_dims(c.embedding_vec) = :dims
                        THEN GREATEST(0.0, 1.0 - (c.embedding_vec <=> CAST(:q_vec AS vector)))
                        ELSE 0.0
                    END AS semantic_score,
                    LEAST(
                        1.0,
                        COALESCE(ts_rank_cd(c.search_tsv, plainto_tsquery('simple', :query)), 0.0)
                    ) AS lexical_score
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE 1=1 {scope_filter} {doc_filter}
            )
            SELECT
                document_id,
                document_title,
                chunk_index,
                content,
                semantic_score,
                lexical_score,
                ROUND((:sem_w * semantic_score + :lex_w * lexical_score)::numeric, 4) AS score
            FROM scored
            WHERE (:sem_w * semantic_score + :lex_w * lexical_score) >= :min_score
            ORDER BY score DESC
            LIMIT :top_k
            """
        )
        params: dict[str, object] = {
            "q_vec": vec_literal,
            "dims": dims,
            "query": query,
            "sem_w": _SEMANTIC_WEIGHT,
            "lex_w": _LEXICAL_WEIGHT,
            "min_score": min_score,
            "top_k": top_k,
            "tenant_id": self._principal.tenant_id,
            "user_id": self._principal.user_id,
        }
        if document_ids:
            sql = sql.bindparams(bindparam("doc_ids", expanding=True))
            params["doc_ids"] = list(document_ids)

        rows = (await self._session.execute(sql, params)).mappings().all()
        return [
            RetrievedChunk(
                document_id=str(row["document_id"]),
                document_title=str(row["document_title"]),
                chunk_index=int(row["chunk_index"]),
                content=str(row["content"]),
                semantic_score=round(float(row["semantic_score"]), 4),
                lexical_score=round(float(row["lexical_score"]), 4),
                score=float(row["score"]),
            )
            for row in rows
        ]


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
