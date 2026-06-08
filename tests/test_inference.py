"""Tests for inference module."""

import pytest


class TestInferenceModule:
    """Tests for AI inference module."""

    def test_import(self):
        """Inference module is importable."""
        from kicad_agent.inference import generate_analysis
        assert callable(generate_analysis)
