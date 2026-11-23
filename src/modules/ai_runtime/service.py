from collections.abc import AsyncIterator, Sequence
from typing import Literal, cast

from modules.ai_runtime.prompt_loader import load_prompt
from modules.ai_runtime.retriever import KnowledgeRetriever, format_grounded_context
from modules.ai_runtime.schemas import ChatStreamEvent, ChatTurnInput, ChatTurnResult
from modules.conversations.models import Conversation
from modules.conversations.repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from modules.knowledge.schemas import RetrievedChunk
from modules.model_gateway.base import LLMProvider
from modules.model_gateway.exceptions import ModelGatewayError
from modules.model_gateway.schemas import ChatMessage, ModelRequest, TokenUsage

_MAX_HISTORY_MESSAGES = 20


class ChatService:
    """Orchestrates single and multi-turn chat execution with RAG and persistence."""

    def __init__(
        self,
        provider: LLMProvider,
        repository: ConversationRepository,
        *,
        retriever: KnowledgeRetriever | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._retriever = retriever
        self._system_prompt = system_prompt or load_prompt("system_default.md")

    async def execute_turn(self, turn_input: ChatTurnInput) -> ChatTurnResult:
        """Retrieve relevant knowledge, call the LLM provider, and persist the turn."""
        conversation = await self._resolve_conversation(turn_input)
        citations = await self._retrieve_context(turn_input)
        history_messages = self._build_model_messages(
            conversation,
            turn_input.message,
            citations=citations,
        )

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
            citations=citations,
        )

    async def stream_turn(self, turn_input: ChatTurnInput) -> AsyncIterator[ChatStreamEvent]:
        """Stream RAG citations and incremental chat chunks, then persist the reply."""
        conversation = await self._resolve_conversation(turn_input)
        citations = await self._retrieve_context(turn_input)
        history_messages = self._build_model_messages(
            conversation,
            turn_input.message,
            citations=citations,
        )
        request = ModelRequest(messages=history_messages, model=turn_input.model)

        yield ChatStreamEvent(
            event="meta",
            conversation_id=conversation.id,
            provider=self._provider.provider_name,
            model=turn_input.model,
        )
        if citations:
            yield ChatStreamEvent(event="citations", citations=citations)

        accumulated_parts: list[str] = []
        resolved_model = turn_input.model or "unknown"
        final_usage = TokenUsage()

        try:
            async for chunk in self._provider.stream(request):
                if chunk.model:
                    resolved_model = chunk.model
                if chunk.usage is not None:
                    final_usage = chunk.usage
                if chunk.delta:
                    accumulated_parts.append(chunk.delta)
                    yield ChatStreamEvent(event="delta", delta=chunk.delta)
        except ModelGatewayError as exc:
            yield ChatStreamEvent(event="error", detail=str(exc))
            return

        full_reply = "".join(accumulated_parts)
        await self._repository.append_message(
            conversation=conversation,
            role="user",
            content=turn_input.message,
        )
        await self._repository.append_message(
            conversation=conversation,
            role="assistant",
            content=full_reply,
            provider=self._provider.provider_name,
            model=resolved_model,
            usage=final_usage,
        )

        yield ChatStreamEvent(
            event="done",
            conversation_id=conversation.id,
            provider=self._provider.provider_name,
            model=resolved_model,
            usage=final_usage,
        )

    async def _retrieve_context(self, turn_input: ChatTurnInput) -> list[RetrievedChunk]:
        if self._retriever is None:
            return []
        return await self._retriever.retrieve(
            user_message=turn_input.message,
            mode=turn_input.retrieval_mode,
            document_ids=turn_input.document_ids,
            top_k=turn_input.top_k,
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
        *,
        citations: Sequence[RetrievedChunk],
    ) -> list[ChatMessage]:
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=self._system_prompt),
        ]
        grounded_block = format_grounded_context(citations)
        if grounded_block:
            messages.append(ChatMessage(role="system", content=grounded_block))

        recent_messages = conversation.messages[-_MAX_HISTORY_MESSAGES:]
        for item in recent_messages:
            if item.role in ("user", "assistant"):
                role = cast(Literal["user", "assistant"], item.role)
                messages.append(ChatMessage(role=role, content=item.content))

        messages.append(ChatMessage(role="user", content=current_user_message))
        return messages
