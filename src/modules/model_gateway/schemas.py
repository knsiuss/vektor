from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MessageRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """A single validated message within a model conversation."""

    model_config = ConfigDict(frozen=True)

    role: MessageRole
    content: str = Field(min_length=1)


class TokenUsage(BaseModel):
    """Normalized token consumption metadata reported by an LLM provider."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ModelRequest(BaseModel):
    """Normalized request payload sent to any configured LLM provider."""

    model_config = ConfigDict(frozen=True)

    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=32768)


class ModelResponse(BaseModel):
    """Normalized response returned from an LLM provider."""

    model_config = ConfigDict(frozen=True)

    content: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    usage: TokenUsage
    finish_reason: str | None = Field(default=None)
