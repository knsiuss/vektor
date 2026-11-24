import re
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.conversations.models import Conversation, ConversationMessage
from modules.conversations.schemas import ModelUsageBreakdown, UsageSummary
from modules.identity.models import AuditLog
from modules.identity.principal import DEV_PRINCIPAL, Principal
from modules.model_gateway.schemas import TokenUsage


class ConversationNotFoundError(Exception):
    """Raised when a referenced conversation ID does not exist."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"Conversation '{conversation_id}' was not found.")
        self.conversation_id = conversation_id


class PermissionDeniedError(Exception):
    """Raised when the caller is not authorized for the requested operation."""


class ConversationRepository:
    """Async repository for persisting conversations and their message history."""

    def __init__(self, session: AsyncSession, principal: Principal | None = None) -> None:
        # Falling back to the development principal still scopes every query to one
        # tenant; it never means "unscoped", so a forgotten call site cannot leak.
        self._session = session
        self._principal = principal or DEV_PRINCIPAL

    def _scope(self, *, tenant_wide: bool = False):
        """Conversations the caller may see: own threads, or the whole tenant for admins."""
        clauses = [Conversation.tenant_id == self._principal.tenant_id]
        if not tenant_wide:
            clauses.append(Conversation.owner_id == self._principal.user_id)
        return and_(*clauses)

    async def _audit(self, action: str, conversation: Conversation | None) -> None:
        """Record privileged access to a colleague's conversation."""
        self._session.add(
            AuditLog(
                tenant_id=self._principal.tenant_id,
                actor_id=self._principal.user_id,
                action=action,
                resource_type="conversation",
                resource_id=conversation.id if conversation else None,
                resource_owner_id=conversation.owner_id if conversation else None,
            )
        )
        await self._session.flush()

    async def create_conversation(self, title: str) -> Conversation:
        """Create and flush a new conversation record owned by the caller."""
        clean_title = title.strip()[:255] or "New Conversation"
        conversation = Conversation(
            title=clean_title,
            tenant_id=self._principal.tenant_id,
            owner_id=self._principal.user_id,
            messages=[],
        )
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def list_conversations(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Conversation]:
        """Return the caller's recent conversations ordered by last update descending."""
        stmt = (
            select(Conversation)
            .where(self._scope())
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_tenant_conversations(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Conversation]:
        """Admin view: every conversation in the tenant, with an audit record."""
        stmt = (
            select(Conversation)
            .where(self._scope(tenant_wide=True))
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        await self._audit("conversation.list", None)
        return rows

    async def _load_conversation(self, conversation_id: str) -> Conversation | None:
        stmt = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
            # Compaction rewrites messages with bulk SQL, so always reload the collection.
            .execution_options(populate_existing=True)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Fetch a conversation the caller may read, or None when it is not theirs.

        Another user's thread is invisible to members (404 semantics) and readable by
        a tenant admin, whose access is written to the audit log.
        """
        conversation = await self._load_conversation(conversation_id)
        if conversation is None:
            return None
        if conversation.tenant_id != self._principal.tenant_id:
            return None
        if conversation.owner_id != self._principal.user_id:
            if not self._principal.is_admin:
                return None
            await self._audit("conversation.read", conversation)
        return conversation

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation the caller owns or administers, auditing cross-user deletes."""
        conversation = await self._load_conversation(conversation_id)
        if conversation is None or conversation.tenant_id != self._principal.tenant_id:
            return False
        if conversation.owner_id != self._principal.user_id:
            if not self._principal.is_admin:
                return False
            await self._audit("conversation.delete", conversation)
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
        status: str | None = None,
        clarify_options: list[str] | None = None,
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
            status=status,
            clarify_options=clarify_options,
        )
        conversation.updated_at = datetime.now(UTC)
        self._session.add(message)
        await self._session.flush()
        return message

    async def replace_messages_with_summary(
        self,
        *,
        conversation: Conversation,
        message_ids: list[str],
        content: str,
        created_at: datetime | None = None,
    ) -> ConversationMessage:
        """Delete the given messages and insert one summary ahead of the surviving turns."""
        if message_ids:
            await self._session.execute(
                delete(ConversationMessage).where(ConversationMessage.id.in_(message_ids))
            )
        summary = ConversationMessage(
            conversation_id=conversation.id,
            role="summary",
            content=content,
            created_at=created_at or datetime.now(UTC),
        )
        conversation.updated_at = datetime.now(UTC)
        self._session.add(summary)
        await self._session.flush()
        return summary

    async def get_usage_summary(self, *, tenant_wide: bool = False) -> UsageSummary:
        """Aggregate conversation counts and token usage for the caller or the tenant."""
        scope = self._scope(tenant_wide=tenant_wide)
        conv_count = (
            await self._session.execute(select(func.count(Conversation.id)).where(scope))
        ).scalar_one()
        msg_count = (
            await self._session.execute(
                select(func.count(ConversationMessage.id))
                .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
                .where(scope)
            )
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
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .where(ConversationMessage.role == "assistant", scope)
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

    async def search_messages(
        self,
        *,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, str]]:
        """Search past conversation messages across sessions using FTS/token matching."""
        clean_query = query.strip()
        if not clean_query:
            return []

        bind = self._session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            sql = text(
                """
                SELECT
                    c.id AS conversation_id,
                    c.title AS title,
                    m.role AS role,
                    m.content AS content
                FROM conversation_messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE to_tsvector('simple', m.content) @@ plainto_tsquery('simple', :query)
                  AND c.tenant_id = :tenant_id
                  AND c.owner_id = :owner_id
                ORDER BY m.created_at DESC
                LIMIT :limit
                """
            )
            rows = (
                await self._session.execute(
                    sql,
                    {
                        "query": clean_query,
                        "limit": limit,
                        "tenant_id": self._principal.tenant_id,
                        "owner_id": self._principal.user_id,
                    },
                )
            ).mappings()
            return [
                {
                    "conversation_id": str(r["conversation_id"]),
                    "title": str(r["title"]),
                    "role": str(r["role"]),
                    "snippet": str(r["content"])[:400],
                }
                for r in rows
            ]

        tokens = [t for t in re.findall(r"[a-z0-9_.-]+", clean_query.lower()) if len(t) >= 2]
        if not tokens:
            return []
        stmt = (
            select(
                Conversation.id,
                Conversation.title,
                ConversationMessage.role,
                ConversationMessage.content,
            )
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .where(self._scope())
            .order_by(ConversationMessage.created_at.desc())
            .limit(300)
        )
        rows_raw = (await self._session.execute(stmt)).all()
        scored: list[tuple[int, dict[str, str]]] = []
        for conv_id, title, role, content in rows_raw:
            lower = content.lower()
            hits = sum(1 for tok in tokens if tok in lower)
            if hits > 0:
                scored.append(
                    (
                        hits,
                        {
                            "conversation_id": conv_id,
                            "title": title,
                            "role": role,
                            "snippet": content[:400],
                        },
                    )
                )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _score, item in scored[:limit]]
