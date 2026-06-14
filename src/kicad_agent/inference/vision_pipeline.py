"""Gemma 4 12B Vision inference pipeline for KiCad PCB analysis.

Loads a quantized Gemma 4 12B model via mlx-vlm and generates reasoning
from PCB/schematic images + text prompts. Adapted from spectral-primitives
Phase 73 Gemma4VisionPipeline.

Provides:
- KiCadVisionConfig: frozen config for Gemma 4 vision inference
- KiCadVisionPipeline: loads Gemma 4 12B, generates from images + text
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class KiCadVisionConfig(BaseModel):
    """Configuration for Gemma 4 12B vision inference pipeline.

    Defines model name, LoRA adapter path, and generation parameters.
    All fields are immutable. mlx-vlm handles device placement automatically
    on Apple Silicon.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str = Field(
        default="mlx-community/gemma-4-12B-it-8bit",
        description="HuggingFace model ID for quantized Gemma 4 12B (MLX format)",
    )
    adapter_path: Path | None = Field(
        default=None,
        description="Path to LoRA adapter directory (None = base model only)",
    )
    max_tokens: int = Field(default=2048, ge=1, description="Max tokens to generate")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="Sampling temperature")
    verbose: bool = Field(default=False, description="mlx-vlm verbose logging")

    @field_validator("adapter_path", mode="after")
    @classmethod
    def _validate_adapter_path(cls, v: Path | None) -> Path | None:
        if v is not None:
            resolved = v.resolve()
            if not resolved.exists():
                raise ValueError(f"LoRA adapter not found: {resolved}")
            if not resolved.is_dir():
                raise ValueError(f"LoRA adapter must be a directory: {resolved}")
        return v


class KiCadVisionPipeline:
    """Vision inference pipeline for Gemma 4 12B on KiCad PCBs/schematics.

    Loads a quantized Gemma 4 12B model via mlx-vlm on construction.
    Accepts PIL.Image of PCB render + text prompt, runs vision inference,
    and returns raw text output.

    Args:
        config: KiCadVisionConfig with model name and generation parameters.
    """

    def __init__(self, config: KiCadVisionConfig) -> None:
        self._config = config
        self._model, self._processor = self._load_model(config)

    @property
    def config(self) -> KiCadVisionConfig:
        return self._config

    def generate_from_image(
        self,
        image: "PIL.Image.Image",
        prompt: str,
    ) -> str:
        """Generate reasoning from PCB/schematic image + text prompt.

        Args:
            image: PIL.Image of PCB render or schematic.
            prompt: Text prompt instructing the model.

        Returns:
            Raw text output from the model.
        """
        from mlx_vlm import generate as mlx_generate
        from mlx_vlm.prompt_utils import apply_chat_template

        formatted_prompt = apply_chat_template(
            self._processor,
            self._model.config,
            prompt,
            num_images=1,
        )
        try:
            raw_text = mlx_generate(
                model=self._model,
                processor=self._processor,
                prompt=formatted_prompt,
                image=image,
                max_tokens=self._config.max_tokens,
                temp=self._config.temperature,
                verbose=self._config.verbose,
            )
        except Exception as exc:
            logger.warning("Gemma 4 vision inference failed: %s", exc)
            return ""
        return self._extract_text(raw_text)

    def generate_from_prompt(self, prompt: str) -> str:
        """Text-only generation (no image). For backward compat / testing.

        Args:
            prompt: Text prompt instructing the model.

        Returns:
            Raw text output from the model.
        """
        from mlx_vlm import generate as mlx_generate
        from mlx_vlm.prompt_utils import apply_chat_template

        formatted_prompt = apply_chat_template(
            self._processor,
            self._model.config,
            prompt,
            num_images=0,
        )
        try:
            raw_text = mlx_generate(
                model=self._model,
                processor=self._processor,
                prompt=formatted_prompt,
                image=None,
                max_tokens=self._config.max_tokens,
                temp=self._config.temperature,
                verbose=self._config.verbose,
            )
        except Exception as exc:
            logger.warning("Gemma 4 text inference failed: %s", exc)
            return ""
        return self._extract_text(raw_text)

    @staticmethod
    def _load_model(config: KiCadVisionConfig) -> tuple[Any, Any]:
        """Load model and processor via mlx-vlm. Lazy heavy import."""
        from mlx_vlm import load

        logger.info("Loading Gemma 4 vision model: %s", config.model_name)
        model, processor = load(
            config.model_name,
            adapter_path=str(config.adapter_path) if config.adapter_path is not None else None,
        )
        if config.adapter_path is not None:
            logger.info("Loaded LoRA adapter from %s", config.adapter_path)
        return model, processor

    @staticmethod
    def _extract_text(raw_text: Any) -> str:
        """Extract text from mlx-vlm output (handles GenerationResult or str)."""
        if hasattr(raw_text, "text"):
            raw_text = raw_text.text
        if not raw_text or not str(raw_text).strip():
            return ""
        return str(raw_text)
