"""MCP Apps host endpoints for reading UI resources and bridging widget tool calls."""

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session, get_embedding_provider, get_principal
from modules.conversations.repository import ConversationRepository
from modules.identity.principal import Principal
from modules.knowledge.repository import KnowledgeRepository
from modules.mcp_apps.registry import build_default_ui_registry
from modules.model_gateway.embeddings import EmbeddingProvider
from modules.tools.builtins import build_default_tool_registry
from modules.tools.schemas import ToolExecutionRecord

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])

_UI_REGISTRY = build_default_ui_registry()


class UIResourceOut(BaseModel):
    """MCP App UI resource payload."""

    uri: str
    name: str
    mime_type: str
    html: str


class MCPToolCallIn(BaseModel):
    """Tool invocation bridged from an MCP App widget through the host."""

    name: str = Field(..., min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    allow_mutating: bool = False


@router.get("/resources", response_model=UIResourceOut)
async def read_ui_resource(
    response: Response,
    uri: Annotated[str, Query(min_length=1, description="MCP App ui:// resource URI")],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> UIResourceOut:
    """Read a registered MCP App HTML template by its ui:// URI."""
    resource = _UI_REGISTRY.get(uri)
    if resource is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"UI resource '{uri}' not found.",
        )
    response.headers["Cache-Control"] = "private, max-age=300"
    return UIResourceOut(
        uri=resource.uri,
        name=resource.name,
        mime_type=resource.mime_type,
        html=resource.html,
    )


@router.post("/tools/call", response_model=ToolExecutionRecord)
async def call_mcp_tool(
    payload: MCPToolCallIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> ToolExecutionRecord:
    """Execute an allowlisted tool on behalf of an interactive MCP App widget."""
    knowledge_repo = KnowledgeRepository(
        session=session, embedding_provider=embeddings, principal=principal
    )
    conversation_repo = ConversationRepository(session=session)
    registry = build_default_tool_registry(
        conversation_repo=conversation_repo,
        knowledge_repo=knowledge_repo,
    )
    return await registry.execute(
        call_id=f"mcp-ui-{uuid4().hex[:12]}",
        tool_name=payload.name,
        raw_arguments=payload.arguments,
        allow_mutating=payload.allow_mutating,
    )
