from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    get_db_session,
    get_document_extractor,
    get_embedding_provider,
)
from modules.knowledge.extractors import DocumentExtractor, UnsupportedDocumentError
from modules.knowledge.repository import DuplicateDocumentError, KnowledgeRepository
from modules.knowledge.schemas import (
    DocumentIngestInput,
    DocumentSummary,
    KnowledgeSearchInput,
    RetrievedChunk,
)
from modules.model_gateway.embeddings import EmbeddingProvider
from modules.model_gateway.exceptions import (
    ModelGatewayError,
    ProviderAuthenticationError,
)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

_MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB guard


def _get_knowledge_repo(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> KnowledgeRepository:
    return KnowledgeRepository(session=session, embedding_provider=embeddings)


@router.post(
    "/documents",
    response_model=DocumentSummary,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_text_document(
    payload: DocumentIngestInput,
    repo: Annotated[KnowledgeRepository, Depends(_get_knowledge_repo)],
) -> DocumentSummary:
    """Ingest raw text or Markdown content into the hybrid vector knowledge base."""
    try:
        return await repo.ingest_document(
            title=payload.title,
            content=payload.content,
            source=payload.source,
        )
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding provider authentication is not configured.",
        ) from exc
    except ModelGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream embedding provider failed.",
        ) from exc


@router.post(
    "/documents/upload",
    response_model=DocumentSummary,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_file(
    repo: Annotated[KnowledgeRepository, Depends(_get_knowledge_repo)],
    extractor: Annotated[DocumentExtractor, Depends(get_document_extractor)],
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str | None, Form()] = None,
) -> DocumentSummary:
    """Upload PDF, DOCX, Markdown, Text, or Image files for extraction and indexing."""
    filename = file.filename or "uploaded_document.txt"
    content_bytes = await file.read()
    if len(content_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds maximum allowed size of 15 MB.",
        )

    try:
        extracted_text = await extractor.extract(
            filename=filename,
            content_bytes=content_bytes,
        )
        resolved_title = (title or Path(filename).stem).strip() or filename
        return await repo.ingest_document(
            title=resolved_title,
            content=extracted_text,
            source=filename,
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding provider authentication is not configured.",
        ) from exc
    except ModelGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream embedding provider failed.",
        ) from exc


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(
    repo: Annotated[KnowledgeRepository, Depends(_get_knowledge_repo)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentSummary]:
    """List ingested documents in the knowledge base."""
    return await repo.list_documents(limit=limit, offset=offset)


@router.post("/search", response_model=list[RetrievedChunk])
async def search_knowledge(
    payload: KnowledgeSearchInput,
    repo: Annotated[KnowledgeRepository, Depends(_get_knowledge_repo)],
) -> list[RetrievedChunk]:
    """Execute a hybrid semantic + lexical search against indexed knowledge chunks."""
    try:
        return await repo.hybrid_search(
            query=payload.query,
            top_k=payload.top_k,
            min_score=payload.min_score,
            document_ids=payload.document_ids,
        )
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding provider authentication is not configured.",
        ) from exc
    except ModelGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream embedding provider failed.",
        ) from exc


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    repo: Annotated[KnowledgeRepository, Depends(_get_knowledge_repo)],
) -> Response:
    """Remove a document and all of its indexed chunks from the knowledge base."""
    deleted = await repo.delete_document(document_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge document '{document_id}' was not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
