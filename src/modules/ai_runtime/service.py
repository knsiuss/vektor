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
from modules.model_gateway.schemas import ChatMessage, ModelRequest, ModelResponse, TokenUsage
from modules.tools.registry import ToolRegistry
from modules.tools.schemas import ToolExecutionRecord

_MAX_HISTORY_MESSAGES = 20
_MAX_TOOL_ITERATIONS = 3


class ChatService:
    """Orchestrates multi-turn chat with hybrid RAG, bounded tool calls, and persistence."""

    def __init__(
        self,
        provider: LLMProvider,
        repository: ConversationRepository,
        *,
        retriever: KnowledgeRetriever | None = None,
        tool_registry: ToolRegistry | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._retriever = retriever
        self._tools = tool_registry
        self._system_prompt = system_prompt or load_prompt("system_default.md")

    async def execute_turn(self, turn_input: ChatTurnInput) -> ChatTurnResult:
        """Retrieve knowledge, run bounded tool loop, and persist the completed turn."""
        conversation = await self._resolve_conversation(turn_input)
        citations = await self._retrieve_context(turn_input)
        working_messages = self._build_model_messages(
            conversation,
            turn_input.message,
            citations=citations,
        )

        response, tool_records, total_usage = await self._run_with_tools(
            working_messages,
            turn_input=turn_input,
        )

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
            usage=total_usage,
        )

        return ChatTurnResult(
            conversation_id=conversation.id,
            reply=response.content,
            provider=response.provider,
            model=response.model,
            usage=total_usage,
            citations=citations,
            tool_calls=tool_records,
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

    async def _run_with_tools(
        self,
        messages: list[ChatMessage],
        *,
        turn_input: ChatTurnInput,
    ) -> tuple[ModelResponse, list[ToolExecutionRecord], TokenUsage]:
        tool_schemas = self._resolve_tool_schemas(turn_input)
        records: list[ToolExecutionRecord] = []
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        for _ in range(_MAX_TOOL_ITERATIONS):
            request = ModelRequest(
                messages=messages,
                model=turn_input.model,
                tools=tool_schemas or None,
            )
            response = await self._provider.generate(request)
            prompt_tokens += response.usage.prompt_tokens
            completion_tokens += response.usage.completion_tokens
            total_tokens += response.usage.total_tokens

            if not response.tool_calls or self._tools is None or not turn_input.enable_tools:
                return (
                    response,
                    records,
                    TokenUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    ),
                )

            messages.append(
                ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for call in response.tool_calls:
                exec_record = await self._tools.execute(
                    call_id=call.id,
                    tool_name=call.name,
                    raw_arguments=call.arguments,
                    allow_mutating=turn_input.allow_mutating_tools,
                )
                records.append(exec_record)
                messages.append(
                    ChatMessage(
                        role="tool",
                        tool_call_id=call.id,
                        content=exec_record.output,
                    )
                )

        # Final synthesis pass with tools disabled after reaching iteration cap
        final_response = await self._provider.generate(
            ModelRequest(messages=messages, model=turn_input.model)
        )
        prompt_tokens += final_response.usage.prompt_tokens
        completion_tokens += final_response.usage.completion_tokens
        total_tokens += final_response.usage.total_tokens
        return (
            final_response,
            records,
            TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ),
        )

    def _resolve_tool_schemas(self, turn_input: ChatTurnInput) -> list[dict[str, object]]:
        if self._tools is None or not turn_input.enable_tools:
            return []
        defs = self._tools.list_definitions(include_mutating=turn_input.allow_mutating_tools)
        return [item.to_openai_tool() for item in defs]

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
