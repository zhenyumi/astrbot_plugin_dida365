from __future__ import annotations


class DidaError(Exception):
    """Base exception for the Dida365 plugin."""


class DidaConfigurationError(DidaError):
    """Raised when required plugin configuration is missing."""


class DidaNetworkError(DidaError):
    """Raised when the plugin cannot reach the Dida365 API."""


class DidaApiError(DidaError):
    """Raised when the Dida365 API returns an error response."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        payload: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


class DidaAuthenticationError(DidaApiError):
    """Raised when the Dida365 API rejects the provided credentials."""


class DidaNotFoundError(DidaApiError):
    """Raised when a requested Dida365 resource does not exist."""



class DidaLlmIntentError(DidaError):
    """Raised when the LLM intent output is missing or malformed."""


class DidaValidationError(DidaError):
    """Raised when plugin-side validation fails for a parsed intent."""


class DidaConfirmationError(DidaError):
    """Raised when a confirmation step is required, missing, or expired."""
