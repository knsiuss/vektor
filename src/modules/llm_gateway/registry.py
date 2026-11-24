import json
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.llm_gateway.models import ModelRegistryEntry
from modules.model_gateway.schemas import TokenUsage

ModelStatus = Literal["verified", "experimental", "blocked"]


@dataclass(frozen=True, slots=True)
class ModelCaps:
    """Supported capabilities declared by a registered model."""

    tool_calling: bool = True
    structured_output: bool = True
    caching: bool = False


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    """Result of capability & support-tier gating before an LLM call."""

    allowed: bool
    allow_mutating_tools: bool
    warning: str | None = None
    reason: str | None = None


class ModelRegistryService:
    """Manages versioned model pricing, support tiers, and capability gating."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_model(self, model_id: str) -> ModelRegistryEntry | None:
        stmt = select(ModelRegistryEntry).where(ModelRegistryEntry.id == model_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def upsert_model(
        self,
        *,
        model_id: str,
        provider: str,
        tier: str = "standard",
        context_window: int = 128000,
        caps: ModelCaps | None = None,
        price_in_micros: int = 0,
        price_out_micros: int = 0,
        price_cache_write_micros: int = 0,
        price_cache_read_micros: int = 0,
        status: ModelStatus = "verified",
        eval_score: float | None = None,
    ) -> ModelRegistryEntry:
        resolved_caps = caps or ModelCaps()
        caps_str = json.dumps(
            {
                "tool_calling": resolved_caps.tool_calling,
                "structured_output": resolved_caps.structured_output,
                "caching": resolved_caps.caching,
            }
        )
        entry = await self.get_model(model_id)
        if entry is None:
            entry = ModelRegistryEntry(
                id=model_id,
                provider=provider,
                tier=tier,
                context_window=context_window,
                caps_json=caps_str,
                price_in_micros=price_in_micros,
                price_out_micros=price_out_micros,
                price_cache_write_micros=price_cache_write_micros,
                price_cache_read_micros=price_cache_read_micros,
                status=status,
                eval_score=eval_score,
            )
            self._session.add(entry)
        else:
            entry.provider = provider
            entry.tier = tier
            entry.context_window = context_window
            entry.caps_json = caps_str
            entry.price_in_micros = price_in_micros
            entry.price_out_micros = price_out_micros
            entry.price_cache_write_micros = price_cache_write_micros
            entry.price_cache_read_micros = price_cache_read_micros
            entry.status = status
            entry.eval_score = eval_score
        await self._session.flush()
        return entry

    @staticmethod
    def check_capabilities(
        entry: ModelRegistryEntry,
        *,
        needs_tools: bool = False,
        needs_structured: bool = False,
        requested_mutating: bool = False,
    ) -> CapabilityDecision:
        if entry.status == "blocked":
            return CapabilityDecision(
                allowed=False,
                allow_mutating_tools=False,
                reason=f"Model '{entry.id}' is blocked or deprecated.",
            )

        raw_caps = json.loads(entry.caps_json or "{}")
        if needs_tools and not raw_caps.get("tool_calling", False):
            return CapabilityDecision(
                allowed=False,
                allow_mutating_tools=False,
                reason=f"Model '{entry.id}' does not support tool calling.",
            )
        if needs_structured and not raw_caps.get("structured_output", False):
            return CapabilityDecision(
                allowed=False,
                allow_mutating_tools=False,
                reason=f"Model '{entry.id}' does not support structured output.",
            )

        if entry.status == "experimental":
            return CapabilityDecision(
                allowed=True,
                allow_mutating_tools=False,
                warning=(
                    f"Model '{entry.id}' is experimental (not yet verified by eval). "
                    "Mutating tools are disabled."
                    if requested_mutating
                    else f"Model '{entry.id}' is experimental (not yet verified by eval)."
                ),
            )

        return CapabilityDecision(allowed=True, allow_mutating_tools=requested_mutating)

    @staticmethod
    def estimate_cost_micros(usage: TokenUsage, entry: ModelRegistryEntry) -> int:
        """Calculate token cost in micro-USD using versioned per-1M-token rates."""
        billable_in = max(0, usage.prompt_tokens - usage.cached_tokens)
        cost = (
            billable_in * entry.price_in_micros
            + usage.completion_tokens * entry.price_out_micros
            + usage.cache_creation_tokens * entry.price_cache_write_micros
            + usage.cached_tokens * entry.price_cache_read_micros
        )
        return (cost + 999_999) // 1_000_000 if cost > 0 else 0
