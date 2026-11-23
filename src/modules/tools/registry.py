import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from modules.tools.schemas import ToolDefinition, ToolExecutionRecord

ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class RegisteredTool:
    """Pairs a validated ToolDefinition with its async execution handler."""

    definition: ToolDefinition
    handler: ToolHandler


class ToolRegistry:
    """Allowlisted registry enforcing risk-tier guardrails before tool execution."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        """Register an executable tool under its unique name."""
        self._tools[definition.name] = RegisteredTool(definition=definition, handler=handler)

    def list_definitions(self, *, include_mutating: bool = False) -> list[ToolDefinition]:
        """Return tool schemas visible to the model for the current permission scope."""
        return [
            entry.definition
            for entry in self._tools.values()
            if include_mutating or entry.definition.risk_level == "read"
        ]

    async def execute(
        self,
        *,
        call_id: str,
        tool_name: str,
        raw_arguments: str | dict[str, Any],
        allow_mutating: bool = False,
    ) -> ToolExecutionRecord:
        """Validate allowlist, risk level, and JSON arguments before running a tool."""
        entry = self._tools.get(tool_name)
        if entry is None:
            return ToolExecutionRecord(
                call_id=call_id,
                tool_name=tool_name,
                arguments={},
                status="blocked",
                output=f"Tool '{tool_name}' is not in the allowlist.",
            )

        if entry.definition.risk_level == "mutating" and not allow_mutating:
            return ToolExecutionRecord(
                call_id=call_id,
                tool_name=tool_name,
                arguments={},
                status="blocked",
                output=(
                    f"Tool '{tool_name}' requires explicit approval (allow_mutating_tools=True)."
                ),
            )

        parsed_args = _parse_arguments(raw_arguments)
        if parsed_args is None:
            return ToolExecutionRecord(
                call_id=call_id,
                tool_name=tool_name,
                arguments={},
                status="error",
                output="Malformed JSON arguments passed to tool.",
            )

        try:
            result = await entry.handler(parsed_args)
            return ToolExecutionRecord(
                call_id=call_id,
                tool_name=tool_name,
                arguments=parsed_args,
                status="success",
                output=result,
            )
        except Exception as exc:
            return ToolExecutionRecord(
                call_id=call_id,
                tool_name=tool_name,
                arguments=parsed_args,
                status="error",
                output=f"Tool execution failed: {exc}",
            )


def _parse_arguments(raw_arguments: str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    try:
        loaded = json.loads(raw_arguments or "{}")
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None
