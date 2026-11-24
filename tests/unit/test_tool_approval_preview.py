from typing import Any

from modules.tools.registry import ToolRegistry
from modules.tools.schemas import ToolDefinition


def _registry(handler) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="restart_service",
            description="Restart one service by name.",
            parameters_schema={
                "type": "object",
                "properties": {"service": {"type": "string"}},
                "required": ["service"],
            },
            risk_level="mutating",
        ),
        handler,
    )
    return registry


async def test_blocked_mutation_keeps_arguments_for_the_approval_preview() -> None:
    """Verify a blocked mutating tool reports what it would have run."""
    calls: list[dict[str, Any]] = []

    async def _handler(args: dict[str, Any]) -> str:
        calls.append(args)
        return "restarted"

    record = await _registry(_handler).execute(
        call_id="c1",
        tool_name="restart_service",
        raw_arguments='{"service": "api"}',
    )

    assert record.status == "blocked"
    assert record.arguments == {"service": "api"}
    assert '"service": "api"' in record.output
    assert "allow_mutating_tools" in record.output
    assert calls == []


async def test_approved_mutation_runs_and_returns_output() -> None:
    """Verify the same tool executes once the caller explicitly allows mutations."""

    async def _handler(args: dict[str, Any]) -> str:
        return f"restarted {args['service']}"

    record = await _registry(_handler).execute(
        call_id="c1",
        tool_name="restart_service",
        raw_arguments={"service": "worker"},
        allow_mutating=True,
    )

    assert record.status == "success"
    assert record.output == "restarted worker"
    assert record.arguments == {"service": "worker"}


async def test_malformed_arguments_fail_before_the_risk_gate() -> None:
    """Verify broken JSON is reported as an error even for a mutating tool."""

    async def _handler(args: dict[str, Any]) -> str:
        return "unreachable"

    record = await _registry(_handler).execute(
        call_id="c1",
        tool_name="restart_service",
        raw_arguments="{not json",
    )

    assert record.status == "error"
    assert record.arguments == {}
