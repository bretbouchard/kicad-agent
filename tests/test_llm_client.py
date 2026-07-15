"""Tests for LLM client and provider modules."""

import pytest

from volta.llm.local_client import LocalLLMClient
from volta.llm.backend import LLMBackend


class TestLocalLLMClientDetailed:
    """Detailed tests for LocalLLMClient."""

    def test_model_property(self):
        """model property returns model identifier."""
        client = LocalLLMClient(model="custom/model")
        assert client.model == "custom/model"

    def test_adapter_path_property(self):
        """adapter_path property returns string."""
        client = LocalLLMClient()
        assert isinstance(client.adapter_path, str)

    def test_unload_twice(self):
        """unload_model is idempotent."""
        client = LocalLLMClient()
        client.unload_model()
        client.unload_model()  # Should not raise

    def test_chat_method_exists(self):
        """chat method exists."""
        client = LocalLLMClient()
        assert hasattr(client, "chat")

    def test_create_message_method_exists(self):
        """create_message method exists."""
        client = LocalLLMClient()
        assert hasattr(client, "create_message")

    def test_analyze_board_method_exists(self):
        """analyze_board method exists."""
        client = LocalLLMClient()
        assert hasattr(client, "analyze_board")

    def test_assess_routing_method_exists(self):
        """assess_routing method exists."""
        client = LocalLLMClient()
        assert hasattr(client, "assess_routing")


class TestLLMBackend:
    """Tests for LLM backend protocol."""

    def test_import(self):
        """LLMBackend is importable."""
        assert LLMBackend is not None


class TestLLMProvider:
    """Tests for LLM provider."""

    def test_import(self):
        """LLM provider module is importable."""
        from volta.llm.provider import LLMProvider
        assert LLMProvider is not None
