from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from modules.knowledge.schemas import RetrievedChunk
from modules.model_gateway.schemas import TokenUsage
from modules.tools.schemas import ToolExecutionRecord


class ChatTurnInput(BaseModel):
    """Validated user input for executing a single AI runtime chat turn."""

    model_config = ConfigDict(frozen=True)

    message: str = Field(min_length=1, max_length=16000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    retrieval_mode: Literal["auto", "always", "explicit", "off"] = "auto"
    document_ids: list[str] | None = None
    top_k: int = Field(default=4, ge=1, le=10)
    enable_tools: bool = True
    allow_mutating_tools: bool = False


class ChatTurnResult(BaseModel):
    """Structured outcome produced by the AI runtime for a chat turn."""

    model_config = ConfigDict(frozen=True)

    conversation_id: str = Field(min_length=1)
    reply: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    usage: TokenUsage
    citations: list[RetrievedChunk] = Field(default_factory=list)
    tool_calls: list[ToolExecutionRecord] = Field(default_factory=list)


class ChatStreamEvent(BaseModel):
    """Structured SSE event emitted during streaming chat execution."""

    model_config = ConfigDict(frozen=True)

    event: Literal["meta", "citations", "delta", "done", "error"]
    conversation_id: str | None = None
    delta: str | None = None
    provider: str | None = None
    model: str | None = None
    usage: TokenUsage | None = None
    citations: list[RetrievedChunk] | None = None
    detail: str | None = None
