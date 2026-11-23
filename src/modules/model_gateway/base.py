from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from modules.model_gateway.schemas import ModelRequest, ModelResponse, StreamChunk


@runtime_checkable
class LLMProvider(Protocol):
    """Contract that every upstream LLM adapter in Vektor must implement."""

    @property
    def provider_name(self) -> str:
        """Unique identifier for the configured provider (e.g. 'openrouter')."""
        ...

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Execute a single non-streaming chat completion request."""
        ...

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        """Yield incremental text chunks and final token usage for a chat request."""
        ...
