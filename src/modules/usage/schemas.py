from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UsageBreakdownRow(BaseModel):
    """Aggregated upstream usage for one (user?, kind, provider, model) group."""

    user_id: str | None = None
    kind: str
    provider: str
    model: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class UsageBreakdown(BaseModel):
    """Usage grouped by call kind and model, with overall totals for the period."""

    since: datetime | None = None
    until: datetime | None = None
    total_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    rows: list[UsageBreakdownRow]


class ToolUsageItem(BaseModel):
    """Aggregated execution statistics for one tool."""

    tool_name: str
    calls: int
    share: float
    success_rate: float
    avg_duration_ms: float


class ToolUsageReport(BaseModel):
    """Top tools breakdown for the caller across a time window."""

    days: int
    total_calls: int
    tools: list[ToolUsageItem]


class TimeseriesPoint(BaseModel):
    """One day bucket of conversation activity."""

    date: str
    conversations: int
    messages: int
    tokens: int


class TimeseriesTotals(BaseModel):
    """Aggregated activity for a whole window."""

    conversations: int
    messages: int
    tokens: int


class UsageTimeseries(BaseModel):
    """Daily activity for the requested window plus the window before it."""

    days: int
    points: list[TimeseriesPoint]
    current: TimeseriesTotals
    previous: TimeseriesTotals


class FeedbackInput(BaseModel):
    """User thumbs up/down feedback on an assistant reply."""

    conversation_id: str = Field(min_length=1, max_length=64)
    message_id: str = Field(min_length=1, max_length=64)
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackResponse(BaseModel):
    """Persisted feedback acknowledgement."""

    id: str
    rating: Literal["up", "down"]
    created_at: datetime
