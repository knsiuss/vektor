from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConversationSummary(BaseModel):
    """Lightweight representation of a conversation thread for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageItem(BaseModel):
    """Serialized view of a single persisted message inside a conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    provider: str | None
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    created_at: datetime


class ConversationDetail(ConversationSummary):
    """Full conversation thread including its ordered message history."""

    messages: list[MessageItem]
