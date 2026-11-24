from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    status: str | None = None
    clarify_options: list[str] | None = None
    created_at: datetime


class ConversationContext(BaseModel):
    """How much of the model prompt window the stored history currently occupies."""

    used_tokens: int
    limit_tokens: int
    included_messages: int
    total_messages: int


class ConversationDetail(ConversationSummary):
    """Full conversation thread including its ordered message history."""

    messages: list[MessageItem]
    context: ConversationContext


class AdminConversationSummary(BaseModel):
    """Tenant-wide conversation summary for admin views."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    owner_id: str
    created_at: datetime
    updated_at: datetime


class ModelUsageBreakdown(BaseModel):
    """Aggregated token usage for a specific provider and model."""

    provider: str
    model: str
    assistant_turns: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class DailyUsage(BaseModel):
    """Daily usage totals for a single day."""

    date: str
    conversations: int
    messages: int
    tokens: int


class UsageSummary(BaseModel):
    """Platform-wide conversation and token usage metrics."""

    total_conversations: int
    total_messages: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    by_model: list[ModelUsageBreakdown]
    # Assistant reply outcomes ("answer" | "clarify" | "unknown") for this scope.
    by_status: dict[str, int] = Field(default_factory=dict)
