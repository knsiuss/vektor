import hashlib
import hmac

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from modules.channels.security import (
    decrypt_channel_config,
    encrypt_channel_config,
    verify_discord_signature,
    verify_meta_signature,
)


def test_encrypt_and_decrypt_channel_config_roundtrip() -> None:
    master_key = "test-master-key-for-vektor-channels"
    original = {
        "bot_token": "123456:ABCDEF_secret_token_value",
        "verify_token": "plain-verify",
    }
    encrypted = encrypt_channel_config(
        original,
        master_key=master_key,
        tenant_id="tenant-1",
        connector_id="conn-1",
    )
    assert encrypted["bot_token"].startswith("enc:v1:")
    assert "ABCDEF_secret_token_value" not in encrypted["bot_token"]
    assert encrypted["verify_token"] == "plain-verify"

    decrypted = decrypt_channel_config(
        encrypted,
        master_key=master_key,
        tenant_id="tenant-1",
        connector_id="conn-1",
    )
    assert decrypted == original


def test_verify_meta_signature() -> None:
    body = b'{"entry":[]}'
    secret = "meta-app-secret"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_meta_signature(body, sig, secret) is True
    assert verify_meta_signature(body, "sha256=bad", secret) is False


def test_verify_discord_signature() -> None:
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    ts = "1700000000"
    body = b'{"type":1}'
    sig_hex = priv.sign(ts.encode() + body).hex()
    assert verify_discord_signature(body, sig_hex, ts, pub_hex) is True
    assert verify_discord_signature(body, "00" * 64, ts, pub_hex) is False
