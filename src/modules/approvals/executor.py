from collections.abc import Awaitable, Callable
from typing import Any

from modules.approvals.models import ActionApproval
from modules.approvals.repository import ApprovalStateError, validate_approval_transition

ActionHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ActionExecutionError(Exception):
    """Raised when an approved action cannot be executed."""


class ActionExecutorRegistry:
    """Scoped registry of executable write actions guarded by Approval Gate."""

    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, tool_name: str, handler: ActionHandler) -> None:
        self._handlers[tool_name] = handler

    async def execute(self, approval: ActionApproval) -> dict[str, Any]:
        """Execute an action strictly after it has been human-approved."""
        validate_approval_transition(approval.status, "executed")
        handler = self._handlers.get(approval.tool_name)
        if handler is None:
            raise ActionExecutionError(f"No executor registered for tool {approval.tool_name!r}.")
        return await handler(approval.arguments)


def ensure_executable(approval: ActionApproval) -> None:
    if approval.status != "approved":
        raise ApprovalStateError(f"Approval must be 'approved', got {approval.status!r}.")
