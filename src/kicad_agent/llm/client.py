"""Anthropic client wrapper with configuration and graceful error handling.

Provides LLMClient as a singleton-style wrapper around the Anthropic SDK,
reading API key from environment and model from optional configuration.

Security (threat model):
  T-15-03: API key from environment variable only; never logged or included in error messages.
"""

from __future__ import annotations

import os
from typing import Any


class LLMConfigError(Exception):
    """Raised when LLM configuration is invalid (missing API key, etc.)."""


class LLMClient:
    """Anthropic API client with environment-based configuration.

    Reads ANTHROPIC_API_KEY from the environment and KICAD_AGENT_MODEL
    for the model to use (defaults to claude-sonnet-4-20250514).

    Args:
        model: Optional model override. If provided, takes precedence over
               the KICAD_AGENT_MODEL environment variable.

    Raises:
        LLMConfigError: If ANTHROPIC_API_KEY is not set in the environment.
    """

    def __init__(self, model: str | None = None) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Get your key from https://console.anthropic.com/"
            )

        self._model = model or os.environ.get(
            "KICAD_AGENT_MODEL", "claude-sonnet-4-20250514"
        )

        # Lazy import of anthropic -- allows module to be loaded without it installed
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    @property
    def model(self) -> str:
        """The model identifier used for API calls."""
        return self._model

    def create_message(self, **kwargs: Any) -> Any:
        """Call the Anthropic messages.create endpoint.

        Passes through all keyword arguments to client.messages.create().
        Automatically injects the configured model.

        Args:
            **kwargs: Arguments passed to anthropic.Anthropic().messages.create().

        Returns:
            The Anthropic Message response object.

        Raises:
            LLMConfigError: On authentication or rate limit errors with descriptive messages.
        """
        import anthropic

        kwargs.setdefault("model", self._model)

        try:
            return self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise LLMConfigError(
                f"Anthropic API authentication failed: {exc.status_code}. "
                "Check your ANTHROPIC_API_KEY."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise LLMConfigError(
                f"Anthropic API rate limit exceeded: {exc.status_code}. "
                "Please wait and retry."
            ) from exc
