"""Multi-tenant Workflow Automation Engine endpoints."""

from typing import Annotated, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    get_db_session,
    get_embedding_provider,
    get_principal,
    get_settings,
    get_usage_recorder,
)
from core.config.settings import Settings
from modules.conversations.repository import ConversationRepository
from modules.identity.principal import Principal
from modules.knowledge.repository import KnowledgeRepository
from modules.model_gateway.embeddings import EmbeddingProvider
from modules.model_gateway.openai_compatible import OpenAICompatibleProvider
from modules.tools.builtins import build_default_tool_registry
from modules.usage.metered import MeteredProvider
from modules.usage.models import KIND_CHAT
from modules.usage.recorder import UsageRecorder
from modules.workflows.repository import WorkflowRepository
from modules.workflows.runner import WorkflowRunner
from modules.workflows.schemas import (
    WorkflowApprovalIn,
    WorkflowCreateIn,
    WorkflowOut,
    WorkflowRunOut,
    WorkflowRunStartIn,
)

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


def _build_runner(
    *,
    request: Request,
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    embeddings: EmbeddingProvider,
    recorder: UsageRecorder,
) -> WorkflowRunner:
    http_client = cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None))
    base_provider = OpenAICompatibleProvider(
        provider_name=settings.llm_provider_name,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        default_model=settings.llm_default_model,
        timeout_seconds=settings.llm_timeout_seconds,
        client=http_client,
    )
    llm_provider = MeteredProvider(base_provider, recorder, kind=KIND_CHAT)
    knowledge_repo = KnowledgeRepository(
        session=session, embedding_provider=embeddings, principal=principal
    )
    conversation_repo = ConversationRepository(session=session)
    tool_registry = build_default_tool_registry(
        conversation_repo=conversation_repo,
        knowledge_repo=knowledge_repo,
    )
    return WorkflowRunner(
        session=session,
        principal=principal,
        knowledge_repo=knowledge_repo,
        llm_provider=llm_provider,
        tool_registry=tool_registry,
    )


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[WorkflowOut]:
    """List workflows owned by the caller's tenant."""
    repo = WorkflowRepository(session=session, principal=principal)
    return await repo.list_workflows()


@router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreateIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> WorkflowOut:
    """Create a new workflow definition for the caller's tenant."""
    repo = WorkflowRepository(session=session, principal=principal)
    created = await repo.create_workflow(payload)
    await session.commit()
    return created


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> None:
    """Delete a workflow definition within the caller's tenant."""
    repo = WorkflowRepository(session=session, principal=principal)
    deleted = await repo.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")
    await session.commit()


@router.get("/runs", response_model=list[WorkflowRunOut])
async def list_workflow_runs(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[WorkflowRunOut]:
    """List recent workflow execution runs for the caller's tenant."""
    repo = WorkflowRepository(session=session, principal=principal)
    return await repo.list_runs()


@router.get("/runs/{run_id}", response_model=WorkflowRunOut)
async def get_workflow_run(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> WorkflowRunOut:
    """Fetch a single workflow run and its step logs."""
    repo = WorkflowRepository(session=session, principal=principal)
    found = await repo.get_run(run_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found.")
    run, workflow_name = found
    return repo.to_run_out(run, workflow_name)


@router.post(
    "/{workflow_id}/runs",
    response_model=WorkflowRunOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_workflow_run(
    workflow_id: str,
    payload: WorkflowRunStartIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
) -> WorkflowRunOut:
    """Start executing a workflow until completion or a human_approval checkpoint."""
    repo = WorkflowRepository(session=session, principal=principal)
    workflow = await repo.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")
    if not workflow.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workflow is disabled.")

    runner = _build_runner(
        request=request,
        session=session,
        principal=principal,
        settings=settings,
        embeddings=embeddings,
        recorder=recorder,
    )
    result = await runner.start_run(workflow, input_data=payload.input)
    await session.commit()
    return result


@router.post("/runs/{run_id}/approve", response_model=WorkflowRunOut)
async def approve_workflow_run(
    run_id: str,
    payload: WorkflowApprovalIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
) -> WorkflowRunOut:
    """Approve or reject a workflow run paused at a human_approval checkpoint."""
    repo = WorkflowRepository(session=session, principal=principal)
    found = await repo.get_run(run_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found.")
    run, _ = found
    workflow = await repo.get_workflow(run.workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    runner = _build_runner(
        request=request,
        session=session,
        principal=principal,
        settings=settings,
        embeddings=embeddings,
        recorder=recorder,
    )
    try:
        result = await runner.resume_run(
            run,
            workflow,
            decision=payload.decision,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return result
