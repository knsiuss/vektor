from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.conversations.models import Conversation, ConversationMessage
from modules.model_gateway.schemas import TokenUsage


class ConversationNotFoundError(Exception):
    """Raised when a referenced conversation ID does not exist."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"Conversation '{conversation_id}' was not found.")
        self.conversation_id = conversation_id


class ConversationRepository:
    """Async repository for persisting conversations and their message history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_conversation(self, title: str) -> Conversation:
        """Create and flush a new conversation record."""
        clean_title = title.strip()[:255] or "New Conversation"
        conversation = Conversation(title=clean_title)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Fetch a conversation along with its ordered messages, or None if missing."""
        stmt = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def append_message(
        self,
        *,
        conversation: Conversation,
        role: str,
        content: str,
        provider: str | None = None,
        model: str | None = None,
        usage: TokenUsage | None = None,
    ) -> ConversationMessage:
        """Persist a new message into an existing conversation and bump updated_at."""
        message = ConversationMessage(
            conversation_id=conversation.id,
            role=role,
            content=content,
            provider=provider,
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
        )
        conversation.updated_at = datetime.now(UTC)
        self._session.add(message)
        await self._session.flush()
        return message
