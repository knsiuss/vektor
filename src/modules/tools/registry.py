import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from modules.tools.schemas import ToolDefinition, ToolExecutionRecord

ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]

_logger = logging.getLogger(__name__)


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

        parsed_args = _parse_arguments(raw_arguments)
        if parsed_args is None:
            return ToolExecutionRecord(
                call_id=call_id,
                tool_name=tool_name,
                arguments={},
                status="error",
                output="Malformed JSON arguments passed to tool.",
            )

        if entry.definition.risk_level == "mutating" and not allow_mutating:
            # Keep the arguments so the UI can show what would run before approving.
            preview = json.dumps(parsed_args, ensure_ascii=False)[:400] or "{}"
            return ToolExecutionRecord(
                call_id=call_id,
                tool_name=tool_name,
                arguments=parsed_args,
                status="blocked",
                output=(
                    f"Tool '{tool_name}' requires explicit approval "
                    f"(allow_mutating_tools=True). Preview: {preview}"
                ),
            )

        try:
            result = await entry.handler(parsed_args)
            return ToolExecutionRecord(
                call_id=call_id,
                tool_name=tool_name,
                arguments=parsed_args,
                status="success",
                output=result,
                ui_resource_uri=entry.definition.ui_resource_uri,
            )
        except Exception:
            # The model sees a generic failure; details stay in the server log so an
            # upstream error cannot leak hostnames or credentials into a prompt.
            _logger.exception("tool execution failed tool=%s call=%s", tool_name, call_id)
            return ToolExecutionRecord(
                call_id=call_id,
                tool_name=tool_name,
                arguments=parsed_args,
                status="error",
                output="Tool execution failed. The error was logged.",
            )


def _parse_arguments(raw_arguments: str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    try:
        loaded = json.loads(raw_arguments or "{}")
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None
