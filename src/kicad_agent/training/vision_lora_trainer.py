"""Gemma 4 LoRA trainer for KiCad vision fine-tuning.

Wraps mlx-vlm LoRA training with chunked restart pattern for MPS
memory mitigation on Apple Silicon. Adapted from spectral-primitives
Phase 73 Gemma4 LoRA trainer.

Uses mlx-vlm's built-in LoRA training (mlx_vlm.lora.main()) which handles
vision token positioning, image embedding gradients, and gradient checkpointing.

Do NOT hand-roll VLM training -- mlx-vlm handles all the complexity.

Provides:
- KiCadVisionSFTConfig: frozen config for vision training
- run_kicad_vision_lora: main training entry point with chunked restart
"""

from __future__ import annotations

import argparse
import gc
import logging
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class KiCadVisionSFTConfig(BaseModel):
    """Configuration for Gemma 4 vision LoRA fine-tuning.

    Frozen to enforce immutability.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(
        default="ggml-org/gemma-4-12B-it-Q4_K_M",
        description="HuggingFace model ID for quantized Gemma 4 12B (MLX format)",
    )
    data: Path = Field(
        default=Path("training_output/kicad_vision_data"),
        description="Path to HuggingFace vision training dataset directory",
    )
    output_dir: Path = Field(
        default=Path("training_output/kicad_vision_lora"),
        description="Output directory for LoRA adapter checkpoints",
    )
    lora_layers: int = Field(default=16, ge=1, le=256, description="LoRA rank")
    batch_size: int = Field(default=1, ge=1, description="Training batch size")
    learning_rate: float = Field(default=1e-5, gt=0.0, description="Learning rate")
    max_steps: int = Field(default=500, ge=1, description="Maximum training steps")
    chunk_size: int = Field(default=50, ge=10, description="Steps per chunk for MPS memory mitigation")
    max_chunks: int = Field(default=10, ge=1, description="Maximum number of training chunks")
    save_every: int = Field(default=50, ge=1, description="Save checkpoint every N steps")
    grad_checkpoint: bool = Field(default=True, description="Enable gradient checkpointing")
    max_seq_length: int = Field(default=2048, ge=1, description="Maximum sequence length")


def _get_lora_main():
    """Lazy import of mlx-vlm LoRA training entry point."""
    from mlx_vlm.lora import main as lora_main
    return lora_main


def _resolve_dataset_arg(data_path: Path) -> str:
    """Return absolute path for dataset argument."""
    return str(data_path.resolve())


def _build_lora_args(
    config: KiCadVisionSFTConfig,
    chunk_steps: int,
    adapter_path: str | None,
    output_path: str,
) -> argparse.Namespace:
    """Build argparse.Namespace matching mlx_vlm.lora.main() expected fields."""
    dataset_arg = _resolve_dataset_arg(config.data)
    return argparse.Namespace(
        model_path=config.model,
        dataset=dataset_arg,
        dataset_config=None,
        split="train",
        image_resize_shape=None,
        custom_prompt_format=None,
        learning_rate=config.learning_rate,
        batch_size=config.batch_size,
        iters=chunk_steps,
        epochs=None,
        steps_per_report=10,
        steps_per_eval=200,
        steps_per_save=config.save_every,
        val_batches=4,
        max_seq_length=config.max_seq_length,
        grad_checkpoint=config.grad_checkpoint,
        grad_clip=None,
        train_on_completions=False,
        gradient_accumulation_steps=1,
        assistant_id=77091,
        lora_alpha=16,
        lora_rank=config.lora_layers,
        lora_dropout=0.0,
        full_finetune=False,
        train_vision=False,
        train_mode="sft",
        beta=0.1,
        eps=1e-8,
        output_path=output_path,
        adapter_path=adapter_path,
    )


def run_kicad_vision_lora(config: KiCadVisionSFTConfig) -> dict[str, Any]:
    """Run Gemma 4 LoRA fine-tuning with chunked restart pattern.

    Per MPS memory mitigation: Process restart every chunk_size steps prevents
    memory growth. Each chunk is a separate call to mlx_vlm.lora.main().

    Args:
        config: KiCadVisionSFTConfig with training parameters.

    Returns:
        Dict with checkpoint path, total_steps, chunks_completed.
    """
    if not config.data.exists():
        raise FileNotFoundError(f"Training data not found: {config.data}")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    lora_main = _get_lora_main()

    # Monkey-patch mlx_vlm.lora.load_dataset for local save_to_disk format
    import mlx_vlm.lora as lora_mod

    _original_load_dataset = getattr(lora_mod, "load_dataset", None)

    if _original_load_dataset:
        from datasets import load_from_disk

        def _local_aware_load(path, *args, **kwargs):
            local_path = Path(path)
            if local_path.exists():
                if (local_path / "dataset_info.json").exists() or (local_path / "features.json").exists():
                    logger.info("Using load_from_disk for local dataset: %s", local_path)
                    ds = load_from_disk(local_path)
                    if hasattr(ds, "get"):
                        return ds.get("train", ds)
                    return ds
            return _original_load_dataset(path, *args, **kwargs)

        lora_mod.load_dataset = _local_aware_load

    total_steps = 0
    last_checkpoint_dir = config.output_dir

    try:
        for chunk_idx in range(config.max_chunks):
            if total_steps >= config.max_steps:
                logger.info("Reached max_steps (%d). Stopping.", config.max_steps)
                break

            remaining = config.max_steps - total_steps
            chunk_steps = min(config.chunk_size, remaining)

            chunk_output = config.output_dir / f"chunk-{chunk_idx:04d}"

            logger.info(
                "Chunk %d/%d: steps %d-%d, output=%s",
                chunk_idx + 1,
                config.max_chunks,
                total_steps,
                total_steps + chunk_steps,
                chunk_output,
            )

            # Resume from previous chunk
            adapter_path: str | None = None
            if chunk_idx > 0:
                prev_chunk = config.output_dir / f"chunk-{chunk_idx - 1:04d}"
                if (prev_chunk / "adapters.safetensors").exists():
                    adapter_path = str(prev_chunk)

            args = _build_lora_args(
                config=config,
                chunk_steps=chunk_steps,
                adapter_path=adapter_path,
                output_path=str(chunk_output),
            )

            lora_main(args)
            total_steps += chunk_steps
            last_checkpoint_dir = chunk_output

            # Memory cleanup between chunks
            gc.collect()
            try:
                import torch
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    torch.mps.empty_cache()
            except ImportError:
                pass

            logger.info("Chunk %d complete. Total steps: %d", chunk_idx + 1, total_steps)

    finally:
        if _original_load_dataset:
            lora_mod.load_dataset = _original_load_dataset

    # Consolidate final adapter to output root
    _consolidate_checkpoint(last_checkpoint_dir, config.output_dir)

    return {
        "checkpoint_path": str(config.output_dir),
        "total_steps": total_steps,
        "chunks_completed": min(
            config.max_chunks,
            (total_steps + config.chunk_size - 1) // config.chunk_size,
        ),
    }


def _consolidate_checkpoint(chunk_dir: Path, output_dir: Path) -> None:
    """Copy final chunk adapter to output_dir root for easy loading."""
    adapters_src = chunk_dir / "adapters.safetensors"
    if not adapters_src.exists() and chunk_dir.name.endswith(".safetensors"):
        adapters_src = chunk_dir

    if adapters_src.exists():
        shutil.copy2(adapters_src, output_dir / "adapters.safetensors")
        logger.info("Consolidated adapter to %s", output_dir)
    else:
        logger.warning("No adapters.safetensors found in %s", chunk_dir)
