import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_SECRET_PATTERN = re.compile(r"\b(?:sk|vk|pa|rk)-[A-Za-z0-9_-]{12,}\b")


@dataclass(frozen=True, slots=True)
class EncryptedKey:
    """Envelope-encrypted API key bundle safe for database persistence."""

    ciphertext: str
    wrapped_dek: str
    last4: str
    fingerprint: str


def _derive_kek(master_key: str) -> bytes:
    if not master_key.strip():
        raise ValueError("KMS master key must not be empty.")
    return hashlib.sha256(master_key.encode("utf-8")).digest()


def compute_fingerprint(plaintext: str, *, master_key: str) -> str:
    """Compute a keyed HMAC-SHA256 digest to detect duplicate keys without plaintext."""
    kek = _derive_kek(master_key)
    return hmac.new(kek, plaintext.encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_api_key(
    plaintext: str,
    *,
    master_key: str,
    tenant_id: str,
    key_id: str,
) -> EncryptedKey:
    """Encrypt an API key with a random DEK wrapped by the deployment KEK and tenant AAD."""
    clean = plaintext.strip()
    if len(clean) < 8:
        raise ValueError("API key is too short.")

    kek = _derive_kek(master_key)
    dek = os.urandom(32)
    aad = f"{tenant_id}:{key_id}".encode()

    dek_nonce = os.urandom(12)
    wrapped = dek_nonce + AESGCM(kek).encrypt(dek_nonce, dek, aad)

    key_nonce = os.urandom(12)
    cipher = key_nonce + AESGCM(dek).encrypt(key_nonce, clean.encode("utf-8"), aad)

    return EncryptedKey(
        ciphertext=base64.urlsafe_b64encode(cipher).decode("ascii"),
        wrapped_dek=base64.urlsafe_b64encode(wrapped).decode("ascii"),
        last4=clean[-4:],
        fingerprint=compute_fingerprint(clean, master_key=master_key),
    )


def decrypt_api_key(
    ciphertext: str,
    wrapped_dek: str,
    *,
    master_key: str,
    tenant_id: str,
    key_id: str,
) -> str:
    """Unwrap DEK and decrypt an API key, verifying tenant_id:key_id AAD binding."""
    kek = _derive_kek(master_key)
    aad = f"{tenant_id}:{key_id}".encode()

    wrapped_raw = base64.urlsafe_b64decode(wrapped_dek.encode("ascii"))
    dek = AESGCM(kek).decrypt(wrapped_raw[:12], wrapped_raw[12:], aad)

    cipher_raw = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    plain = AESGCM(dek).decrypt(cipher_raw[:12], cipher_raw[12:], aad)
    return plain.decode("utf-8")


def redact_secrets(text: str) -> str:
    """Mask common provider API key patterns before logging or tracing."""
    return _SECRET_PATTERN.sub("[REDACTED_KEY]", text)
