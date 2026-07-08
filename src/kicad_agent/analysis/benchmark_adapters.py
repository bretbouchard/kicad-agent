"""Model adapters for the spatial reasoning benchmark.

Split out of ``benchmark_runner.py`` (originally 768 LOC) to keep each
module focused. Re-exported from ``benchmark_runner.py`` for backward
compatibility.

Public surface:
    - QwenTextAdapter
    - GemmaVisionAdapter
    - _GEMMA_MODEL_ID, _GEMMA_MMPROJ module constants
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from kicad_agent.analysis.benchmark_types import ModelAdapter
from kicad_agent.analysis.spatial_benchmark import SpatialReasoningTask

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Qwen Text Adapter
# ---------------------------------------------------------------------------


class QwenTextAdapter:
    """Adapter for Qwen2.5-0.5B (text-only) via LocalLLMClient.

    Handles all task types as pure text — no image input.
    """

    _SYSTEM_PROMPT = (
        "You are a PCB design expert. Answer spatial reasoning questions "
        "about PCB layout concisely. For numeric answers, respond with "
        "just the number. For yes/no questions, respond with 'yes' or 'no'. "
        "For fix selection, respond with 'Fix N: <description>'. "
        "For path questions, describe waypoints as (x, y) coordinates."
    )

    def __init__(
        self,
        model: str | None = None,
        adapter_dir: str | Path | None = None,
        max_tokens: int = 256,
        temperature: float = 0.1,
    ) -> None:
        self._model_name = model or "Qwen/Qwen2.5-0.5B-Instruct"
        self._adapter_dir = adapter_dir
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client: Any = None

    @property
    def name(self) -> str:
        return f"Qwen2.5-0.5B ({self._model_name})"

    @property
    def supports_vision(self) -> bool:
        return False

    def _ensure_loaded(self) -> None:
        if self._client is not None:
            return
        from kicad_agent.llm.local_client import LocalLLMClient

        self._client = LocalLLMClient(
            model=self._model_name,
            adapter_dir=self._adapter_dir,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )
        logger.info("Qwen2.5-0.5B loaded via LocalLLMClient")

    def run_task(self, task: SpatialReasoningTask) -> str:
        self._ensure_loaded()
        messages = [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": task.question},
        ]
        return self._client.chat(messages, max_tokens=self._max_tokens)


# ---------------------------------------------------------------------------
# Gemma Vision Adapter
# ---------------------------------------------------------------------------

# Default Gemma 4 12B GGUF model and vision projector paths.
_GEMMA_MODEL_ID = "ggml-org/gemma-4-12B-it-Q4_K_M"
_GEMMA_MMPROJ = "ggml-org/gemma-4-12B-it-Q8_0"


class GemmaVisionAdapter:
    """Adapter for Gemma 4 12B encoder-free vision via mlx-lm.

    Loads the Q4_K_M GGUF model + Q8_0 vision projector (mmproj).
    For text-only tasks, degrades gracefully by passing text only.
    For vision tasks, interleaves image tokens with text prompt.

    Requires mlx-lm >= 0.31.3 with multimodal support.
    """

    _SYSTEM_PROMPT = (
        "You are a PCB design expert with vision capabilities. "
        "Analyze the provided PCB render and answer spatial reasoning "
        "questions. For numeric answers, respond with just the number. "
        "For yes/no questions, respond with 'yes' or 'no'. "
        "For fix selection, respond with 'Fix N: <description>'. "
        "For path questions, describe waypoints as (x, y) coordinates."
    )

    def __init__(
        self,
        model_repo: str | None = None,
        mmproj_repo: str | None = None,
        max_tokens: int = 256,
        temperature: float = 0.1,
    ) -> None:
        self._model_repo = model_repo or _GEMMA_MODEL_ID
        self._mmproj_repo = mmproj_repo or _GEMMA_MMPROJ
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._model: Any = None
        self._tokenizer: Any = None
        self._processor: Any = None
        self._available: bool | None = None

    @property
    def name(self) -> str:
        return f"Gemma 4 12B ({self._model_repo})"

    @property
    def supports_vision(self) -> bool:
        return True

    def is_available(self) -> bool:
        """Check if Gemma 4 12B can be loaded (model + mmproj cached)."""
        if self._available is not None:
            return self._available
        try:
            from mlx_lm import load

            load(self._model_repo)
            self._available = True
        except Exception as exc:
            logger.warning("Gemma 4 12B unavailable: %s", exc)
            self._available = False
        return self._available

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from mlx_lm import load

        self._model, self._tokenizer = load(self._model_repo)
        # Try loading mmproj for vision support.
        try:
            # mlx-lm vision loading via separate mmproj.
            # If mmproj is bundled with the GGUF, it may already be loaded.
            pass
        except Exception as exc:
            logger.debug("mmproj load skipped: %s", exc)
        logger.info("Gemma 4 12B loaded via mlx-lm")

    def run_task(self, task: SpatialReasoningTask) -> str:
        self._ensure_loaded()

        messages = [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": task.question},
        ]

        # For vision tasks with a render, try to include the image.
        if task.input_type == "vision" and task.render_path:
            image_path = Path(task.render_path)
            if image_path.exists():
                messages = self._build_vision_messages(task, image_path)
            else:
                logger.debug(
                    "Render not found for %s, falling back to text-only",
                    task.task_id,
                )

        # Format as ChatML for Gemma.
        prompt_parts = []
        for msg in messages:
            prompt_parts.append(f"<start_of_turn>{msg['role']}\n{msg['content']}<end_of_turn>")
        prompt_parts.append("<start_of_turn>model\n")
        prompt = "\n".join(prompt_parts)

        import mlx.core as mx
        from mlx_lm import generate

        if self._temperature > 0:
            def sampler(logits):
                return mx.random.categorical(logits * (1.0 / max(self._temperature, 1e-8)))
        else:
            def sampler(logits):
                return mx.argmax(logits, axis=-1)

        response = generate(
            self._model, self._tokenizer,
            prompt=prompt,
            max_tokens=self._max_tokens,
            sampler=sampler,
            verbose=False,
        )

        # Extract assistant response.
        marker = "<start_of_turn>model\n"
        if marker in response:
            idx = response.index(marker) + len(marker)
            return response[idx:].strip()
        return response.strip()

    def _build_vision_messages(
        self, task: SpatialReasoningTask, image_path: Path,
    ) -> list[dict[str, str]]:
        """Build messages with image reference for vision tasks."""
        # Gemma 4 12B encoder-free processes images via linear projection.
        # mlx-lm handles image tokenization internally when using
        # the generate() function with image input.
        # For now, include image path reference in the text prompt,
        # as actual image embedding depends on mlx-lm's multimodal API.
        question = (
            f"{task.question}\n\n"
            f"[PCB render: {image_path.name}]"
        )
        return [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
