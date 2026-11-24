from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from modules.llm_gateway.errors import classify_error
from modules.llm_gateway.registry import ModelCaps, ModelRegistryService
from modules.model_gateway.schemas import TokenUsage


async def test_model_registry_gating_cost_and_error_matrix() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            svc = ModelRegistryService(session)
            verified = await svc.upsert_model(
                model_id="openai/gpt-4o-mini",
                provider="openrouter",
                caps=ModelCaps(tool_calling=True, structured_output=True, caching=True),
                price_in_micros=150_000,
                price_out_micros=600_000,
                price_cache_read_micros=75_000,
                status="verified",
                eval_score=0.96,
            )
            experimental = await svc.upsert_model(
                model_id="liquid/lfm-3-1.7b:free",
                provider="openrouter",
                caps=ModelCaps(tool_calling=True, structured_output=False, caching=False),
                status="experimental",
            )
            blocked = await svc.upsert_model(
                model_id="legacy/deprecated-model",
                provider="openai",
                status="blocked",
            )

            d_ok = svc.check_capabilities(verified, needs_tools=True, requested_mutating=True)
            assert d_ok.allowed is True
            assert d_ok.allow_mutating_tools is True

            d_exp = svc.check_capabilities(experimental, needs_tools=True, requested_mutating=True)
            assert d_exp.allowed is True
            assert d_exp.allow_mutating_tools is False
            assert d_exp.warning is not None

            d_blk = svc.check_capabilities(blocked)
            assert d_blk.allowed is False

            usage = TokenUsage(
                prompt_tokens=1_000_000,
                completion_tokens=1_000_000,
                total_tokens=2_000_000,
                cached_tokens=500_000,
            )
            # 500k uncached in (75k) + 500k cached read (37.5k) + 1M out (600k) = 712,500 micros
            assert svc.estimate_cost_micros(usage, verified) == 712_500

            err_byok = classify_error(401, "Invalid key", key_mode="byok")
            assert err_byok.category == "AUTH"
            assert "rotate" in err_byok.user_action.lower()

            err_managed = classify_error(402, "Quota exceeded", key_mode="managed")
            assert err_managed.category == "QUOTA"
            assert "support" in err_managed.user_action.lower()
    finally:
        await engine.dispose()
