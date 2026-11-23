class ModelGatewayError(Exception):
    """Base exception for all LLM provider and gateway failures."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class ProviderAuthenticationError(ModelGatewayError):
    """Raised when provider credentials are missing, expired, or rejected."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=False)


class ProviderRateLimitError(ModelGatewayError):
    """Raised when the LLM provider rejects a request due to rate or quota limits."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=True)


class ProviderTimeoutError(ModelGatewayError):
    """Raised when an LLM provider request exceeds the configured timeout."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=True)


class ProviderResponseError(ModelGatewayError):
    """Raised when a provider returns an HTTP error or malformed/untrusted payload."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message, provider=provider, retryable=retryable)
