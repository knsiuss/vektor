from typing import Protocol, runtime_checkable

from modules.model_gateway.schemas import ModelRequest, ModelResponse


@runtime_checkable
class LLMProvider(Protocol):
    """Contract that every LLM provider implementation must satisfy."""

    @property
    def provider_name(self) -> str:
        """Return the canonical identifier of the LLM provider."""
        ...

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Execute a completion request and return a normalized ModelResponse."""
        ...
