from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.conversations.models import Conversation, ConversationMessage
from modules.conversations.schemas import ModelUsageBreakdown, UsageSummary
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
        conversation = Conversation(title=clean_title, messages=[])
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def list_conversations(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Conversation]:
        """Return recent conversations ordered by last update descending."""
        stmt = (
            select(Conversation)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Fetch a conversation along with its ordered messages, or None if missing."""
        stmt = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation by ID and return True if a record was removed."""
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            return False
        await self._session.delete(conversation)
        await self._session.flush()
        return True

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

    async def get_usage_summary(self) -> UsageSummary:
        """Aggregate conversation counts and token usage grouped by provider/model."""
        conv_count = (await self._session.execute(select(func.count(Conversation.id)))).scalar_one()
        msg_count = (
            await self._session.execute(select(func.count(ConversationMessage.id)))
        ).scalar_one()

        grouped_stmt = (
            select(
                ConversationMessage.provider,
                ConversationMessage.model,
                func.count(ConversationMessage.id),
                func.coalesce(func.sum(ConversationMessage.prompt_tokens), 0),
                func.coalesce(func.sum(ConversationMessage.completion_tokens), 0),
                func.coalesce(func.sum(ConversationMessage.total_tokens), 0),
            )
            .where(ConversationMessage.role == "assistant")
            .group_by(ConversationMessage.provider, ConversationMessage.model)
            .order_by(func.sum(ConversationMessage.total_tokens).desc())
        )
        rows = (await self._session.execute(grouped_stmt)).all()

        breakdown = [
            ModelUsageBreakdown(
                provider=row[0] or "unknown",
                model=row[1] or "unknown",
                assistant_turns=int(row[2]),
                prompt_tokens=int(row[3]),
                completion_tokens=int(row[4]),
                total_tokens=int(row[5]),
            )
            for row in rows
        ]

        return UsageSummary(
            total_conversations=int(conv_count),
            total_messages=int(msg_count),
            prompt_tokens=sum(item.prompt_tokens for item in breakdown),
            completion_tokens=sum(item.completion_tokens for item in breakdown),
            total_tokens=sum(item.total_tokens for item in breakdown),
            by_model=breakdown,
        )
