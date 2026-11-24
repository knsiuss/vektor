from datetime import datetime

from pydantic import BaseModel, Field


class WidgetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    allowed_domains: list[str] = Field(default_factory=list, max_length=50)
    system_prompt: str | None = Field(default=None, max_length=4000)
    welcome_message: str = Field(
        default="Halo! Ada yang bisa saya bantu?",
        min_length=1,
        max_length=500,
    )
    theme: dict[str, str] = Field(
        default_factory=lambda: {"primary_color": "#2563eb", "position": "bottom-right"}
    )
    knowledge_scope: list[str] | None = None


class WidgetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    allowed_domains: list[str] | None = Field(default=None, max_length=50)
    system_prompt: str | None = Field(default=None, max_length=4000)
    welcome_message: str | None = Field(default=None, min_length=1, max_length=500)
    theme: dict[str, str] | None = None
    knowledge_scope: list[str] | None = None
    is_active: bool | None = None


class WidgetResponse(BaseModel):
    id: str
    tenant_id: str
    public_key: str
    name: str
    allowed_domains: list[str]
    system_prompt: str | None
    welcome_message: str
    theme: dict[str, str]
    knowledge_scope: list[str] | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WidgetPublicConfig(BaseModel):
    name: str
    welcome_message: str
    theme: dict[str, str]


class PublicChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    visitor_token: str = Field(min_length=8, max_length=128)
