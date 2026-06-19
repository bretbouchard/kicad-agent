"""Adapter metadata registry with versioned JSON storage.

Manages adapter metadata files including training parameters, dataset
composition, provenance fields, and dataset symlinks to external storage.

Threat mitigations (STRIDE):
- T-97-03: Auto-increment version on conflict; force=False default prevents silent overwrite
- T-97-06: Metadata includes dataset composition, training params, timestamps for audit trail
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class DatasetInfo(BaseModel):
    """Dataset composition metadata for adapter provenance."""

    model_config = ConfigDict(frozen=True)

    maze_samples: int = Field(description="Number of maze vision samples")
    pcb_samples: int = Field(description="Number of PCB vision samples")
    total_samples: int = Field(description="Total samples in unified dataset")
    maze_chains_file: str = Field(
        default="training_output/chains_100k.jsonl",
        description="Path to maze chains file used for conversion",
    )
    maze_samples_file: str = Field(
        default="training_output/maze_samples_100k.jsonl",
        description="Path to maze samples file used for conversion",
    )
    pcb_vision_dir: str = Field(
        default="training_output/vision_data/train/",
        description="Path to PCB vision dataset directory",
    )


class AdapterMetadata(BaseModel):
    """Versioned adapter training metadata.

    Captures all training parameters, dataset composition, and provenance
    fields needed to reproduce an adapter training run.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = Field(description="Version label (v1, v2, etc.)")
    base_model: str = Field(
        default="google/gemma-4-12b-it",
        description="HuggingFace model ID of the base model",
    )
    created: str = Field(description="ISO 8601 timestamp of metadata creation")
    training_platform: str = Field(
        default="vast.ai RTX 3090",
        description="Training hardware/platform description",
    )
    training_steps: int = Field(
        default=400,
        description="Number of training steps completed",
    )
    training_loss: float | None = Field(
        default=None,
        description="Final training loss value",
    )
    lora_rank: int = Field(
        default=16,
        description="LoRA rank used during training",
    )
    lora_alpha: int = Field(
        default=32,
        description="LoRA alpha parameter used during training",
    )
    learning_rate: float = Field(
        default=1e-5,
        description="Learning rate used during training",
    )
    dataset: DatasetInfo = Field(description="Dataset composition information")
    verified_mlx: bool = Field(
        default=False,
        description="Whether adapter has been verified on Apple MLX locally",
    )
    notes: str = Field(
        default="",
        description="Free-form notes about this training run",
    )
    # Council MED-6: provenance fields for reproducibility
    vast_instance_id: str | None = Field(
        default=None,
        description="Vast.ai instance ID if trained on cloud GPU",
    )
    training_started: str | None = Field(
        default=None,
        description="ISO 8601 timestamp when training started",
    )
    training_completed: str | None = Field(
        default=None,
        description="ISO 8601 timestamp when training completed",
    )
    git_commit: str | None = Field(
        default=None,
        description="Git commit hash of the training code",
    )
    actual_cost_usd: float | None = Field(
        default=None,
        description="Actual training cost in USD",
    )


class AdapterRegistry:
    """Manages adapter metadata and dataset symlinks.

    Writes versioned training_metadata.json files to adapter directories.
    Auto-increments version on conflict to prevent silent overwrites.
    Creates symlinks from training_output to external storage for datasets.
    """

    def __init__(
        self,
        base_dir: Path = Path("/Volumes/Storage/models/kicad-agent/adapters"),
    ) -> None:
        self._base_dir = base_dir

    def write_metadata(
        self,
        adapter_name: str,
        metadata: AdapterMetadata,
        force: bool = False,
    ) -> Path:
        """Write metadata JSON for an adapter. Auto-increments version if exists.

        Args:
            adapter_name: Name of the adapter directory.
            metadata: Adapter metadata to write.
            force: If True, overwrite existing file without version increment.
                   If False (default), auto-increment version to prevent overwrite.

        Returns:
            Path to the written metadata JSON file.
        """
        adapter_dir = self._base_dir / adapter_name
        adapter_dir.mkdir(parents=True, exist_ok=True)
        meta_path = adapter_dir / "training_metadata.json"

        if meta_path.exists() and not force:
            existing = json.loads(meta_path.read_text())
            old_ver = existing.get("version", "v0")
            try:
                ver_num = int(old_ver.lstrip("v"))
                new_ver = f"v{ver_num + 1}"
            except ValueError:
                new_ver = f"{old_ver}_1"
            metadata = metadata.model_copy(update={"version": new_ver})

        meta_path.write_text(
            json.dumps(json.loads(metadata.model_dump_json()), indent=2),
        )
        logger.info(
            "Wrote adapter metadata to %s (version %s)",
            meta_path,
            metadata.version,
        )
        return meta_path

    def read_metadata(self, adapter_name: str) -> AdapterMetadata | None:
        """Read metadata for an adapter.

        Args:
            adapter_name: Name of the adapter to look up.

        Returns:
            Parsed AdapterMetadata, or None if not found.
        """
        meta_path = self._base_dir / adapter_name / "training_metadata.json"
        if not meta_path.exists():
            return None
        data = json.loads(meta_path.read_text())
        return AdapterMetadata(**data)

    def create_dataset_symlinks(
        self,
        source_dir: Path,
        link_name: str,
    ) -> Path:
        """Create symlink from source_dir to external storage datasets directory.

        Creates a symlink at {base_dir}/../datasets/{link_name} pointing to
        the resolved absolute path of source_dir.

        Args:
            source_dir: Source directory containing the dataset.
            link_name: Name for the symlink in the datasets directory.

        Returns:
            Path to the created symlink.
        """
        datasets_dir = self._base_dir.parent / "datasets"
        datasets_dir.mkdir(parents=True, exist_ok=True)
        link_path = datasets_dir / link_name

        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(source_dir.resolve())

        logger.info(
            "Created symlink %s -> %s",
            link_path,
            source_dir.resolve(),
        )
        return link_path
