"""Tests for LLM and inference modules."""

import pytest


class TestLocalClient:
    """Tests for local LLM client."""

    def test_import(self):
        """LocalLLMClient is importable."""
        from kicad_agent.llm.local_client import LocalLLMClient
        assert LocalLLMClient is not None

    def test_creation_with_defaults(self):
        """LocalLLMClient creates with default model."""
        client = LocalLLMClient()
        assert "Qwen" in client.model

    def test_creation_custom_model(self):
        """LocalLLMClient accepts custom model name."""
        client = LocalLLMClient(model="custom/model")
        assert client.model == "custom/model"

    def test_adapter_path_property(self):
        """adapter_path property returns string."""
        client = LocalLLMClient()
        assert isinstance(client.adapter_path, str)

    def test_unload_model(self):
        """unload_model is safe to call on fresh client."""
        client = LocalLLMClient()
        client.unload_model()  # Should not raise
        client.unload_model()  # Idempotent


class TestLLMBackend:
    """Tests for LLM backend protocol."""

    def test_import(self):
        """LLM backend is importable."""
        from kicad_agent.llm.backend import LLMBackend
        assert LLMBackend is not None
