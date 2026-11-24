from dataclasses import dataclass
from typing import Literal

GatewayErrorCategory = Literal["AUTH", "RATE_LIMIT", "QUOTA", "CONTEXT", "SERVER", "UNKNOWN"]


@dataclass(frozen=True, slots=True)
class NormalizedGatewayError:
    """Normalized provider failure with BYOK vs Managed remediation guidance."""

    category: GatewayErrorCategory
    message: str
    retryable: bool
    user_action: str


def classify_error(
    status_code: int,
    detail: str,
    *,
    key_mode: Literal["byok", "managed"],
) -> NormalizedGatewayError:
    """Map upstream HTTP errors into actionable BYOK vs Managed responses."""
    lower = detail.lower()
    if status_code in (401, 403):
        action = (
            "Your API key was rejected (marked invalid). Please rotate or replace your key."
            if key_mode == "byok"
            else "Platform key authentication failed; rotating pool key."
        )
        return NormalizedGatewayError("AUTH", detail or "Authentication failed.", False, action)

    if status_code == 429:
        return NormalizedGatewayError(
            "RATE_LIMIT",
            detail or "Provider rate limit exceeded.",
            True,
            "Wait briefly and retry.",
        )

    if status_code == 402 or "quota" in lower or "insufficient" in lower or "credit" in lower:
        action = (
            "Provider balance exhausted. Top up your provider or enable credit fallback."
            if key_mode == "byok"
            else "Platform quota alert; please contact support or retry shortly."
        )
        return NormalizedGatewayError("QUOTA", detail or "Quota exceeded.", False, action)

    if status_code == 400 and ("context" in lower or "token" in lower or "length" in lower):
        return NormalizedGatewayError(
            "CONTEXT",
            detail or "Context length exceeded.",
            True,
            "Compact conversation history and retry.",
        )

    if status_code >= 500:
        return NormalizedGatewayError(
            "SERVER",
            detail or f"Upstream server error ({status_code}).",
            True,
            "Retry or fall back to an equivalent verified model.",
        )

    return NormalizedGatewayError("UNKNOWN", detail or "Unknown upstream error.", False, "Retry.")
