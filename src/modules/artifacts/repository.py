"""Repository for tenant- and user-scoped Artifact CRUD and versioning."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.artifacts.models import Artifact, ArtifactVersion


class VersionConflictError(Exception):
    """Raised when base_version does not match the artifact's current_version."""


class ArtifactRepository:
    """Manage Artifacts and immutable ArtifactVersions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_artifact(
        self,
        *,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        artifact_type: str,
        title: str,
        source: dict[str, Any],
        created_by: str = "model",
    ) -> tuple[Artifact, ArtifactVersion]:
        artifact = Artifact(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            type=artifact_type,
            title=title.strip()[:256],
            status="ready",
            current_version=1,
        )
        self._session.add(artifact)
        await self._session.flush()

        ver = ArtifactVersion(
            artifact_id=artifact.id,
            version=1,
            source_json=json.dumps(source, ensure_ascii=False),
            created_by=created_by,
        )
        self._session.add(ver)
        await self._session.flush()
        return artifact, ver

    async def get_artifact(
        self,
        *,
        artifact_id: str,
        tenant_id: str,
        user_id: str,
    ) -> Artifact | None:
        stmt = select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.tenant_id == tenant_id,
            Artifact.user_id == user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_versions(self, *, artifact_id: str) -> list[ArtifactVersion]:
        stmt = (
            select(ArtifactVersion)
            .where(ArtifactVersion.artifact_id == artifact_id)
            .order_by(ArtifactVersion.version.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_version(self, *, artifact_id: str, version: int) -> ArtifactVersion | None:
        stmt = select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.version == version,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def append_version(
        self,
        *,
        artifact: Artifact,
        base_version: int,
        source: dict[str, Any],
        created_by: str = "user",
    ) -> ArtifactVersion:
        if artifact.current_version != base_version:
            raise VersionConflictError(
                f"Expected base_version={artifact.current_version}, got {base_version}."
            )
        next_version = artifact.current_version + 1
        artifact.current_version = next_version
        ver = ArtifactVersion(
            artifact_id=artifact.id,
            version=next_version,
            source_json=json.dumps(source, ensure_ascii=False),
            created_by=created_by,
        )
        self._session.add(ver)
        await self._session.flush()
        return ver
