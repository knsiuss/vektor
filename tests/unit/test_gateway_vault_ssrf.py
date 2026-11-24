import pytest
from cryptography.exceptions import InvalidTag

from modules.llm_gateway.ssrf import SSRFBlockedError, validate_custom_base_url
from modules.llm_gateway.vault import (
    compute_fingerprint,
    decrypt_api_key,
    encrypt_api_key,
    redact_secrets,
)


def test_aes_gcm_envelope_encryption_and_cross_tenant_aad() -> None:
    master = "super-secret-kms-master-key"
    enc = encrypt_api_key(
        "sk-or-v1-secret-token-1234",
        master_key=master,
        tenant_id="tenant-a",
        key_id="key-1",
    )
    assert enc.last4 == "1234"
    assert "secret-token" not in enc.ciphertext
    assert enc.fingerprint == compute_fingerprint("sk-or-v1-secret-token-1234", master_key=master)

    plain = decrypt_api_key(
        enc.ciphertext,
        enc.wrapped_dek,
        master_key=master,
        tenant_id="tenant-a",
        key_id="key-1",
    )
    assert plain == "sk-or-v1-secret-token-1234"

    # Cross-tenant AAD mismatch must fail decryption.
    with pytest.raises(InvalidTag):
        decrypt_api_key(
            enc.ciphertext,
            enc.wrapped_dek,
            master_key=master,
            tenant_id="tenant-b",
            key_id="key-1",
        )


def test_secret_redaction_and_anti_ssrf() -> None:
    masked = redact_secrets("Authorization Bearer sk-proj-abc1234567890xyz failed")
    assert "abc1234567890xyz" not in masked
    assert "[REDACTED_KEY]" in masked

    with pytest.raises(SSRFBlockedError):
        validate_custom_base_url("http://api.openai.com/v1")

    with pytest.raises(SSRFBlockedError):
        validate_custom_base_url("https://169.254.169.254/latest/meta-data")

    with pytest.raises(SSRFBlockedError):
        validate_custom_base_url("https://127.0.0.1:11434/v1", allow_local=False)

    assert (
        validate_custom_base_url("http://127.0.0.1:11434/v1", allow_local=True)
        == "http://127.0.0.1:11434/v1"
    )
