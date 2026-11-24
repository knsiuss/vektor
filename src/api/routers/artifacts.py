"""API endpoints for versioned Artifacts (metadata, versions, edit, restore)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.artifacts.exporter import export_artifact_ir, sanitize_filename
from modules.artifacts.patcher import InvalidPatchError, apply_ir_patch
from modules.artifacts.repository import ArtifactRepository, VersionConflictError
from modules.identity.principal import Principal

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])


class ArtifactVersionOut(BaseModel):
    version: int
    source: dict[str, Any]
    created_by: str
    created_at: datetime


class ArtifactOut(BaseModel):
    id: str
    conversation_id: str
    type: str
    title: str
    status: str
    current_version: int
    source: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ArtifactEditIn(BaseModel):
    base_version: int = Field(..., ge=1)
    source: dict[str, Any]


class ArtifactRestoreIn(BaseModel):
    version: int = Field(..., ge=1)


class ArtifactPatchIn(BaseModel):
    base_version: int = Field(..., ge=1)
    patch: dict[str, Any]


@router.get("/{artifact_id}", response_model=ArtifactOut)
async def get_artifact(
    artifact_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ArtifactOut:
    repo = ArtifactRepository(session)
    artifact = await repo.get_artifact(
        artifact_id=artifact_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
    ver = await repo.get_version(artifact_id=artifact.id, version=artifact.current_version)
    return ArtifactOut(
        id=artifact.id,
        conversation_id=artifact.conversation_id,
        type=artifact.type,
        title=artifact.title,
        status=artifact.status,
        current_version=artifact.current_version,
        source=json.loads(ver.source_json) if ver else None,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
    )


@router.get("/{artifact_id}/versions", response_model=list[ArtifactVersionOut])
async def list_artifact_versions(
    artifact_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ArtifactVersionOut]:
    repo = ArtifactRepository(session)
    artifact = await repo.get_artifact(
        artifact_id=artifact_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
    versions = await repo.list_versions(artifact_id=artifact.id)
    return [
        ArtifactVersionOut(
            version=v.version,
            source=json.loads(v.source_json),
            created_by=v.created_by,
            created_at=v.created_at,
        )
        for v in versions
    ]


@router.post("/{artifact_id}/edit", response_model=ArtifactVersionOut)
async def edit_artifact(
    artifact_id: str,
    payload: ArtifactEditIn,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ArtifactVersionOut:
    repo = ArtifactRepository(session)
    artifact = await repo.get_artifact(
        artifact_id=artifact_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
    try:
        ver = await repo.append_version(
            artifact=artifact,
            base_version=payload.base_version,
            source=payload.source,
            created_by="user",
        )
    except VersionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    return ArtifactVersionOut(
        version=ver.version,
        source=json.loads(ver.source_json),
        created_by=ver.created_by,
        created_at=ver.created_at,
    )


@router.post("/{artifact_id}/patch", response_model=ArtifactVersionOut)
async def patch_artifact(
    artifact_id: str,
    payload: ArtifactPatchIn,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ArtifactVersionOut:
    repo = ArtifactRepository(session)
    artifact = await repo.get_artifact(
        artifact_id=artifact_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
    current_ver = await repo.get_version(artifact_id=artifact.id, version=artifact.current_version)
    if current_ver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")
    try:
        patched = apply_ir_patch(json.loads(current_ver.source_json), payload.patch)
        ver = await repo.append_version(
            artifact=artifact,
            base_version=payload.base_version,
            source=patched,
            created_by="model",
        )
    except InvalidPatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except VersionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    return ArtifactVersionOut(
        version=ver.version,
        source=json.loads(ver.source_json),
        created_by=ver.created_by,
        created_at=ver.created_at,
    )


@router.get("/{artifact_id}/versions/{version}/export")
async def export_artifact_version(
    artifact_id: str,
    version: int,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    fmt: str = Query("md", alias="format"),
) -> Response:
    repo = ArtifactRepository(session)
    artifact = await repo.get_artifact(
        artifact_id=artifact_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
    ver = await repo.get_version(artifact_id=artifact.id, version=version)
    if ver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")
    try:
        content, media_type, ext = export_artifact_ir(
            artifact_type=artifact.type,
            title=artifact.title,
            source=json.loads(ver.source_json),
            fmt=fmt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    filename = sanitize_filename(artifact.title, version, ext)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{artifact_id}/restore", response_model=ArtifactVersionOut)
async def restore_artifact_version(
    artifact_id: str,
    payload: ArtifactRestoreIn,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ArtifactVersionOut:
    repo = ArtifactRepository(session)
    artifact = await repo.get_artifact(
        artifact_id=artifact_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
    target = await repo.get_version(artifact_id=artifact.id, version=payload.version)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")
    ver = await repo.append_version(
        artifact=artifact,
        base_version=artifact.current_version,
        source=json.loads(target.source_json),
        created_by="user",
    )
    await session.commit()
    return ArtifactVersionOut(
        version=ver.version,
        source=json.loads(ver.source_json),
        created_by=ver.created_by,
        created_at=ver.created_at,
    )

