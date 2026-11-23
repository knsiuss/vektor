from typing import Literal, cast

from modules.ai_runtime.prompt_loader import load_prompt
from modules.ai_runtime.schemas import ChatTurnInput, ChatTurnResult
from modules.conversations.models import Conversation
from modules.conversations.repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from modules.model_gateway.base import LLMProvider
from modules.model_gateway.schemas import ChatMessage, ModelRequest

_MAX_HISTORY_MESSAGES = 20


class ChatService:
    """Orchestrates single and multi-turn chat execution with conversation persistence."""

    def __init__(
        self,
        provider: LLMProvider,
        repository: ConversationRepository,
        *,
        system_prompt: str | None = None,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._system_prompt = system_prompt or load_prompt("system_default.md")

    async def execute_turn(self, turn_input: ChatTurnInput) -> ChatTurnResult:
        """Load conversation history, call the LLM provider, and persist the new turn."""
        conversation = await self._resolve_conversation(turn_input)
        history_messages = self._build_model_messages(conversation, turn_input.message)

        request = ModelRequest(messages=history_messages, model=turn_input.model)
        response = await self._provider.generate(request)

        await self._repository.append_message(
            conversation=conversation,
            role="user",
            content=turn_input.message,
        )
        await self._repository.append_message(
            conversation=conversation,
            role="assistant",
            content=response.content,
            provider=response.provider,
            model=response.model,
            usage=response.usage,
        )

        return ChatTurnResult(
            conversation_id=conversation.id,
            reply=response.content,
            provider=response.provider,
            model=response.model,
            usage=response.usage,
        )

    async def _resolve_conversation(self, turn_input: ChatTurnInput) -> Conversation:
        if turn_input.conversation_id is None:
            return await self._repository.create_conversation(title=turn_input.message[:80])

        conversation = await self._repository.get_conversation(turn_input.conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(turn_input.conversation_id)
        return conversation

    def _build_model_messages(
        self,
        conversation: Conversation,
        current_user_message: str,
    ) -> list[ChatMessage]:
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=self._system_prompt),
        ]
        recent_messages = conversation.messages[-_MAX_HISTORY_MESSAGES:]
        for item in recent_messages:
            if item.role in ("user", "assistant"):
                role = cast(Literal["user", "assistant"], item.role)
                messages.append(ChatMessage(role=role, content=item.content))

        messages.append(ChatMessage(role="user", content=current_user_message))
        return messages
