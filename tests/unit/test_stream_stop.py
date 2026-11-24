import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from api.streaming import StreamedTurn, stream_events
from modules.ai_runtime.schemas import ChatStreamEvent, ChatTurnInput
from modules.ai_runtime.service import STOPPED_SUFFIX, ChatService

QUESTION = "What is the failover procedure?"


def _meta(conversation_id: str = "c1") -> ChatStreamEvent:
    return ChatStreamEvent(event="meta", conversation_id=conversation_id)


def _delta(text: str) -> ChatStreamEvent:
    return ChatStreamEvent(event="delta", delta=text)


def _done(conversation_id: str = "c1") -> ChatStreamEvent:
    return ChatStreamEvent(event="done", conversation_id=conversation_id)


class _FakeService:
    """Stands in for ChatService: replays events, then optionally hangs like a slow model."""

    def __init__(
        self,
        events: list[ChatStreamEvent],
        *,
        hang_after: bool = False,
        save_result: bool = True,
        save_error: Exception | None = None,
    ) -> None:
        self._events = events
        self._hang_after = hang_after
        self._save_result = save_result
        self._save_error = save_error
        self.saved: list[dict[str, Any]] = []

    async def stream_turn(self, payload: ChatTurnInput) -> AsyncIterator[ChatStreamEvent]:
        for event in self._events:
            yield event
        if self._hang_after:
            await asyncio.sleep(30)

    async def save_interrupted_turn(self, **kwargs: Any) -> bool:
        if self._save_error is not None:
            raise self._save_error
        self.saved.append(kwargs)
        return self._save_result


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def commit(self) -> None:
        self.calls.append("commit")

    async def rollback(self) -> None:
        self.calls.append("rollback")


class _FakeRecorder:
    def __init__(self) -> None:
        self.flushed = 0

    async def flush(self) -> None:
        self.flushed += 1


def _run(
    service: _FakeService,
    session: _FakeSession,
    recorder: _FakeRecorder,
) -> AsyncIterator[str]:
    return stream_events(
        service=service,  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
        payload=ChatTurnInput(message=QUESTION),
        recorder=recorder,
    )


async def _take_then_close(agen: Any, count: int | None) -> list[str]:
    """Read ``count`` frames (all when None), then close the stream like a dropped client."""
    frames: list[str] = []
    async for frame in agen:
        frames.append(frame)
        if count is not None and len(frames) == count:
            break
    await agen.aclose()
    return frames


async def test_completed_turn_is_committed_and_not_saved_again() -> None:
    """Verify a normal turn is committed once; the stop path must not add a second copy."""
    service = _FakeService([_meta(), _delta("Hel"), _delta("lo"), _done()])
    session, recorder = _FakeSession(), _FakeRecorder()

    frames = await _take_then_close(_run(service, session, recorder), None)

    assert len(frames) == 4
    assert frames[1].startswith("event: delta\ndata: ")
    assert session.calls == ["commit"]
    assert service.saved == []
    assert recorder.flushed == 1


async def test_stop_after_text_saves_what_was_already_sent() -> None:
    """Verify a client that leaves mid-answer gets the sent text saved and committed."""
    service = _FakeService([_meta(), _delta("Hel"), _delta("lo ")], hang_after=True)
    session, recorder = _FakeSession(), _FakeRecorder()

    await _take_then_close(_run(service, session, recorder), 3)

    assert service.saved == [
        {
            "conversation_id": "c1",
            "user_message": QUESTION,
            "partial_reply": "Hello ",
            "model": None,
        }
    ]
    assert session.calls == ["commit"]
    assert recorder.flushed == 1


async def test_stop_before_any_text_saves_nothing() -> None:
    """Verify stopping before the first word leaves no trace, so the question can be re-asked."""
    service = _FakeService(
        [_meta(), ChatStreamEvent(event="status", status="Searching knowledge base...")],
        hang_after=True,
    )
    session, recorder = _FakeSession(), _FakeRecorder()

    await _take_then_close(_run(service, session, recorder), 2)

    assert service.saved == []
    assert session.calls == ["rollback"]


async def test_whitespace_only_output_is_not_saved() -> None:
    """Verify an answer that is only blanks counts as no answer."""
    service = _FakeService([_meta(), _delta("  \n")], hang_after=True)
    session, recorder = _FakeSession(), _FakeRecorder()

    await _take_then_close(_run(service, session, recorder), 2)

    assert service.saved == []
    assert session.calls == ["rollback"]


async def test_error_event_discards_the_turn_even_if_text_was_sent() -> None:
    """Verify a failed turn is rolled back rather than saved as if it had been stopped."""
    error = ChatStreamEvent(event="error", detail="upstream failed")
    service = _FakeService([_meta(), _delta("partial"), error])
    session, recorder = _FakeSession(), _FakeRecorder()

    await _take_then_close(_run(service, session, recorder), None)

    assert service.saved == []
    assert session.calls == ["rollback"]


async def test_closing_exactly_at_the_done_frame_does_not_save_twice() -> None:
    """Verify a disconnect while the final frame is sent keeps the already-saved turn."""
    service = _FakeService([_meta(), _delta("Hello"), _done()])
    session, recorder = _FakeSession(), _FakeRecorder()

    await _take_then_close(_run(service, session, recorder), 3)

    assert service.saved == []
    assert session.calls == ["commit"]


async def test_save_failure_rolls_back_and_never_raises() -> None:
    """Verify a database error while saving a stopped turn cannot crash the response."""
    service = _FakeService(
        [_meta(), _delta("Hello")],
        hang_after=True,
        save_error=RuntimeError("database is locked"),
    )
    session, recorder = _FakeSession(), _FakeRecorder()

    await _take_then_close(_run(service, session, recorder), 2)

    assert session.calls == ["rollback"]
    assert recorder.flushed == 1


async def test_unsaved_stop_is_rolled_back() -> None:
    """Verify nothing is committed when the service declines to save the stopped turn."""
    service = _FakeService([_meta(), _delta("Hello")], hang_after=True, save_result=False)
    session, recorder = _FakeSession(), _FakeRecorder()

    await _take_then_close(_run(service, session, recorder), 2)

    assert session.calls == ["rollback"]


async def test_task_cancellation_still_saves_the_partial_answer() -> None:
    """Verify the save also happens when the framework cancels the response task."""
    service = _FakeService([_meta(), _delta("Hello")], hang_after=True)
    session, recorder = _FakeSession(), _FakeRecorder()
    got_text = asyncio.Event()

    async def consume() -> None:
        async for frame in _run(service, session, recorder):
            if frame.startswith("event: delta"):
                got_text.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(got_text.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [item["partial_reply"] for item in service.saved] == ["Hello"]
    assert session.calls == ["commit"]
    assert recorder.flushed == 1


def test_streamed_turn_tracks_conversation_text_and_outcome() -> None:
    """Verify the bookkeeping that decides what to do when the stream ends."""
    turn = StreamedTurn()
    status = ChatStreamEvent(event="status", status="x")
    for event in (_meta("c9"), _delta("a"), _delta("b"), status):
        turn.observe(event)

    assert turn.conversation_id == "c9"
    assert turn.text == "ab"
    assert (turn.finished, turn.failed) == (False, False)

    turn.observe(_done("c9"))
    assert turn.finished is True

    failed = StreamedTurn()
    failed.observe(ChatStreamEvent(event="error", detail="boom"))
    assert failed.failed is True


# ---- ChatService.save_interrupted_turn ---------------------------------------------------


class _FakeRepository:
    def __init__(self, known: str | None = "c1") -> None:
        self._known = known
        self.appended: list[dict[str, Any]] = []

    async def get_conversation(self, conversation_id: str, **_: Any) -> Any:
        return SimpleNamespace(id=conversation_id) if conversation_id == self._known else None

    async def append_message(self, **kwargs: Any) -> None:
        self.appended.append(kwargs)


def _service(repository: _FakeRepository) -> ChatService:
    provider = SimpleNamespace(provider_name="fake-provider")
    return ChatService(provider=provider, repository=repository)  # type: ignore[arg-type]


async def test_interrupted_turn_saves_question_and_marked_partial_answer() -> None:
    """Verify both messages are stored in order and the answer is marked as stopped."""
    repo = _FakeRepository()

    saved = await _service(repo).save_interrupted_turn(
        conversation_id="c1",
        user_message=QUESTION,
        partial_reply="Promote the replica first  \n",
        model="m-1",
    )

    assert saved is True
    assert [(m["role"], m["content"]) for m in repo.appended] == [
        ("user", QUESTION),
        ("assistant", "Promote the replica first" + STOPPED_SUFFIX),
    ]
    assistant = repo.appended[1]
    assert (assistant["provider"], assistant["model"]) == ("fake-provider", "m-1")


async def test_interrupted_turn_closes_a_code_block_the_stop_cut_open() -> None:
    """Verify an unfinished code fence is closed so the stopped marker renders as text."""
    repo = _FakeRepository()

    await _service(repo).save_interrupted_turn(
        conversation_id="c1",
        user_message=QUESTION,
        partial_reply="Run:\n```bash\nsystemctl restart vektor",
    )

    content = repo.appended[1]["content"]
    assert content == "Run:\n```bash\nsystemctl restart vektor\n```" + STOPPED_SUFFIX
    assert content.count("```") % 2 == 0
    assert repo.appended[1]["model"] == "unknown"


async def test_interrupted_turn_with_no_text_or_unknown_conversation_saves_nothing() -> None:
    """Verify the two cases where there is nothing to keep."""
    repo = _FakeRepository()
    service = _service(repo)

    empty = await service.save_interrupted_turn(
        conversation_id="c1", user_message=QUESTION, partial_reply="   "
    )
    unknown = await service.save_interrupted_turn(
        conversation_id="other", user_message=QUESTION, partial_reply="text"
    )

    assert (empty, unknown) == (False, False)
    assert repo.appended == []
