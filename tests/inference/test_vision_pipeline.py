"""Tests for KiCad Vision Pipeline (Plan 01)."""

from __future__ import annotations

import pytest
import pydantic
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Any

from kicad_agent.inference.vision_pipeline import KiCadVisionConfig, KiCadVisionPipeline


class TestKiCadVisionConfig:
    """KiCadVisionConfig validation tests."""

    def test_default_config(self):
        config = KiCadVisionConfig()
        assert config.model_name == "mlx-community/gemma-4-12B-it-8bit"
        assert config.adapter_path is None
        assert config.max_tokens == 2048
        assert config.temperature == 0.0

    def test_custom_config(self):
        config = KiCadVisionConfig(
            model_name="custom-model",
            max_tokens=4096,
        )
        assert config.model_name == "custom-model"
        assert config.max_tokens == 4096

    def test_frozen(self):
        config = KiCadVisionConfig()
        with pytest.raises(pydantic.ValidationError):
            config.model_name = "other"

    def test_extra_forbid(self):
        with pytest.raises(pydantic.ValidationError):
            KiCadVisionConfig(nonexistent_field="bad")

    def test_adapter_path_validation_none(self):
        config = KiCadVisionConfig(adapter_path=None)
        assert config.adapter_path is None

    def test_adapter_path_validation_missing(self):
        with pytest.raises(ValueError, match="not found"):
            KiCadVisionConfig(adapter_path=Path("/nonexistent/path"))

    def test_adapter_path_validation_not_dir(self):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tf:
            with pytest.raises(ValueError, match="must be a directory"):
                KiCadVisionConfig(adapter_path=Path(tf.name))


class TestKiCadVisionPipeline:
    """KiCadVisionPipeline unit tests (mocked mlx-vlm at source module level)."""

    @patch("kicad_agent.inference.vision_pipeline.KiCadVisionPipeline._load_model")
    def test_init_loads_model(self, mock_load):
        mock_load.return_value = (MagicMock(), MagicMock())
        config = KiCadVisionConfig()
        pipeline = KiCadVisionPipeline(config)
        assert pipeline.config is config
        mock_load.assert_called_once_with(config)

    @patch("mlx_vlm.prompt_utils.apply_chat_template", return_value="formatted")
    @patch("mlx_vlm.generate", return_value="test output")
    @patch("kicad_agent.inference.vision_pipeline.KiCadVisionPipeline._load_model")
    def test_generate_from_image(self, mock_load, mock_gen, mock_template):
        mock_load.return_value = (MagicMock(), MagicMock())
        config = KiCadVisionConfig()
        pipeline = KiCadVisionPipeline(config)

        image = MagicMock()
        result = pipeline.generate_from_image(image, "Analyze this PCB")

        assert result == "test output"
        mock_template.assert_called_once()
        mock_gen.assert_called_once()

    @patch("mlx_vlm.prompt_utils.apply_chat_template", return_value="formatted")
    @patch("mlx_vlm.generate", return_value="text output")
    @patch("kicad_agent.inference.vision_pipeline.KiCadVisionPipeline._load_model")
    def test_generate_from_prompt(self, mock_load, mock_gen, mock_template):
        mock_load.return_value = (MagicMock(), MagicMock())
        pipeline = KiCadVisionPipeline(KiCadVisionConfig())

        result = pipeline.generate_from_prompt("Analyze without image")

        assert result == "text output"

    @patch("mlx_vlm.prompt_utils.apply_chat_template", return_value="formatted")
    @patch("mlx_vlm.generate", side_effect=Exception("OOM"))
    @patch("kicad_agent.inference.vision_pipeline.KiCadVisionPipeline._load_model")
    def test_generate_from_image_handles_error(self, mock_load, mock_gen, mock_template):
        mock_load.return_value = (MagicMock(), MagicMock())
        pipeline = KiCadVisionPipeline(KiCadVisionConfig())

        result = pipeline.generate_from_image(MagicMock(), "prompt")
        assert result == ""

    @patch("kicad_agent.inference.vision_pipeline.KiCadVisionPipeline._load_model")
    def test_extract_text_string(self, mock_load):
        mock_load.return_value = (MagicMock(), MagicMock())
        pipeline = KiCadVisionPipeline(KiCadVisionConfig())
        assert pipeline._extract_text("hello") == "hello"

    @patch("kicad_agent.inference.vision_pipeline.KiCadVisionPipeline._load_model")
    def test_extract_text_generation_result(self, mock_load):
        mock_load.return_value = (MagicMock(), MagicMock())
        pipeline = KiCadVisionPipeline(KiCadVisionConfig())
        gen_result = MagicMock()
        gen_result.text = "generated text"
        assert pipeline._extract_text(gen_result) == "generated text"

    @patch("kicad_agent.inference.vision_pipeline.KiCadVisionPipeline._load_model")
    def test_extract_text_empty(self, mock_load):
        mock_load.return_value = (MagicMock(), MagicMock())
        pipeline = KiCadVisionPipeline(KiCadVisionConfig())
        assert pipeline._extract_text("") == ""
        assert pipeline._extract_text(None) == ""
