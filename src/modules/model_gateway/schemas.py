from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelToolCall(BaseModel):
    """Normalized tool/function invocation requested by an upstream LLM."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str = "{}"


class ChatMessage(BaseModel):
    """Single conversational or tool turn sent to an upstream LLM provider."""

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_call_id: str | None = None
    tool_calls: list[ModelToolCall] | None = None


class ModelRequest(BaseModel):
    """Normalized request payload passed into any LLMProvider implementation."""

    model_config = ConfigDict(frozen=True)

    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    tools: list[dict[str, Any]] | None = None


class TokenUsage(BaseModel):
    """Normalized token accounting returned by an upstream LLM provider."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ModelResponse(BaseModel):
    """Normalized non-streaming response returned by any LLMProvider."""

    model_config = ConfigDict(frozen=True)

    content: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str | None = None
    tool_calls: list[ModelToolCall] = Field(default_factory=list)


class StreamChunk(BaseModel):
    """Normalized incremental chunk emitted during a streaming LLM generation."""

    model_config = ConfigDict(frozen=True)

    delta: str = ""
    model: str | None = None
    usage: TokenUsage | None = None
    finish_reason: str | None = None
