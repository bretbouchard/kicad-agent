"""Vision training data builder for KiCad Gemma 4 fine-tuning.

Converts existing text-only ChatML JSONL training data to mlx-vlm
vision format by pre-rendering PCB/schematic images and restructuring
messages with image + text multimodal content.

Provides:
- build_vision_dataset: main entry point for data conversion
- VisionDataRow: structured vision training sample
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Vision prompt for PCB analysis tasks
PCB_VISION_PROMPT = (
    "Analyze this PCB layout. Identify component placement, routing patterns, "
    "clearance violations, and potential improvements. When suggesting edits, "
    "use KiCad JSON operation format with exact coordinates from the image."
)

SCHEMATIC_VISION_PROMPT = (
    "Analyze this schematic. Identify connections, component values, net labels, "
    "and potential issues. When suggesting edits, use KiCad JSON operation format."
)

ROUTING_VISION_PROMPT = (
    "Analyze this PCB routing. Identify unrouted nets, routing conflicts, "
    "clearance violations, and via placement issues. Suggest specific routing "
    "improvements using KiCad JSON operation format."
)


@dataclass(frozen=True)
class VisionDataRow:
    """A single vision training data row in mlx-vlm format."""
    image_path: Path
    messages: list[dict[str, Any]]
    task_type: str
    source_file: str


def build_vision_dataset(
    input_jsonl: Path,
    output_dir: Path,
    pcb_dir: Path | None = None,
    max_samples: int | None = None,
) -> int:
    """Convert text-only JSONL to vision training dataset.

    Reads ChatML JSONL training data, looks up corresponding PCB/schematic
    files, renders them to PNG, and produces a HuggingFace-compatible
    vision dataset with images + messages columns.

    Args:
        input_jsonl: Path to input JSONL file (ChatML format).
        output_dir: Output directory for vision dataset.
        pcb_dir: Directory containing PCB/schematic files referenced in training data.
        max_samples: Maximum samples to convert (None = all).

    Returns:
        Number of samples converted.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    samples = _load_jsonl(input_jsonl)
    if max_samples:
        samples = samples[:max_samples]

    converted = 0
    metadata_rows = []

    for idx, sample in enumerate(samples):
        try:
            row = _convert_sample(sample, idx, images_dir, pcb_dir)
            if row is not None:
                metadata_rows.append(_row_to_hf_format(row))
                converted += 1
        except Exception as exc:
            logger.warning("Failed to convert sample %d: %s", idx, exc)

        if converted % 100 == 0 and converted > 0:
            logger.info("Converted %d/%d samples", converted, len(samples))

    # Save as HuggingFace dataset (load_from_disk compatible)
    try:
        from datasets import Dataset, Features, Value, Sequence, Image as HFImage

        hf_rows = []
        for row in metadata_rows:
            # Load actual image for HF Image feature
            img_path = output_dir / row["images"][0]
            hf_rows.append({
                "images": [str(img_path.resolve())],
                "messages": row["messages"],
                "task_type": row["task_type"],
                "source_file": row["source_file"],
            })

        ds = Dataset.from_list(hf_rows)
        ds = ds.cast_column("images", Sequence(HFImage()))
        ds.save_to_disk(output_dir / "train")
        logger.info("Saved HuggingFace dataset to %s/train", output_dir)
    except ImportError:
        # Fallback: save as JSONL if datasets not available
        meta_path = output_dir / "train.jsonl"
        with open(meta_path, "w", encoding="utf-8") as f:
            for row in metadata_rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    logger.info(
        "Vision dataset complete: %d samples in %s",
        converted,
        output_dir,
    )
    return converted


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSONL file."""
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def _convert_sample(
    sample: dict[str, Any],
    idx: int,
    images_dir: Path,
    pcb_dir: Path | None,
) -> VisionDataRow | None:
    """Convert a single text sample to vision format."""
    task_type = sample.get("task_type", "board_analysis")

    # Select vision prompt based on task type
    if "rout" in task_type:
        vision_prompt = ROUTING_VISION_PROMPT
    elif "schematic" in task_type or "sch" in task_type:
        vision_prompt = SCHEMATIC_VISION_PROMPT
    else:
        vision_prompt = PCB_VISION_PROMPT

    # Find source PCB/schematic file
    source_file = sample.get("source_file", sample.get("pcb_file", ""))
    if not source_file and pcb_dir:
        source_file = _find_pcb_for_sample(sample, pcb_dir)

    if not source_file:
        # Cannot convert without a PCB file — create text-only entry
        return None

    pcb_path = Path(source_file)
    if pcb_dir and not pcb_path.is_absolute():
        pcb_path = pcb_dir / pcb_path

    if not pcb_path.exists():
        return None

    # Render to PNG — fall back to PCB render if schematic fails
    image_path = _render_pcb_for_training(pcb_path, idx, images_dir)
    if image_path is None and pcb_path.suffix == ".kicad_sch" and pcb_dir:
        # Schematic failed (missing libs?) — try PCB from same project
        sch_stem = pcb_path.stem
        for pcb in sorted(pcb_dir.rglob(f"{sch_stem}.kicad_pcb")):
            image_path = _render_pcb_for_training(pcb, idx, images_dir)
            if image_path is not None:
                pcb_path = pcb  # Update source_file to PCB
                break
    if image_path is None:
        return None

    # Extract assistant response from ChatML text
    assistant_text = _extract_assistant_text(sample)

    if not assistant_text:
        return None

    # Build vision messages
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": vision_prompt},
            ],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": assistant_text},
            ],
        },
    ]

    return VisionDataRow(
        image_path=image_path,
        messages=messages,
        task_type=task_type,
        source_file=str(pcb_path),
    )


def _find_pcb_for_sample(sample: dict, pcb_dir: Path) -> str:
    """Find a PCB/schematic file matching the sample's task type.

    Returns a path relative to pcb_dir (not cwd) so the caller can
    resolve against pcb_dir without doubling.

    Randomly distributes available files across samples so the model
    sees diverse boards instead of always the same one.
    """
    task_type = sample.get("task_type", "board_analysis")
    base = Path(pcb_dir)

    # Try to match by name pattern first
    name = sample.get("board_name", sample.get("name", ""))
    if name:
        for ext in ("*.kicad_pcb", "*.kicad_sch"):
            match = list(base.glob(f"{name}.{ext[2:]}"))
            if match:
                return str(match[0].relative_to(base))

    # Select file type by task
    if "schematic" in task_type or "sch" in task_type:
        candidates = sorted(base.rglob("*.kicad_sch"))
    elif "rout" in task_type:
        candidates = sorted(base.rglob("*.kicad_pcb"))
    else:
        # board_analysis, component_knowledge — prefer PCB
        candidates = sorted(base.rglob("*.kicad_pcb"))
        if not candidates:
            candidates = sorted(base.rglob("*.kicad_sch"))

    # Filter out boards that kicad-cli can't load (validated at import time)
    candidates = [c for c in candidates if c.name != "smd_test_board.kicad_pcb"]

    if not candidates:
        return ""

    return str(random.choice(candidates).relative_to(base))


def _render_pcb_for_training(
    pcb_path: Path,
    idx: int,
    images_dir: Path,
) -> Path | None:
    """Render PCB or schematic to PNG for training dataset."""
    try:
        from volta.export.pcb_image_renderer import (
            render_pcb_layer_png,
            render_schematic_png,
        )

        if pcb_path.suffix == ".kicad_sch":
            image = render_schematic_png(
                pcb_path,
                width=1024,
                height=768,
            )
        else:
            image = render_pcb_layer_png(
                pcb_path,
                width=1024,
                height=768,
            )

        out_path = images_dir / f"sample_{idx:06d}.png"
        image.save(out_path, "PNG")
        return out_path
    except Exception as exc:
        logger.warning("Failed to render %s: %s", pcb_path, exc)
        return None


def _extract_assistant_text(sample: dict) -> str:
    """Extract assistant response from ChatML text field."""
    text = sample.get("text", "")
    if not text:
        return ""

    # ChatML format: extract assistant content between markers
    parts = text.split("<|im_start|>assistant\n")
    if len(parts) > 1:
        assistant_part = parts[-1]
        # Remove trailing end marker
        end_marker = "<|im_end|>"
        if end_marker in assistant_part:
            assistant_part = assistant_part[: assistant_part.index(end_marker)]
        return assistant_part.strip()

    return text.strip()


def _row_to_hf_format(row: VisionDataRow) -> dict[str, Any]:
    """Convert VisionDataRow to HuggingFace dataset format."""
    # Relative image path for portability
    rel_image = f"images/{row.image_path.name}"
    return {
        "images": [rel_image],
        "messages": row.messages,
        "task_type": row.task_type,
        "source_file": row.source_file,
    }
