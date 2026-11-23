from pydantic import BaseModel, ConfigDict, Field

from modules.model_gateway.schemas import TokenUsage


class ChatTurnInput(BaseModel):
    """Validated user input for executing a single AI runtime chat turn."""

    model_config = ConfigDict(frozen=True)

    message: str = Field(min_length=1, max_length=16000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)
    model: str | None = Field(default=None, min_length=1, max_length=128)


class ChatTurnResult(BaseModel):
    """Structured outcome produced by the AI runtime for a chat turn."""

    model_config = ConfigDict(frozen=True)

    conversation_id: str = Field(min_length=1)
    reply: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    usage: TokenUsage
