"""Editable Markdown prompt templates (persona and future agent prompts)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_principal
from modules.identity.principal import Principal
from modules.prompts.defaults import AVAILABLE, default_content
from modules.prompts.repository import PromptRepository

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])

MAX_PROMPT_CHARS = 20_000


class PromptOut(BaseModel):
    """One template with the effective content for this user."""

    key: str
    label: str
    description: str
    default_content: str
    content: str
    is_custom: bool


class PromptIn(BaseModel):
    """Replacement Markdown for one template."""

    content: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)


def _repo(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> PromptRepository:
    return PromptRepository(session, tenant_id=principal.tenant_id, user_id=principal.user_id)


def _spec(key: str):
    spec = AVAILABLE.get(key)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown prompt.")
    return spec


@router.get("", response_model=list[PromptOut])
async def list_prompts(repo: Annotated[PromptRepository, Depends(_repo)]) -> list[PromptOut]:
    """Every editable template, showing the user's override when one exists."""
    overrides = await repo.list_overrides()
    return [
        PromptOut(
            key=spec.key,
            label=spec.label,
            description=spec.description,
            default_content=default_content(spec.key),
            content=overrides.get(spec.key, default_content(spec.key)),
            is_custom=spec.key in overrides,
        )
        for spec in AVAILABLE.values()
    ]


@router.put("/{key}", response_model=PromptOut)
async def update_prompt(
    key: str,
    payload: PromptIn,
    repo: Annotated[PromptRepository, Depends(_repo)],
) -> PromptOut:
    """Store a user-specific version of the template."""
    spec = _spec(key)
    await repo.upsert(spec.key, payload.content.strip())
    return PromptOut(
        key=spec.key,
        label=spec.label,
        description=spec.description,
        default_content=default_content(spec.key),
        content=payload.content.strip(),
        is_custom=True,
    )


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def reset_prompt(key: str, repo: Annotated[PromptRepository, Depends(_repo)]) -> Response:
    """Drop the override so the shipped default applies again."""
    spec = _spec(key)
    await repo.reset(spec.key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
