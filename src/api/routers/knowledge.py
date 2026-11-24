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
    get_principal,
    get_settings,
)
from core.config.settings import Settings
from modules.identity.models import AuditLog
from modules.identity.principal import Principal
from modules.knowledge.extractors import DocumentExtractor, UnsupportedDocumentError
from modules.knowledge.repository import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
    DuplicateDocumentError,
    KnowledgeRepository,
)
from modules.knowledge.schemas import (
    DocumentGrantIn,
    DocumentGrantOut,
    DocumentIngestInput,
    DocumentSummary,
    KnowledgeSearchInput,
    RetrievedChunk,
    VisibilityUpdate,
)
from modules.model_gateway.embeddings import EmbeddingProvider
from modules.model_gateway.exceptions import (
    ModelGatewayError,
    ProviderAuthenticationError,
)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])



def _get_knowledge_repo(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> KnowledgeRepository:
    return KnowledgeRepository(
        session=session,
        embedding_provider=embeddings,
        principal=principal,
    )


def _not_found(document_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Knowledge document '{document_id}' was not found.",
    )


def _forbidden(document_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"You may read document '{document_id}' but not change it.",
    )


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
            visibility=payload.visibility,
            source_url=payload.source_url,
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
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str | None, Form()] = None,
) -> DocumentSummary:
    """Upload PDF, DOCX, Markdown, Text, or Image files for extraction and indexing."""
    filename = file.filename or "uploaded_document.txt"
    content_bytes = await file.read()
    limit = settings.max_upload_bytes
    if limit > 0 and len(content_bytes) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the configured limit of {limit // (1024 * 1024)} MB.",
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
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> Response:
    """Remove a document and all of its indexed chunks from the knowledge base."""
    try:
        document = await repo.delete_document(document_id)
    except DocumentNotFoundError as exc:
        raise _not_found(document_id) from exc
    except DocumentAccessDeniedError as exc:
        raise _forbidden(document_id) from exc

    # Deleting someone else's document is privileged access: keep a record of it.
    if document.owner_id != principal.user_id:
        session.add(
            AuditLog(
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                action="knowledge.delete",
                resource_type="knowledge_document",
                resource_id=document.id,
                resource_owner_id=document.owner_id,
            )
        )
        await session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/documents/{document_id}/visibility", response_model=DocumentSummary)
async def update_visibility(
    document_id: str,
    payload: VisibilityUpdate,
    repo: Annotated[KnowledgeRepository, Depends(_get_knowledge_repo)],
) -> DocumentSummary:
    """Switch a managed document between private and tenant-wide visibility."""
    try:
        return await repo.set_visibility(document_id, payload.visibility)
    except DocumentNotFoundError as exc:
        raise _not_found(document_id) from exc
    except DocumentAccessDeniedError as exc:
        raise _forbidden(document_id) from exc


@router.get("/documents/{document_id}/grants", response_model=list[DocumentGrantOut])
async def list_document_grants(
    document_id: str,
    repo: Annotated[KnowledgeRepository, Depends(_get_knowledge_repo)],
) -> list[DocumentGrantOut]:
    """List the users who were granted read access to this document."""
    try:
        grants = await repo.list_grants(document_id)
    except DocumentNotFoundError as exc:
        raise _not_found(document_id) from exc
    except DocumentAccessDeniedError as exc:
        raise _forbidden(document_id) from exc
    return [DocumentGrantOut.model_validate(grant) for grant in grants]


@router.post(
    "/documents/{document_id}/grants",
    response_model=DocumentGrantOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_grant(
    document_id: str,
    payload: DocumentGrantIn,
    repo: Annotated[KnowledgeRepository, Depends(_get_knowledge_repo)],
) -> DocumentGrantOut:
    """Share a document with one user, switching it to shared visibility."""
    try:
        grant = await repo.add_grant(document_id, payload.grantee_id)
    except DocumentNotFoundError as exc:
        raise _not_found(document_id) from exc
    except DocumentAccessDeniedError as exc:
        raise _forbidden(document_id) from exc
    return DocumentGrantOut.model_validate(grant)


@router.delete(
    "/documents/{document_id}/grants/{grantee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document_grant(
    document_id: str,
    grantee_id: str,
    repo: Annotated[KnowledgeRepository, Depends(_get_knowledge_repo)],
) -> Response:
    """Revoke one user's access to a shared document."""
    try:
        await repo.remove_grant(document_id, grantee_id)
    except DocumentNotFoundError as exc:
        raise _not_found(grantee_id) from exc
    except DocumentAccessDeniedError as exc:
        raise _forbidden(document_id) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/documents/{document_id}/reindex", response_model=DocumentSummary)
async def reindex_document(
    document_id: str,
    repo: Annotated[KnowledgeRepository, Depends(_get_knowledge_repo)],
) -> DocumentSummary:
    """Re-embed a document's stored chunks and refresh its freshness timestamp."""
    try:
        return await repo.reindex_document(document_id)
    except DocumentNotFoundError as exc:
        raise _not_found(document_id) from exc
    except DocumentAccessDeniedError as exc:
        raise _forbidden(document_id) from exc
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
