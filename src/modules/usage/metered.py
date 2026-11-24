from collections.abc import AsyncIterator

from modules.model_gateway.base import LLMProvider
from modules.model_gateway.schemas import ModelRequest, ModelResponse, StreamChunk
from modules.usage.recorder import UsageRecorder


class MeteredProvider:
    """LLMProvider decorator that records token usage for every successful upstream call."""

    def __init__(self, inner: LLMProvider, recorder: UsageRecorder, *, kind: str) -> None:
        self._inner = inner
        self._recorder = recorder
        self._kind = kind

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    async def generate(self, request: ModelRequest) -> ModelResponse:
        response = await self._inner.generate(request)
        self._recorder.record(
            kind=self._kind,
            provider=response.provider,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
        )
        return response

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        resolved_model = request.model or "unknown"
        async for chunk in self._inner.stream(request):
            if chunk.model:
                resolved_model = chunk.model
            if chunk.usage is not None:
                self._recorder.record(
                    kind=self._kind,
                    provider=self._inner.provider_name,
                    model=resolved_model,
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    total_tokens=chunk.usage.total_tokens,
                )
            yield chunk
