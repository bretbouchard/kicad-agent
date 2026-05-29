"""Tests for HybridLLMClient (kicad_agent.llm.backend)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from kicad_agent.llm.backend import HybridLLMClient, HybridResponse, LLMBackend


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------


class MockClient:
    """Minimal mock satisfying the LLMBackend protocol."""

    def __init__(self, text: str = "test response", model_name: str = "mock-model"):
        self._text = text
        self._model = model_name

    @property
    def model(self) -> str:
        return self._model

    def create_message(self, **kwargs):
        class Content:
            type = "text"
            text = self._text

        class Msg:
            content = [Content()]
            role = "assistant"
            model = self._model
            stop_reason = "end_turn"

        return Msg()


# ---------------------------------------------------------------------------
# Helper: build a hybrid client with both backends mocked
# ---------------------------------------------------------------------------


def _make_client(
    local_text: str = "local output",
    cloud_text: str = "cloud output",
    fallback_mode: str = "local_first",
    confidence_threshold: float = 0.6,
) -> HybridLLMClient:
    return HybridLLMClient(
        local_client=MockClient(text=local_text, model_name="local-mock"),
        cloud_client=MockClient(text=cloud_text, model_name="cloud-mock"),
        confidence_threshold=confidence_threshold,
        fallback_mode=fallback_mode,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCloudOnlyMode:
    def test_cloud_only_mode(self):
        client = _make_client(fallback_mode="cloud_only")
        result = client.create_message(
            max_tokens=100,
            messages=[{"role": "user", "content": "hello"}],
        )
        assert isinstance(result, HybridResponse)
        assert result.source == "cloud"
        assert result.content[0].text == "cloud output"
        assert result.model == "cloud-mock"


class TestLocalOnlyMode:
    def test_local_only_mode(self):
        client = _make_client(fallback_mode="local_only")
        result = client.create_message(
            max_tokens=100,
            tools=[{"name": "test_tool"}],  # should be stripped for local
            messages=[{"role": "user", "content": "hello"}],
        )
        assert isinstance(result, HybridResponse)
        assert result.source == "local"
        assert result.content[0].text == "local output"
        assert result.model == "local-mock"


class TestLocalFirstConfident:
    def test_local_first_confident(self):
        """When the scorer returns high confidence, local result is used."""

        class HighConfidenceScorer:
            def score(self, text, **_kwargs):
                class Score:
                    overall = 0.95
                return Score()

        client = _make_client(fallback_mode="local_first")
        client._scorer = HighConfidenceScorer()

        result = client.create_message(
            max_tokens=100,
            messages=[{"role": "user", "content": "hello"}],
        )
        assert result.source == "local"
        assert result.confidence == 0.95
        assert result.fallback_triggered is False


class TestLocalFirstLowConfidence:
    def test_local_first_low_confidence(self):
        """When the scorer returns low confidence, cloud fallback is triggered."""

        class LowConfidenceScorer:
            def score(self, text, **_kwargs):
                class Score:
                    overall = 0.2
                return Score()

        client = _make_client(fallback_mode="local_first", confidence_threshold=0.6)
        client._scorer = LowConfidenceScorer()

        result = client.create_message(
            max_tokens=100,
            messages=[{"role": "user", "content": "hello"}],
        )
        assert result.source == "cloud"
        assert result.fallback_triggered is True


class TestBackwardCompatContent:
    def test_backward_compat_content(self):
        """HybridResponse.content[0].text works for both local and cloud."""
        client = _make_client(fallback_mode="cloud_only")
        result = client.create_message(
            max_tokens=100,
            messages=[{"role": "user", "content": "hello"}],
        )
        # Anthropic-style content access
        assert len(result.content) >= 1
        assert hasattr(result.content[0], "text")
        assert result.content[0].text == "cloud output"


class TestEnvVarOverride:
    def test_env_var_override(self):
        """KICAD_AGENT_LLM_MODE env var overrides fallback_mode."""
        with patch.dict(os.environ, {"KICAD_AGENT_LLM_MODE": "cloud_only"}):
            client = _make_client(fallback_mode="local_first")
            assert client.fallback_mode == "cloud_only"

    def test_env_var_invalid_ignored(self):
        """Invalid env var value falls back to the constructor default."""
        with patch.dict(os.environ, {"KICAD_AGENT_LLM_MODE": "bogus"}):
            client = _make_client(fallback_mode="local_only")
            assert client.fallback_mode == "local_only"


class TestProtocolConformance:
    def test_protocol_conformance(self):
        """MockClient satisfies the LLMBackend runtime_checkable protocol."""
        mock = MockClient()
        assert isinstance(mock, LLMBackend)
