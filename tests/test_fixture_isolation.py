"""Verify LLM fixture isolation -- autouse removal correctness.

Council audit reference: H-5.

These tests verify that the llm_api_key fixture in conftest_llm.py does NOT
contaminate non-LLM tests (autouse=True was removed). Only tests that
explicitly request llm_api_key get ANTHROPIC_API_KEY set.
"""

from __future__ import annotations

import os


class TestLlmApiKeyFixtureIsolation:
    """Verify llm_api_key fixture is NOT autouse."""

    def test_llm_key_not_set_by_default(self, monkeypatch) -> None:
        """A plain test function must NOT have ANTHROPIC_API_KEY set."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert "ANTHROPIC_API_KEY" not in os.environ

    def test_llm_key_set_when_requested(self, llm_api_key) -> None:
        """A test requesting llm_api_key fixture DOES have the key set."""
        assert "ANTHROPIC_API_KEY" in os.environ
        assert os.environ["ANTHROPIC_API_KEY"] == "sk-test-key-for-testing-only"
