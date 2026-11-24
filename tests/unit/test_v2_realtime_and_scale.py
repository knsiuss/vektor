import asyncio

import pytest

from core.shared_store import InMemoryTTLStore
from modules.approvals.executor import ActionExecutorRegistry
from modules.approvals.models import ActionApproval
from modules.approvals.repository import ApprovalStateError
from modules.channels.dedup import WebhookDeduplicator
from modules.channels.event_bus import InboxEventBus
from modules.knowledge.sync import extract_plain_text


@pytest.mark.asyncio
async def test_inbox_event_bus_tenant_isolation() -> None:
    bus = InboxEventBus()
    stream_a = bus.subscribe("tenant-a")
    stream_b = bus.subscribe("tenant-b")

    task_a = asyncio.create_task(anext(stream_a))
    task_b = asyncio.create_task(anext(stream_b))
    await asyncio.sleep(0.02)

    await bus.publish("tenant-a", "inbox.message", {"session_id": "s1"})
    frame_a = await asyncio.wait_for(task_a, timeout=1.0)
    assert "event: inbox.message" in frame_a
    assert '"session_id": "s1"' in frame_a
    assert not task_b.done()
    task_b.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_b
    await stream_a.aclose()
    await stream_b.aclose()


def test_shared_ttl_store_and_dedup() -> None:
    store = InMemoryTTLStore(max_entries=10)
    dedup = WebhookDeduplicator(ttl_seconds=60.0, store=store)
    assert dedup.mark_if_new("c1", "e1") is True
    assert dedup.mark_if_new("c1", "e1") is False


@pytest.mark.asyncio
async def test_action_executor_requires_approved_status() -> None:
    reg = ActionExecutorRegistry()

    async def _ok(args: dict[str, object]) -> dict[str, object]:
        return {"ran": True, "echo": args}

    reg.register("create_ticket", _ok)

    pending = ActionApproval(
        tenant_id="t1", tool_name="create_ticket", arguments={"id": 1}, status="pending"
    )
    with pytest.raises(ApprovalStateError):
        await reg.execute(pending)

    approved = ActionApproval(
        tenant_id="t1", tool_name="create_ticket", arguments={"id": 1}, status="approved"
    )
    res = await reg.execute(approved)
    assert res == {"ran": True, "echo": {"id": 1}}


def test_extract_plain_text_strips_html_and_scripts() -> None:
    html = (
        "<html><head><script>alert(1)</script></head>"
        "<body><h1>Halo</h1><p>Dunia</p></body></html>"
    )
    assert extract_plain_text(html) == "Halo Dunia"
