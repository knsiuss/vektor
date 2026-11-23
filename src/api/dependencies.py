from typing import cast

import httpx
from fastapi import Request

from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.model_gateway.openai_compatible import OpenAICompatibleProvider


def get_chat_service(request: Request) -> ChatService:
    """Build a ChatService wired to the application's configured LLM provider."""
    settings = cast(Settings, request.app.state.settings)
    http_client = cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None))

    provider = OpenAICompatibleProvider(
        provider_name=settings.llm_provider_name,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        default_model=settings.llm_default_model,
        timeout_seconds=settings.llm_timeout_seconds,
        client=http_client,
    )
    return ChatService(provider=provider)
