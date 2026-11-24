from modules.channels.adapters import (
    parse_discord_interaction,
    parse_telegram_update,
    parse_whatsapp_webhook,
)


def test_parse_telegram_update() -> None:
    msg = parse_telegram_update(
        {"message": {"text": "Halo toko!", "chat": {"id": 123}, "from": {"id": 456}}}
    )
    assert msg is not None
    assert msg.external_user_id == "456"
    assert msg.reply_target_id == "123"
    assert msg.text == "Halo toko!"
    assert parse_telegram_update({"message": {"chat": {"id": 123}}}) is None


def test_parse_whatsapp_cloud_and_qr() -> None:
    qr = parse_whatsapp_webhook({"payload": {"from": "628123@c.us", "body": "Cek stok"}})
    assert qr is not None
    assert qr.external_user_id == "628123@c.us"
    assert qr.text == "Cek stok"

    cloud = parse_whatsapp_webhook(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "628999",
                                        "type": "text",
                                        "text": {"body": "Harga?"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    )
    assert cloud is not None
    assert cloud.external_user_id == "628999"
    assert cloud.text == "Harga?"


def test_parse_discord_interaction() -> None:
    msg = parse_discord_interaction(
        {
            "channel_id": "ch_1",
            "member": {"user": {"id": "u_9"}},
            "data": {"options": [{"name": "question", "value": "Cara order?"}]},
        }
    )
    assert msg is not None
    assert msg.external_user_id == "u_9"
    assert msg.reply_target_id == "ch_1"
    assert msg.text == "Cara order?"
