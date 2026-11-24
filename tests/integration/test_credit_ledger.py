from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from api.main import create_app
from core.config.settings import Settings
from core.database import Base, create_engine, create_session_factory
from modules.billing.ledger import CreditLedgerService, InsufficientCreditsError


async def test_double_entry_credit_ledger_reserve_settle_release_and_expire() -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)

    try:
        async with factory() as session:
            ledger = CreditLedgerService(session)
            await ledger.grant_credits(tenant_id="t1", amount_micros=1_000_000, ref_id="grant-1")
            assert await ledger.get_balance_micros("t1") == 1_000_000

            res1 = await ledger.reserve(tenant_id="t1", hold_micros=600_000)
            assert await ledger.get_balance_micros("t1") == 400_000

            with pytest.raises(InsufficientCreditsError):
                await ledger.reserve(tenant_id="t1", hold_micros=500_000)

            # Settle 250k with 10% markup = 275k -> 325k returned
            charge = await ledger.settle(res1.id, actual_cost_micros=250_000, markup_pct=0.10)
            assert charge == 275_000
            assert await ledger.get_balance_micros("t1") == 725_000

            res2 = await ledger.reserve(tenant_id="t1", hold_micros=200_000)
            assert await ledger.get_balance_micros("t1") == 525_000
            await ledger.release(res2.id)
            assert await ledger.get_balance_micros("t1") == 725_000

            res3 = await ledger.reserve(tenant_id="t1", hold_micros=100_000, ttl_seconds=1)
            expired = await ledger.expire_stale_reservations(
                now=datetime.now(UTC) + timedelta(seconds=5)
            )
            assert expired == 1
            assert res3.status == "released"
            assert await ledger.get_balance_micros("t1") == 725_000
    finally:
        await engine.dispose()


async def test_keys_policy_and_credits_api_end_to_end(tmp_path: Path) -> None:
    db_file = tmp_path / "vault_api.db"
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        llm_embedding_model="local",
        kms_master_key="test-kms-secret",
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            k = await client.post(
                "/api/v1/keys",
                json={
                    "provider": "openrouter",
                    "label": "Main OR",
                    "api_key": "sk-or-v1-abcdefghijklmnop",
                },
            )
            assert k.status_code == 201
            assert k.json()["last4"] == "mnop"
            assert "abcdefghijklmnop" not in k.text

            # Duplicate key rejected
            dup = await client.post(
                "/api/v1/keys",
                json={
                    "provider": "openrouter",
                    "label": "Dup",
                    "api_key": "sk-or-v1-abcdefghijklmnop",
                },
            )
            assert dup.status_code == 409

            # SSRF blocked
            ssrf = await client.post(
                "/api/v1/keys",
                json={
                    "provider": "custom",
                    "label": "Bad",
                    "api_key": "sk-custom-1234567890",
                    "base_url": "https://169.254.169.254/latest",
                },
            )
            assert ssrf.status_code == 400

            # Grant & balance
            grant = await client.post(
                "/api/v1/credits/grant",
                json={"amount_micros": 500_000, "ref_id": "trial-1"},
            )
            assert grant.status_code == 201
            assert grant.json()["balance_micros"] == 500_000
