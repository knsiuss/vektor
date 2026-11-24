from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ChannelType = Literal["telegram", "whatsapp_cloud", "whatsapp_qr", "discord"]


class ChannelCreate(BaseModel):
    channel_type: ChannelType
    name: str = Field(min_length=1, max_length=128)
    config: dict[str, str] = Field(default_factory=dict)
    system_prompt: str | None = Field(default=None, max_length=4000)
    auto_handover_threshold: int = Field(default=2, ge=0, le=10)
    knowledge_scope: list[str] | None = None


class ChannelResponse(BaseModel):
    """Public-safe connector view; never exposes raw bot tokens or secrets."""

    id: str
    tenant_id: str
    channel_type: str
    name: str
    webhook_path: str
    has_credentials: bool
    system_prompt: str | None
    auto_handover_threshold: int
    knowledge_scope: list[str] | None
    is_active: bool
    created_at: datetime


class InboundMessage(BaseModel):
    external_user_id: str
    reply_target_id: str
    text: str
    external_event_id: str | None = None
