from modules.ai_runtime.prompt_loader import load_prompt
from modules.ai_runtime.schemas import ChatTurnInput, ChatTurnResult
from modules.model_gateway.base import LLMProvider
from modules.model_gateway.schemas import ChatMessage, ModelRequest


class ChatService:
    """Orchestrates single-turn chat execution against a configured LLM provider."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        system_prompt: str | None = None,
    ) -> None:
        self._provider = provider
        self._system_prompt = system_prompt or load_prompt("system_default.md")

    async def execute_turn(self, turn_input: ChatTurnInput) -> ChatTurnResult:
        """Build a safe prompt boundary and execute a completion request."""
        request = ModelRequest(
            messages=[
                ChatMessage(role="system", content=self._system_prompt),
                ChatMessage(role="user", content=turn_input.message),
            ],
            model=turn_input.model,
        )
        response = await self._provider.generate(request)

        return ChatTurnResult(
            reply=response.content,
            provider=response.provider,
            model=response.model,
            usage=response.usage,
        )
