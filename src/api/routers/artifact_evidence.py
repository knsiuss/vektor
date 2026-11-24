import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.artifacts.evidence import truncate_source_snippet
from modules.artifacts.repository import ArtifactRepository
from modules.identity.principal import Principal

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])


class EvidenceOut(BaseModel):
    evidence_id: str
    tool_name: str
    parameters: dict[str, Any]
    source_snippet: str


@router.get("/{artifact_id}/evidence/{evidence_id}", response_model=EvidenceOut)
async def get_artifact_evidence(
    artifact_id: str,
    evidence_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EvidenceOut:
    """Return truncated evidence details for a claim inside an artifact."""
    repo = ArtifactRepository(session)
    artifact = await repo.get_artifact(
        artifact_id=artifact_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")

    ver = await repo.get_version(artifact_id=artifact.id, version=artifact.current_version)
    if ver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")

    source = json.loads(ver.source_json)
    evidence_map = source.get("evidence", {}) if isinstance(source, dict) else {}
    entry = evidence_map.get(evidence_id) if isinstance(evidence_map, dict) else None
    if not isinstance(entry, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found.")

    return EvidenceOut(
        evidence_id=evidence_id,
        tool_name=str(entry.get("tool_name", "unknown")),
        parameters=entry.get("parameters", {}) if isinstance(entry.get("parameters"), dict) else {},
        source_snippet=truncate_source_snippet(str(entry.get("source_snippet", ""))),
    )
