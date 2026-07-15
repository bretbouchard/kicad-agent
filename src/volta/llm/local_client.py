"""Local inference using fine-tuned PCB reasoning model (mlx-lm).

Provides LocalLLMClient as a drop-in alternative to LLMClient that runs
inference locally on Apple Silicon using the SFT/GRPO fine-tuned adapter.

No API key required. Uses the mlx-lm library for native GPU acceleration.

Usage:
    from volta.llm.local_client import LocalLLMClient

    client = LocalLLMClient()
    response = client.chat([
        {"role": "system", "content": "You are a PCB design expert."},
        {"role": "user", "content": "Analyze this board: 50 components, 30 nets"},
    ])
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class LocalLLMClient:
    """Local mlx-lm inference client using fine-tuned PCB reasoning model.

    Loads the base Qwen model + LoRA adapter trained on PCB reasoning chains.
    Runs entirely locally on Apple Silicon GPU — no API key needed.

    Args:
        model: Base model HuggingFace ID.
        adapter_dir: Directory containing adapters.safetensors + adapter_config.json.
        max_tokens: Maximum generation length.
        temperature: Sampling temperature (0.0 = greedy).
    """

    _HF_REPO = "bretbouchard/volta-pcb-adapter"

    @classmethod
    def pre_download_adapter(cls) -> Path:
        """Download adapter from HuggingFace Hub to local cache without loading model.

        Triggers the download pipeline (same as _resolve_adapter's HF path)
        but does not instantiate a client or load any model into memory.
        Useful for pre-caching adapters before inference sessions.

        Returns:
            Path to the downloaded adapter directory.

        Raises:
            RuntimeError: If download fails.
        """
        cache_dir = Path.home() / ".cache" / "volta" / "adapters"
        grpo_dir = cache_dir / "grpo"
        sft_dir = cache_dir / "sft"

        # Already cached -- return immediately
        for target_dir in [grpo_dir, sft_dir]:
            if (target_dir / "adapters.safetensors").exists():
                return target_dir

        # Download from HF Hub
        try:
            import shutil
            from huggingface_hub import snapshot_download

            downloaded = snapshot_download(
                cls._HF_REPO,
                allow_patterns=["grpo/*", "sft/*"],
                cache_dir=str(cache_dir),
            )
            for adapter_type in ["grpo", "sft"]:
                src = Path(downloaded) / adapter_type
                dst = cache_dir / adapter_type
                if src.exists() and (src / "adapters.safetensors").exists():
                    dst.mkdir(parents=True, exist_ok=True)
                    for f in src.iterdir():
                        shutil.copy2(f, dst / f.name)

            if (grpo_dir / "adapters.safetensors").exists():
                return grpo_dir
            if (sft_dir / "adapters.safetensors").exists():
                return sft_dir
        except Exception as e:
            raise RuntimeError(
                f"Failed to download adapter from HuggingFace Hub: {e}"
            ) from e

        raise RuntimeError(
            "Downloaded adapter archive contained no valid adapters.safetensors"
        )

    @classmethod
    def get_cache_info(cls) -> dict[str, str | bool | None]:
        """Return information about the local adapter cache.

        Cache directory: Path.home()/.cache/volta/adapters/

        Returns:
            Dict with keys:
            - cache_dir: Absolute path to cache directory.
            - grpo_cached: True if GRPO adapter is cached.
            - sft_cached: True if SFT adapter is cached.
            - adapter_path: Path to preferred adapter (GRPO > SFT > None).
        """
        cache_dir = Path.home() / ".cache" / "volta" / "adapters"
        grpo_dir = cache_dir / "grpo"
        sft_dir = cache_dir / "sft"

        grpo_cached = (grpo_dir / "adapters.safetensors").exists()
        sft_cached = (sft_dir / "adapters.safetensors").exists()

        if grpo_cached:
            adapter_path = str(grpo_dir)
        elif sft_cached:
            adapter_path = str(sft_dir)
        else:
            adapter_path = None

        return {
            "cache_dir": str(cache_dir),
            "grpo_cached": grpo_cached,
            "sft_cached": sft_cached,
            "adapter_path": adapter_path,
        }

    def __init__(
        self,
        model: str | None = None,
        adapter_dir: str | Path | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> None:
        self._model_name = model or os.environ.get(
            "KICAD_LOCAL_MODEL", "Qwen/Qwen2.5-0.5B-Instruct",
        )
        self._adapter_dir = self._resolve_adapter(adapter_dir)
        self._adapter_from_hf = False
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._model = None
        self._tokenizer = None

    def _resolve_adapter(self, adapter_dir: str | Path | None) -> Path:
        """Find adapter directory: explicit > local > HF Hub download."""
        # 1. Explicit path
        if adapter_dir:
            p = Path(adapter_dir)
            if p.exists():
                return p

        # 2. Local training output (GRPO > SFT > Gemma SFT)
        local_paths = [
            Path(os.environ.get("KICAD_LOCAL_ADAPTER", "training_output/grpo/iter_2")),
            Path("training_output/grpo/iter_2"),
            Path("training_output/sft"),
        ]
        if self._model_name and "gemma" in self._model_name.lower():
            local_paths.insert(0, Path("training_output/gemma_sft"))
        for local in local_paths:
            if local.exists() and (local / "adapters.safetensors").exists():
                return local

        # 3. Download from HuggingFace Hub
        cache_dir = Path.home() / ".cache" / "volta" / "adapters"
        grpo_dir = cache_dir / "grpo"
        sft_dir = cache_dir / "sft"

        for adapter_type, target_dir in [("grpo", grpo_dir), ("sft", sft_dir)]:
            if (target_dir / "adapters.safetensors").exists():
                return target_dir

        # Download from HF Hub (prefer GRPO, fall back to SFT)
        try:
            import shutil
            from huggingface_hub import snapshot_download
            downloaded = snapshot_download(
                self._HF_REPO,
                allow_patterns=["grpo/*", "sft/*"],
                cache_dir=str(cache_dir),
            )
            for adapter_type in ["grpo", "sft"]:
                src = Path(downloaded) / adapter_type
                dst = cache_dir / adapter_type
                if src.exists() and (src / "adapters.safetensors").exists():
                    dst.mkdir(parents=True, exist_ok=True)
                    for f in src.iterdir():
                        shutil.copy2(f, dst / f.name)

            if (grpo_dir / "adapters.safetensors").exists():
                self._adapter_from_hf = True
                return grpo_dir
            if (sft_dir / "adapters.safetensors").exists():
                self._adapter_from_hf = True
                return sft_dir
        except Exception:
            pass

        # 4. No adapter found — will run base model
        return Path("training_output/grpo/iter_2")

    def _ensure_loaded(self) -> None:
        """Lazy-load model and tokenizer on first use."""
        if self._model is not None:
            return

        from mlx_lm import load

        adapter_path = str(self._adapter_dir) if self._adapter_dir.exists() else None
        if adapter_path:
            self._model, self._tokenizer = load(self._model_name, adapter_path=adapter_path)
        else:
            self._model, self._tokenizer = load(self._model_name)

    def unload_model(self) -> None:
        """Release model and tokenizer references for memory management.

        Idempotent -- safe to call multiple times. After unloading, the next
        chat() call will trigger lazy reload via _ensure_loaded().
        """
        self._model = None
        self._tokenizer = None

    @property
    def model(self) -> str:
        """The model identifier."""
        return self._model_name

    @property
    def adapter_path(self) -> str:
        """Path to the LoRA adapter."""
        return str(self._adapter_dir)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Generate a response from a list of chat messages.

        Args:
            messages: List of {"role": "system|user|assistant", "content": "..."}.
            **kwargs: Override max_tokens, temperature, etc.

        Returns:
            Generated text response.
        """
        self._ensure_loaded()

        max_tokens = kwargs.get("max_tokens", self._max_tokens)
        temperature = kwargs.get("temperature", self._temperature)

        prompt = self._format_messages(messages)

        from mlx_lm import generate
        import mlx.core as mx

        # Create temperature sampler
        if temperature > 0:
            def sampler(logits):
                return mx.random.categorical(logits * (1.0 / max(temperature, 1e-8)))
        else:
            def sampler(logits):
                return mx.argmax(logits, axis=-1)

        response = generate(
            self._model, self._tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler,
            verbose=False,
        )

        return self._extract_response(response)

    def create_message(self, **kwargs: Any) -> Any:
        """API-compatible interface matching LLMClient.create_message().

        Converts Anthropic-style messages format to local inference.

        Args:
            **kwargs: Must include 'messages' list. Other kwargs like 'max_tokens'
                      are passed through. 'system' is prepended as a system message.

        Returns:
            Simple namespace object with .content[0].text matching Anthropic response.
        """
        messages = kwargs.get("messages", [])
        system = kwargs.get("system")
        max_tokens = kwargs.get("max_tokens", self._max_tokens)

        # Build message list
        chat_messages = []
        if system:
            chat_messages.append({"role": "system", "content": system})
        chat_messages.extend(messages)

        response_text = self.chat(chat_messages, max_tokens=max_tokens)

        # Return Anthropic-compatible response structure
        class _Content:
            def __init__(self, text: str):
                self.text = text
                self.type = "text"

        class _Message:
            def __init__(self, text: str):
                self.content = [_Content(text)]
                self.role = "assistant"
                self.model = self_model_name
                self.stop_reason = "end_turn"

        self_model_name = self._model_name
        return _Message(response_text)

    def _is_gemma_model(self) -> bool:
        """Check if the current model uses Gemma ChatML format."""
        return "gemma" in self._model_name.lower()

    def _format_messages(self, messages: list[dict[str, str]]) -> str:
        """Format messages as ChatML prompt for the current model.

        Gemma models use <start_of_turn>role\\ncontent<end_of_turn> with 'model'.
        Qwen models use <|im_start|>role\\ncontent<|im_end|> with 'assistant'.
        """
        if self._is_gemma_model():
            return self._format_gemma_chatml(messages)
        return self._format_qwen_chatml(messages)

    @staticmethod
    def _format_gemma_chatml(messages: list[dict[str, str]]) -> str:
        """Format messages in Gemma ChatML format."""
        prompt_parts = []
        for msg in messages:
            role = msg["role"]
            # Gemma uses 'model' instead of 'assistant'.
            if role == "assistant":
                role = "model"
            prompt_parts.append(f"<start_of_turn>{role}\n{msg['content']}<end_of_turn>")
        prompt_parts.append("<start_of_turn>model\n")
        return "\n".join(prompt_parts)

    @staticmethod
    def _format_qwen_chatml(messages: list[dict[str, str]]) -> str:
        """Format messages in Qwen ChatML format."""
        prompt_parts = []
        for msg in messages:
            prompt_parts.append(f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>")
        prompt_parts.append("<|im_start|>assistant\n")
        return "\n".join(prompt_parts)

    def _extract_response(self, response: str) -> str:
        """Extract the assistant/model response from generation output."""
        if self._is_gemma_model():
            marker = "<start_of_turn>model\n"
            end_marker = "<end_of_turn>"
        else:
            marker = "<|im_start|>assistant\n"
            end_marker = "<|im_end|>"

        if marker in response:
            idx = response.index(marker) + len(marker)
            text = response[idx:].strip()
            if end_marker in text:
                text = text[: text.index(end_marker)].strip()
            return text

        return response.strip()

    def analyze_board(
        self,
        board_name: str,
        n_components: int,
        n_nets: int,
        n_layers: int,
        width_mm: float,
        height_mm: float,
        source: str = "unknown",
    ) -> str:
        """Generate a PCB board analysis using the fine-tuned model.

        Args:
            board_name: Name of the board.
            n_components: Number of components.
            n_nets: Number of nets.
            n_layers: Number of PCB layers.
            width_mm: Board width in mm.
            height_mm: Board height in mm.
            source: Source/repo URL.

        Returns:
            Structured PCB analysis text.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a PCB design expert specializing in spatial reasoning. "
                    "Analyze boards using coordinate-grounded reasoning with <point x,y> tags. "
                    "Provide structured analysis: observation, component analysis, connectivity, "
                    "spatial analysis, and routing assessment."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Analyze this PCB board:\n"
                    f"Board: {board_name}\n"
                    f"Components: {n_components}, Nets: {n_nets}, Layers: {n_layers}\n"
                    f"Board size: {width_mm:.1f} x {height_mm:.1f} mm\n"
                    f"Source: {source}\n\n"
                    f"Provide a complete spatial reasoning analysis."
                ),
            },
        ]
        return self.chat(messages, max_tokens=1024)

    def assess_routing(
        self,
        board_name: str,
        n_components: int,
        n_nets: int,
        n_traces: int,
        res_score: float,
        quality_label: str,
        density: float,
        via_density: float,
        manhattan_eff: float,
    ) -> str:
        """Generate a routing quality assessment.

        Args:
            board_name: Name of the board.
            n_components: Number of components.
            n_nets: Number of nets.
            n_traces: Number of traces.
            res_score: Routing Elegance Score.
            quality_label: Quality label (excellent/good/fair/poor).
            density: Component density (comp/mm2).
            via_density: Via density (/mm2).
            manhattan_eff: Manhattan efficiency ratio.

        Returns:
            Routing quality assessment text.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a PCB design expert specializing in routing quality assessment."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Assess the routing quality of this PCB:\n"
                    f"Board: {board_name}\n"
                    f"Components: {n_components}, Nets: {n_nets}, Traces: {n_traces}\n"
                    f"RES Score: {res_score:.3f} ({quality_label})\n"
                    f"Density: {density:.3f} comp/mm2, Via density: {via_density:.3f}/mm2\n"
                    f"Manhattan efficiency: {manhattan_eff:.3f}\n\n"
                    f"Evaluate the routing quality and identify strengths and weaknesses."
                ),
            },
        ]
        return self.chat(messages, max_tokens=768)
