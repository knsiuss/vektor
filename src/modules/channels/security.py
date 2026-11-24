import hashlib
import hmac
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from modules.llm_gateway.vault import decrypt_api_key, encrypt_api_key

SENSITIVE_CONFIG_KEYS = frozenset({"bot_token", "access_token", "api_key", "app_secret"})
_ENC_PREFIX = "enc:v1:"


def encrypt_channel_config(
    config: dict[str, str],
    *,
    master_key: str,
    tenant_id: str,
    connector_id: str,
) -> dict[str, str]:
    """Envelope-encrypt sensitive channel credentials before DB persistence."""
    if not master_key.strip():
        return dict(config)

    result: dict[str, str] = {}
    for key, value in config.items():
        should_encrypt = (
            key in SENSITIVE_CONFIG_KEYS
            and len(value.strip()) >= 8
            and not value.startswith(_ENC_PREFIX)
        )
        if should_encrypt:
            bundle = encrypt_api_key(
                value,
                master_key=master_key,
                tenant_id=tenant_id,
                key_id=f"{connector_id}:{key}",
            )
            result[key] = f"{_ENC_PREFIX}{bundle.wrapped_dek}:{bundle.ciphertext}"
        else:
            result[key] = value
    return result


def decrypt_channel_config(
    config: dict[str, Any],
    *,
    master_key: str,
    tenant_id: str,
    connector_id: str,
) -> dict[str, str]:
    """Decrypt sensitive channel credentials for outbound API calls."""
    result: dict[str, str] = {}
    for key, raw in config.items():
        value = str(raw)
        if value.startswith(_ENC_PREFIX) and master_key.strip():
            parts = value[len(_ENC_PREFIX) :].split(":", 1)
            if len(parts) == 2:
                wrapped_dek, ciphertext = parts
                result[key] = decrypt_api_key(
                    ciphertext=ciphertext,
                    wrapped_dek=wrapped_dek,
                    master_key=master_key,
                    tenant_id=tenant_id,
                    key_id=f"{connector_id}:{key}",
                )
                continue
        result[key] = value
    return result


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Verify Meta WhatsApp X-Hub-Signature-256 HMAC header."""
    if not signature_header or not app_secret:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header[len(prefix) :], expected)


def verify_discord_signature(
    raw_body: bytes,
    signature_hex: str | None,
    timestamp: str | None,
    public_key_hex: str,
) -> bool:
    """Verify Discord Interactions Ed25519 signature header."""
    if not signature_hex or not timestamp or not public_key_hex:
        return False
    try:
        pub_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        pub_key.verify(bytes.fromhex(signature_hex), timestamp.encode("utf-8") + raw_body)
        return True
    except (ValueError, InvalidSignature):
        return False
