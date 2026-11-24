"""Server-sent-event delivery for chat turns, including turns the reader stops early."""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.ai_runtime.schemas import ChatStreamEvent, ChatTurnInput
from modules.ai_runtime.service import ChatService
from modules.usage.recorder import UsageRecorder

logger = logging.getLogger("vektor.stream")


class _Flushable(Protocol):
    async def flush(self) -> None: ...


@dataclass
class StreamedTurn:
    """What the reader has been sent so far, tracked while a turn streams."""

    conversation_id: str | None = None
    parts: list[str] = field(default_factory=list)
    # The backend reported "done": it has already saved the complete turn.
    finished: bool = False
    # The backend reported "error": nothing from this turn should be kept.
    failed: bool = False

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def observe(self, event: ChatStreamEvent) -> None:
        if event.event == "meta" and event.conversation_id:
            self.conversation_id = event.conversation_id
        elif event.event == "delta" and event.delta:
            self.parts.append(event.delta)
        elif event.event == "done":
            self.finished = True
            if event.conversation_id:
                self.conversation_id = event.conversation_id
        elif event.event == "error":
            self.failed = True


def format_sse(event: ChatStreamEvent) -> str:
    return f"event: {event.event}\ndata: {event.model_dump_json(exclude_none=True)}\n\n"


async def stream_events(
    *,
    service: ChatService,
    session: AsyncSession,
    payload: ChatTurnInput,
    recorder: UsageRecorder | _Flushable | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames for one chat turn and make sure its outcome is saved exactly once.

    The session belongs to this generator, so it is committed or rolled back here even when
    the reader disconnects mid-answer. On a disconnect (the Stop button) the text already
    sent is saved with a "stopped" marker; if no text was sent yet, nothing is saved.
    """
    turn = StreamedTurn()
    stream = service.stream_turn(payload)
    try:
        async for event in stream:
            # Record before yielding: a disconnect can interrupt the yield itself.
            turn.observe(event)
            yield format_sse(event)
    finally:
        # Runs on normal completion, errors, GeneratorExit and cancellation alike. Shielded,
        # because the framework cancels this task as soon as the reader goes away.
        with anyio.CancelScope(shield=True):
            try:
                try:
                    await stream.aclose()
                except Exception:  # noqa: BLE001 - the stream may already be finished
                    pass
                if turn.finished:
                    await session.commit()
                elif turn.failed or not turn.conversation_id or not turn.text.strip():
                    await session.rollback()
                else:
                    saved = await service.save_interrupted_turn(
                        conversation_id=turn.conversation_id,
                        user_message=payload.message,
                        partial_reply=turn.text,
                        model=payload.model,
                    )
                    if saved:
                        await session.commit()
                    else:
                        await session.rollback()
            except Exception:
                logger.exception("stream_finalize_failed conversation=%s", turn.conversation_id)
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001 - nothing more can be done for this session
                    pass
            finally:
                if recorder is not None:
                    await recorder.flush()
