"""Hybrid LLM backend: local-first with cloud fallback.

Provides HybridLLMClient that routes LLM requests to a local mlx-lm model
first and falls back to the cloud Anthropic API when local confidence is
below a configurable threshold. This enables zero-cost inference for
well-understood PCB reasoning tasks while preserving cloud quality for
edge cases.

The client reads two environment variables:
- ``KICAD_AGENT_LLM_MODE``: One of "local_first" (default), "cloud_only",
  or "local_only".
- ``KICAD_AGENT_CONFIDENCE_THRESHOLD``: Float 0.0-1.0 (default 0.6). When
  the local model's confidence falls below this value, the hybrid client
  escalates to the cloud.

Backward compatibility:
    HybridResponse.content is a list of Anthropic-compatible content blocks.
    Cloud responses pass through unchanged (tool_use blocks, thinking blocks).
    Local responses are wrapped in a single text block so that existing code
    iterating ``response.content`` or accessing ``response.content[0].text``
    continues to work.

Usage::

    from kicad_agent.llm.backend import HybridLLMClient

    client = HybridLLMClient()
    result = client.create_message(
        max_tokens=4096,
        messages=[{"role": "user", "content": "Design a voltage regulator"}],
    )
    # result.content works like Anthropic Message.content
    # result.source is "local" or "cloud"
    # result.confidence is 0.0-1.0
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLMBackend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMBackend(Protocol):
    """Protocol for LLM clients that can produce messages.

    Both LLMClient (cloud) and LocalLLMClient (local) conform to this
    protocol -- they expose ``.model`` and ``.create_message(**kwargs)``.
    """

    @property
    def model(self) -> str: ...

    def create_message(self, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------------------
# HybridResponse
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HybridResponse:
    """Response from HybridLLMClient with routing metadata.

    Attributes:
        content: Anthropic-compatible content blocks list. Cloud responses
            pass through the original Anthropic Message.content (which may
            contain tool_use, thinking, and text blocks). Local responses
            are wrapped in a single text block.
        source: "local" or "cloud" -- which backend produced this response.
        confidence: Composite confidence score 0.0-1.0 from ConfidenceScorer.
            1.0 for cloud responses (assumed high quality).
        latency_s: Wall-clock time for the LLM call that produced this response.
        fallback_triggered: True when local confidence was below threshold and
            the cloud was called as a fallback.
        model: Model identifier string for the backend that produced the response.
    """

    content: list
    source: str
    confidence: float
    latency_s: float
    fallback_triggered: bool
    model: str


# ---------------------------------------------------------------------------
# Content block wrappers for local responses
# ---------------------------------------------------------------------------


class _LocalTextBlock:
    """Anthropic-compatible text content block for local responses.

    Supports the same attribute interface as Anthropic's TextBlock:
    ``.type`` returns ``"text"`` and ``.text`` returns the content string.
    """

    __slots__ = ("type", "text")

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text

    def __repr__(self) -> str:
        return f"TextBlock(type='text', text={self.text!r:.80})"


class _LocalMessage:
    """Anthropic-compatible Message wrapper for local responses.

    Wraps local model text output with the same ``.content`` list interface
    so that existing code accessing ``response.content`` or iterating
    ``response.content`` looking for block types continues to work.
    """

    __slots__ = ("content", "role", "model", "stop_reason", "_latency_s")

    def __init__(self, text: str, model_name: str) -> None:
        self.content = [_LocalTextBlock(text)]
        self.role = "assistant"
        self.model = model_name
        self.stop_reason = "end_turn"


# ---------------------------------------------------------------------------
# Kwargs that only apply to cloud (tool use) and must be stripped for local
# ---------------------------------------------------------------------------

_CLOUD_ONLY_KWARGS = frozenset({"tools", "tool_choice"})


# ---------------------------------------------------------------------------
# HybridLLMClient
# ---------------------------------------------------------------------------


class HybridLLMClient:
    """Local-first LLM client with automatic cloud fallback.

    Routes requests to a local mlx-lm model first. If the local model's
    confidence score (via ConfidenceScorer) falls below the configured
    threshold, the request is re-sent to the cloud Anthropic API.

    Three operating modes:
    - ``local_first`` (default): Try local, fall back to cloud on low confidence.
    - ``cloud_only``: Bypass local entirely; pass through to cloud client.
    - ``local_only``: Use local only; strip tool-use kwargs (local models
      do not support Anthropic-style tool use).

    Args:
        local_client: Optional LocalLLMClient instance. If None, one will
            be created lazily on first use (requires mlx-lm installed).
        cloud_client: Optional LLMClient instance. If None, one will be
            created lazily when needed (requires ANTHROPIC_API_KEY set).
        confidence_threshold: Minimum confidence 0.0-1.0 for local results.
            Overridden by ``KICAD_AGENT_CONFIDENCE_THRESHOLD`` env var.
        tracker: Optional InterventionTracker for recording fallback events.
        fallback_mode: Operating mode string. Overridden by
            ``KICAD_AGENT_LLM_MODE`` env var.
    """

    def __init__(
        self,
        local_client: Any | None = None,
        cloud_client: Any | None = None,
        confidence_threshold: float = 0.6,
        tracker: Any = None,
        fallback_mode: str = "local_first",
    ) -> None:
        # Environment variable overrides
        env_mode = os.environ.get("KICAD_AGENT_LLM_MODE", "").strip().lower()
        self._fallback_mode = env_mode if env_mode in ("local_first", "cloud_only", "local_only") else fallback_mode

        env_threshold = os.environ.get("KICAD_AGENT_CONFIDENCE_THRESHOLD", "").strip()
        if env_threshold:
            try:
                self._confidence_threshold = float(env_threshold)
            except ValueError:
                self._confidence_threshold = confidence_threshold
        else:
            self._confidence_threshold = confidence_threshold

        self._local_client = local_client
        self._cloud_client = cloud_client
        self._tracker = tracker

        # Lazy-initialized components
        self._scorer: Any | None = None

    @property
    def model(self) -> str:
        """Model identifier for the currently active backend.

        Returns the local model name in local modes, cloud model name
        in cloud_only mode.
        """
        if self._fallback_mode == "cloud_only":
            client = self._resolve_cloud_client()
            return client.model if client else "cloud-unavailable"
        client = self._resolve_local_client()
        return client.model if client else "local-unavailable"

    @property
    def fallback_mode(self) -> str:
        """Current operating mode."""
        return self._fallback_mode

    @property
    def confidence_threshold(self) -> float:
        """Current confidence threshold for local-to-cloud fallback."""
        return self._confidence_threshold

    def create_message(self, **kwargs: Any) -> Any:
        """Route an LLM request according to the current fallback mode.

        Args:
            **kwargs: Arguments passed to the underlying backend's
                ``create_message()``. For cloud: full Anthropic API kwargs
                including tools, tool_choice, thinking, etc. For local:
                tools/tool_choice are stripped before dispatch.

        Returns:
            HybridResponse with ``.content`` list of Anthropic-compatible
            blocks, ``.source`` indicating "local" or "cloud", and metadata.
            The return value is backward-compatible with code that accesses
            ``response.content`` or iterates blocks.
        """
        if self._fallback_mode == "cloud_only":
            return self._call_cloud(kwargs, fallback_triggered=False)

        if self._fallback_mode == "local_only":
            return self._call_local(kwargs, fallback_triggered=False)

        # local_first mode
        return self._call_local_first(kwargs)

    # ------------------------------------------------------------------
    # Mode implementations
    # ------------------------------------------------------------------

    def _call_local_first(self, kwargs: dict[str, Any]) -> HybridResponse:
        """Try local first, fall back to cloud on low confidence.

        Steps:
        1. Call local client (stripping tools/tool_choice kwargs).
        2. Score the local response text via ConfidenceScorer.
        3. If confidence >= threshold, return local result.
        4. If confidence < threshold, call cloud with original kwargs
           and record the intervention.
        5. If local client throws, catch and fall back to cloud.
        """
        local_result = self._try_local(kwargs)

        if local_result is not None:
            # Score the local output
            response_text = local_result.content[0].text
            local_latency = getattr(local_result, "_latency_s", 0.0)
            score = self._get_scorer().score(response_text)

            if score.overall >= self._confidence_threshold:
                # Local is confident enough -- use it
                return HybridResponse(
                    content=local_result.content,
                    source="local",
                    confidence=score.overall,
                    latency_s=local_latency,
                    fallback_triggered=False,
                    model=local_result.model,
                )

            # Low confidence -- fall back to cloud
            logger.info(
                "Local confidence %.3f below threshold %.3f, escalating to cloud",
                score.overall,
                self._confidence_threshold,
            )
            cloud_response = self._call_cloud(
                kwargs,
                fallback_triggered=True,
                local_text=response_text,
                local_confidence=score.overall,
            )
            return cloud_response

        # Local client unavailable or failed -- cloud fallback
        logger.info("Local client unavailable, falling back to cloud")
        return self._call_cloud(kwargs, fallback_triggered=True)

    def _call_cloud(
        self,
        kwargs: dict[str, Any],
        fallback_triggered: bool,
        local_text: str = "",
        local_confidence: float = 0.0,
    ) -> HybridResponse:
        """Pass through to the cloud (Anthropic) client.

        Returns a HybridResponse wrapping the original Anthropic Message
        so that all existing code iterating ``.content`` blocks continues
        to work unchanged.
        """
        client = self._resolve_cloud_client()
        if client is None:
            raise RuntimeError(
                "Cloud LLM client unavailable: ANTHROPIC_API_KEY not set "
                "or anthropic package not installed."
            )

        t0 = time.monotonic()
        cloud_message = client.create_message(**kwargs)
        latency_s = time.monotonic() - t0

        # Record intervention if tracker is available and fallback occurred
        if fallback_triggered and self._tracker is not None:
            self._record_intervention(
                local_text=local_text,
                local_confidence=local_confidence,
                cloud_message=cloud_message,
                cloud_latency_s=latency_s,
                fallback_reason="low_confidence" if local_text else "local_unavailable",
            )

        # Extract cloud output text for the response
        cloud_text = ""
        for block in cloud_message.content:
            if hasattr(block, "text"):
                cloud_text = block.text
                break

        return HybridResponse(
            content=cloud_message.content,
            source="cloud",
            confidence=1.0,
            latency_s=latency_s,
            fallback_triggered=fallback_triggered,
            model=client.model,
        )

    def _call_local(
        self,
        kwargs: dict[str, Any],
        fallback_triggered: bool = False,
    ) -> HybridResponse:
        """Call the local client, stripping cloud-only kwargs.

        Returns a HybridResponse with local content wrapped in an
        Anthropic-compatible text block.
        """
        local_msg = self._dispatch_local(kwargs)

        if local_msg is None:
            raise RuntimeError(
                "Local LLM client unavailable: mlx-lm not installed."
            )

        return HybridResponse(
            content=local_msg.content,
            source="local",
            confidence=0.0,  # caller should score if needed
            latency_s=0.0,
            fallback_triggered=fallback_triggered,
            model=local_msg.model,
        )

    def _try_local(self, kwargs: dict[str, Any]) -> _LocalMessage | None:
        """Attempt to call the local client, returning None on failure.

        Catches all exceptions so the caller can fall back to cloud.
        """
        try:
            return self._dispatch_local(kwargs)
        except Exception as exc:
            logger.warning("Local LLM call failed: %s", exc)
            return None

    def _dispatch_local(self, kwargs: dict[str, Any]) -> _LocalMessage:
        """Build local-compatible kwargs and dispatch to the local client.

        Strips ``tools`` and ``tool_choice`` (not supported by local models).
        Moves ``system`` kwarg into the messages list as a system message if
        present (LocalLLMClient handles this in create_message, but we also
        ensure it here for robustness).

        Returns:
            _LocalMessage with Anthropic-compatible content blocks.
        """
        client = self._resolve_local_client()
        if client is None:
            raise RuntimeError("Local LLM client not available")

        t0 = time.monotonic()

        # Strip cloud-only kwargs
        local_kwargs = {k: v for k, v in kwargs.items() if k not in _CLOUD_ONLY_KWARGS}

        # LocalLLMClient.create_message handles 'system' already
        raw_response = client.create_message(**local_kwargs)

        latency_s = time.monotonic() - t0

        # raw_response is the _Message from LocalLLMClient with .content and .model
        # We re-wrap into our own _LocalMessage for consistency
        text = raw_response.content[0].text if raw_response.content else ""
        model_name = getattr(raw_response, "model", client.model)

        msg = _LocalMessage(text, model_name)
        # Store latency for callers that need it
        msg._latency_s = latency_s  # type: ignore[attr-defined]
        return msg

    # ------------------------------------------------------------------
    # Lazy resolution
    # ------------------------------------------------------------------

    def _resolve_local_client(self) -> Any | None:
        """Get or lazily create the local client.

        Returns None if mlx-lm is not installed.
        """
        if self._local_client is not None:
            return self._local_client

        try:
            from kicad_agent.llm.local_client import LocalLLMClient

            self._local_client = LocalLLMClient()
            return self._local_client
        except Exception as exc:
            logger.debug("Could not create LocalLLMClient: %s", exc)
            return None

    def _resolve_cloud_client(self) -> Any | None:
        """Get or lazily create the cloud client.

        Returns None if ANTHROPIC_API_KEY is not set.
        """
        if self._cloud_client is not None:
            return self._cloud_client

        try:
            from kicad_agent.llm.client import LLMClient

            self._cloud_client = LLMClient()
            return self._cloud_client
        except Exception as exc:
            logger.debug("Could not create LLMClient: %s", exc)
            return None

    def _get_scorer(self) -> Any:
        """Get or lazily create the ConfidenceScorer."""
        if self._scorer is None:
            from kicad_agent.llm.confidence import ConfidenceScorer

            self._scorer = ConfidenceScorer()
        return self._scorer

    # ------------------------------------------------------------------
    # Intervention tracking
    # ------------------------------------------------------------------

    def _record_intervention(
        self,
        local_text: str,
        local_confidence: float,
        cloud_message: Any,
        cloud_latency_s: float,
        fallback_reason: str,
    ) -> None:
        """Record a fallback event to the InterventionTracker.

        Silently ignores tracker errors -- tracking is best-effort.
        """
        try:
            from datetime import datetime, timezone

            from kicad_agent.ai_tracking.tracker import InterventionEvent

            # Extract cloud output text
            cloud_text = ""
            for block in cloud_message.content:
                if hasattr(block, "text"):
                    cloud_text = block.text
                    break

            event = InterventionEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                stage="unknown",
                local_output=local_text[:2048],
                local_confidence=local_confidence,
                local_latency_s=0.0,
                fallback_triggered=True,
                fallback_reason=fallback_reason,
                cloud_output=cloud_text[:2048],
                cloud_latency_s=cloud_latency_s,
                confidence_diff=1.0 - local_confidence,
                model_used="cloud",
            )

            if self._tracker is not None:
                self._tracker.record(event)
        except Exception as exc:
            logger.debug("Failed to record intervention: %s", exc)
