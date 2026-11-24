from api.routers.channel_analytics import compute_deflection_rate
from modules.channels.adapters import (
    parse_discord_interaction,
    parse_telegram_update,
    parse_whatsapp_webhook,
)
from modules.channels.dedup import WebhookDeduplicator


def test_webhook_deduplicator_blocks_duplicate_events() -> None:
    dedup = WebhookDeduplicator(ttl_seconds=60.0)
    assert dedup.mark_if_new("conn_1", "evt_100") is True
    assert dedup.mark_if_new("conn_1", "evt_100") is False
    assert dedup.mark_if_new("conn_2", "evt_100") is True
    assert dedup.mark_if_new("conn_1", None) is True


def test_adapters_extract_external_event_ids() -> None:
    tg = parse_telegram_update(
        {"update_id": 999, "message": {"text": "Hi", "chat": {"id": 1}, "from": {"id": 2}}}
    )
    assert tg is not None and tg.external_event_id == "999"

    wa = parse_whatsapp_webhook({"payload": {"id": "wamid_1", "from": "6281", "body": "Halo"}})
    assert wa is not None and wa.external_event_id == "wamid_1"

    dc = parse_discord_interaction(
        {
            "id": "inter_7",
            "channel_id": "ch_1",
            "member": {"user": {"id": "u_1"}},
            "data": {"options": [{"name": "q", "value": "Test"}]},
        }
    )
    assert dc is not None and dc.external_event_id == "inter_7"


def test_compute_deflection_rate() -> None:
    assert compute_deflection_rate(0, 0) == 1.0
    assert compute_deflection_rate(10, 2) == 0.8
    assert compute_deflection_rate(5, 5) == 0.0
