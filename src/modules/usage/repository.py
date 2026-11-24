from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.conversations.models import Conversation, ConversationMessage
from modules.conversations.repository import PermissionDeniedError
from modules.identity.principal import Principal
from modules.usage.models import MessageFeedback, ToolUsageEvent, UsageEvent
from modules.usage.schemas import (
    FeedbackItem,
    FeedbackResponse,
    TimeseriesPoint,
    TimeseriesTotals,
    ToolUsageItem,
    ToolUsageReport,
    UsageBreakdown,
    UsageBreakdownRow,
    UsageTimeseries,
)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class UsageEventRepository:
    """Read access to usage events, always scoped to the caller's tenant (and user)."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._session = session
        self._principal = principal

    async def breakdown(
        self,
        *,
        tenant_wide: bool = False,
        by_user: bool = False,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> UsageBreakdown:
        """Aggregate calls and tokens by kind/provider/model (and by user for admins)."""
        if (tenant_wide or by_user) and not self._principal.is_admin:
            raise PermissionDeniedError("Administrator role required.")

        since_utc = _as_utc(since)
        until_utc = _as_utc(until)

        columns = [
            UsageEvent.kind,
            UsageEvent.provider,
            UsageEvent.model,
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            func.coalesce(func.sum(UsageEvent.total_tokens), 0),
        ]
        group_by = [UsageEvent.kind, UsageEvent.provider, UsageEvent.model]
        if by_user:
            columns.insert(0, UsageEvent.user_id)
            group_by.insert(0, UsageEvent.user_id)

        stmt = select(*columns).where(UsageEvent.tenant_id == self._principal.tenant_id)
        if not tenant_wide:
            stmt = stmt.where(UsageEvent.user_id == self._principal.user_id)
        if since_utc is not None:
            stmt = stmt.where(UsageEvent.created_at >= since_utc)
        if until_utc is not None:
            stmt = stmt.where(UsageEvent.created_at < until_utc)
        stmt = stmt.group_by(*group_by).order_by(func.sum(UsageEvent.total_tokens).desc())

        rows: list[UsageBreakdownRow] = []
        for record in (await self._session.execute(stmt)).all():
            offset = 1 if by_user else 0
            rows.append(
                UsageBreakdownRow(
                    user_id=record[0] if by_user else None,
                    kind=record[offset],
                    provider=record[offset + 1],
                    model=record[offset + 2],
                    calls=int(record[offset + 3]),
                    prompt_tokens=int(record[offset + 4]),
                    completion_tokens=int(record[offset + 5]),
                    total_tokens=int(record[offset + 6]),
                )
            )

        return UsageBreakdown(
            since=since_utc,
            until=until_utc,
            total_calls=sum(r.calls for r in rows),
            prompt_tokens=sum(r.prompt_tokens for r in rows),
            completion_tokens=sum(r.completion_tokens for r in rows),
            total_tokens=sum(r.total_tokens for r in rows),
            rows=rows,
        )

    async def timeseries(self, *, days: int) -> UsageTimeseries:
        """Daily conversation activity for the caller, plus the window before it."""
        today = datetime.now(UTC).date()
        window_start = today - timedelta(days=days - 1)
        previous_start = window_start - timedelta(days=days)
        scope = (
            Conversation.tenant_id == self._principal.tenant_id,
            Conversation.owner_id == self._principal.user_id,
        )

        conversations = {
            str(row[0]): int(row[1])
            for row in (
                await self._session.execute(
                    select(func.date(Conversation.created_at), func.count(Conversation.id))
                    .where(*scope, func.date(Conversation.created_at) >= previous_start.isoformat())
                    .group_by(func.date(Conversation.created_at))
                )
            ).all()
        }
        message_rows = (
            await self._session.execute(
                select(
                    func.date(ConversationMessage.created_at),
                    func.count(ConversationMessage.id),
                    func.coalesce(func.sum(ConversationMessage.total_tokens), 0),
                )
                .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
                .where(
                    *scope,
                    func.date(ConversationMessage.created_at) >= previous_start.isoformat(),
                )
                .group_by(func.date(ConversationMessage.created_at))
            )
        ).all()
        messages = {str(row[0]): int(row[1]) for row in message_rows}
        tokens = {str(row[0]): int(row[2]) for row in message_rows}

        points: list[TimeseriesPoint] = []
        for offset in range(days):
            day = (window_start + timedelta(days=offset)).isoformat()
            points.append(
                TimeseriesPoint(
                    date=day,
                    conversations=conversations.get(day, 0),
                    messages=messages.get(day, 0),
                    tokens=tokens.get(day, 0),
                )
            )

        previous_days = {
            (previous_start + timedelta(days=offset)).isoformat() for offset in range(days)
        }
        return UsageTimeseries(
            days=days,
            points=points,
            current=TimeseriesTotals(
                conversations=sum(point.conversations for point in points),
                messages=sum(point.messages for point in points),
                tokens=sum(point.tokens for point in points),
            ),
            previous=TimeseriesTotals(
                conversations=sum(
                    count for day, count in conversations.items() if day in previous_days
                ),
                messages=sum(count for day, count in messages.items() if day in previous_days),
                tokens=sum(count for day, count in tokens.items() if day in previous_days),
            ),
        )

    async def list_feedback(
        self,
        *,
        rating: str | None = None,
        limit: int = 20,
    ) -> list[FeedbackItem]:
        """Recent feedback from the caller, newest first, with the answer it refers to."""
        stmt = (
            select(MessageFeedback, Conversation.title, ConversationMessage.content)
            .outerjoin(Conversation, Conversation.id == MessageFeedback.conversation_id)
            .outerjoin(ConversationMessage, ConversationMessage.id == MessageFeedback.message_id)
            .where(
                MessageFeedback.tenant_id == self._principal.tenant_id,
                MessageFeedback.user_id == self._principal.user_id,
            )
            .order_by(MessageFeedback.created_at.desc())
            .limit(limit)
        )
        if rating is not None:
            stmt = stmt.where(MessageFeedback.rating == rating)

        rows = (await self._session.execute(stmt)).all()
        return [
            FeedbackItem(
                id=feedback.id,
                conversation_id=feedback.conversation_id,
                conversation_title=title,
                message_id=feedback.message_id,
                excerpt=(content or "")[:400],
                rating=feedback.rating,
                comment=feedback.comment,
                created_at=feedback.created_at,
            )
            for feedback, title, content in rows
        ]

    async def record_tool_call(
        self,
        *,
        tool_name: str,
        status: str,
        duration_ms: int,
    ) -> None:
        """Persist a single tool invocation telemetry record for the caller."""
        self._session.add(
            ToolUsageEvent(
                tenant_id=self._principal.tenant_id,
                user_id=self._principal.user_id,
                tool_name=tool_name[:128],
                status=status[:24],
                duration_ms=max(0, duration_ms),
            )
        )
        await self._session.flush()

    async def top_tools(
        self,
        *,
        days: int = 30,
        limit: int = 10,
    ) -> ToolUsageReport:
        """Return ranked tool invocation telemetry for the caller within the last N days."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        success_case = case((ToolUsageEvent.status == "success", 1), else_=0)
        stmt = (
            select(
                ToolUsageEvent.tool_name,
                func.count(ToolUsageEvent.id),
                func.coalesce(func.sum(success_case), 0),
                func.coalesce(func.avg(ToolUsageEvent.duration_ms), 0.0),
            )
            .where(
                ToolUsageEvent.tenant_id == self._principal.tenant_id,
                ToolUsageEvent.user_id == self._principal.user_id,
                ToolUsageEvent.created_at >= cutoff,
            )
            .group_by(ToolUsageEvent.tool_name)
            .order_by(func.count(ToolUsageEvent.id).desc())
            .limit(limit)
        )
        records = (await self._session.execute(stmt)).all()
        total_calls = sum(int(row[1]) for row in records)
        tools: list[ToolUsageItem] = []
        for tool_name, calls_raw, successes_raw, avg_ms_raw in records:
            calls = int(calls_raw)
            successes = int(successes_raw)
            tools.append(
                ToolUsageItem(
                    tool_name=str(tool_name),
                    calls=calls,
                    share=round(calls / total_calls, 4) if total_calls else 0.0,
                    success_rate=round(successes / calls, 4) if calls else 0.0,
                    avg_duration_ms=round(float(avg_ms_raw), 1),
                )
            )
        return ToolUsageReport(days=days, total_calls=total_calls, tools=tools)

    async def record_feedback(
        self,
        *,
        conversation_id: str,
        message_id: str,
        rating: Literal["up", "down"],
        comment: str | None = None,
    ) -> FeedbackResponse:
        """Persist thumbs up/down feedback on an assistant response."""
        item = MessageFeedback(
            tenant_id=self._principal.tenant_id,
            user_id=self._principal.user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            rating=rating,
            comment=comment.strip() if comment and comment.strip() else None,
        )
        self._session.add(item)
        await self._session.flush()
        return FeedbackResponse(
            id=item.id,
            rating=rating,
            created_at=item.created_at,
        )
