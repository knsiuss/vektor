from typing import Any

import httpx

from modules.channels.schemas import InboundMessage


def parse_telegram_update(payload: dict[str, Any]) -> InboundMessage | None:
    """Extract normalized message from a Telegram Bot API webhook update."""
    message = payload.get("message") or payload.get("edited_message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    chat = message.get("chat")
    sender = message.get("from")
    if not isinstance(text, str) or not text.strip() or not isinstance(chat, dict):
        return None
    chat_id = str(chat.get("id", ""))
    user_id = str(sender.get("id", chat_id)) if isinstance(sender, dict) else chat_id
    if not chat_id:
        return None
    event_id = str(payload["update_id"]) if "update_id" in payload else None
    return InboundMessage(
        external_user_id=user_id,
        reply_target_id=chat_id,
        text=text.strip(),
        external_event_id=event_id,
    )


def parse_whatsapp_webhook(payload: dict[str, Any]) -> InboundMessage | None:
    """Extract normalized message from WhatsApp Cloud API or WAHA/Evolution QR bridge."""
    # WAHA / Evolution QR bridge flat format
    if "payload" in payload and isinstance(payload["payload"], dict):
        inner = payload["payload"]
        sender = str(inner.get("from", ""))
        body = inner.get("body")
        if sender and isinstance(body, str) and body.strip():
            event_id = str(inner["id"]) if "id" in inner else None
            return InboundMessage(
                external_user_id=sender,
                reply_target_id=sender,
                text=body.strip(),
                external_event_id=event_id,
            )

    # Meta WhatsApp Cloud API nested format
    entries = payload.get("entry")
    if not isinstance(entries, list) or not entries:
        return None
    changes = entries[0].get("changes") if isinstance(entries[0], dict) else None
    if not isinstance(changes, list) or not changes:
        return None
    value = changes[0].get("value") if isinstance(changes[0], dict) else None
    messages = value.get("messages") if isinstance(value, dict) else None
    if not isinstance(messages, list) or not messages:
        return None
    msg = messages[0]
    if not isinstance(msg, dict) or msg.get("type") != "text":
        return None
    sender = str(msg.get("from", ""))
    text_obj = msg.get("text")
    body = text_obj.get("body") if isinstance(text_obj, dict) else None
    if not sender or not isinstance(body, str) or not body.strip():
        return None
    event_id = str(msg["id"]) if "id" in msg else None
    return InboundMessage(
        external_user_id=sender,
        reply_target_id=sender,
        text=body.strip(),
        external_event_id=event_id,
    )


def parse_discord_interaction(payload: dict[str, Any]) -> InboundMessage | None:
    """Extract normalized message from a Discord Interaction slash-command payload."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    options = data.get("options")
    text = ""
    if isinstance(options, list):
        for opt in options:
            if isinstance(opt, dict) and isinstance(opt.get("value"), str):
                text = opt["value"].strip()
                break
    if not text:
        return None
    member = payload.get("member")
    user = member.get("user") if isinstance(member, dict) else payload.get("user")
    user_id = str(user.get("id", "unknown")) if isinstance(user, dict) else "unknown"
    channel_id = str(payload.get("channel_id", user_id))
    event_id = str(payload["id"]) if "id" in payload else None
    return InboundMessage(
        external_user_id=user_id,
        reply_target_id=channel_id,
        text=text,
        external_event_id=event_id,
    )


async def send_telegram_reply(
    client: httpx.AsyncClient,
    bot_token: str,
    chat_id: str,
    text: str,
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    await client.post(url, json={"chat_id": chat_id, "text": text[:4096]}, timeout=15.0)


async def send_whatsapp_cloud_reply(
    client: httpx.AsyncClient,
    phone_number_id: str,
    access_token: str,
    to: str,
    text: str,
) -> None:
    url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
    await client.post(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        json={"messaging_product": "whatsapp", "to": to, "text": {"body": text[:4096]}},
        timeout=15.0,
    )


async def send_whatsapp_qr_reply(
    client: httpx.AsyncClient,
    bridge_url: str,
    api_key: str,
    chat_id: str,
    text: str,
) -> None:
    url = f"{bridge_url.rstrip('/')}/api/sendText"
    headers = {"X-Api-Key": api_key} if api_key else {}
    await client.post(
        url,
        headers=headers,
        json={"chatId": chat_id, "text": text[:4096], "session": "default"},
        timeout=15.0,
    )
