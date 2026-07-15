"""Maze chain to vision format converter.

Joins maze_samples_100k.jsonl (rendering geometry) with chains_100k.jsonl
(reasoning text) by sample_id, renders maze grids as PNG images via
matplotlib, filters to is_correct=True only, and outputs HuggingFace
vision dataset format matching the existing PCB vision schema.

Provides:
- build_maze_vision_dataset: main entry point for maze data conversion
- _reconstruct_grid: boolean grid from maze geometry
- _render_maze_grid: matplotlib-based maze renderer
- _create_vision_messages: PCB-vision-compatible message builder
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend -- must be before pyplot import

logger = logging.getLogger(__name__)

# Vision prompt for maze routing tasks
MAZE_VISION_PROMPT = (
    "Analyze this maze routing problem. The grid shows obstacles (dark cells), "
    "source (green), and target (red). Find the shortest path from source to target "
    "avoiding obstacles. Use <point x,y> coordinate notation."
)

# Task type identifier for maze vision data
TASK_TYPE = "maze_routing"


def build_maze_vision_dataset(
    chains_file: Path,
    maze_samples_file: Path,
    output_dir: Path,
    max_samples: int | None = None,
) -> int:
    """Convert maze routing chains to HuggingFace vision training dataset.

    Reads chains JSONL and maze_samples JSONL, joins by sample_id,
    renders maze grids as PNG images, and produces a HuggingFace-compatible
    vision dataset with images + messages columns.

    Only chains with is_correct=True and non-empty chain_text are included.
    Chains whose sample_id has no matching maze_sample are skipped.

    Args:
        chains_file: Path to chains_100k.jsonl.
        maze_samples_file: Path to maze_samples_100k.jsonl.
        output_dir: Output directory for vision dataset.
        max_samples: Maximum samples to convert (None = all).

    Returns:
        Number of samples converted.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # Build sample_id lookup from maze_samples
    samples_index = _load_maze_samples_index(maze_samples_file)
    logger.info(
        "Loaded %d maze samples from %s",
        len(samples_index),
        maze_samples_file,
    )

    # Stream chains file, filtering as we go
    converted = 0
    metadata_rows = []

    with open(chains_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            chain = json.loads(line)

            # Filter: is_correct=True AND chain_text non-empty AND sample_id exists
            if not chain.get("is_correct", False):
                continue
            chain_text = chain.get("chain_text", "")
            if not chain_text.strip():
                continue
            sample_id = chain.get("sample_id")
            if sample_id is None or sample_id not in samples_index:
                continue

            try:
                sample = samples_index[sample_id]

                # Reconstruct grid and render
                image_path = _render_and_save(
                    sample=sample,
                    idx=converted,
                    images_dir=images_dir,
                )
                if image_path is None:
                    logger.warning("Failed to render sample %d, skipping", sample_id)
                    continue

                # Create vision messages matching PCB vision schema
                messages = _create_vision_messages(chain_text)

                # Build HuggingFace row
                source_file = f"maze_sample_{sample_id}"
                row = _row_to_hf_format(
                    image_filename=image_path.name,
                    messages=messages,
                    task_type=TASK_TYPE,
                    source_file=source_file,
                )
                metadata_rows.append(row)
                converted += 1

                if converted % 100 == 0 and converted > 0:
                    logger.info("Converted %d samples", converted)

            except Exception as exc:
                logger.warning("Failed to convert chain for sample %d: %s", sample_id, exc)

            if max_samples is not None and converted >= max_samples:
                break

    # Save as HuggingFace dataset (load_from_disk compatible)
    _save_dataset(output_dir, metadata_rows)

    logger.info(
        "Maze vision dataset complete: %d samples in %s",
        converted,
        output_dir,
    )
    return converted


def _load_maze_samples_index(path: Path) -> dict[int, dict[str, Any]]:
    """Stream maze_samples JSONL and build {sample_id: sample_dict} lookup.

    Each sample has: sample_id (int), board_width_mm (float),
    board_height_mm (float), grid_size_mm (float), obstacle_count (int),
    obstacle_positions (list[list[float]]), source_point (list[float]),
    target_point (list[float]), solution_path (list[list[float]]),
    difficulty (str).
    """
    index: dict[int, dict[str, Any]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            sample = json.loads(line)
            sid = sample.get("sample_id")
            if sid is not None:
                index[int(sid)] = sample
    return index


def _reconstruct_grid(
    board_width_mm: float,
    board_height_mm: float,
    grid_size_mm: float,
    obstacle_positions: list[list[float]],
) -> list[list[bool]]:
    """Reconstruct a boolean grid from sample metadata.

    Obstacle positions are marked True. All other cells are False.
    Follows the pattern from src/volta/training/chains.py.
    """
    rows = max(1, int(board_height_mm / grid_size_mm))
    cols = max(1, int(board_width_mm / grid_size_mm))
    grid = [[False] * cols for _ in range(rows)]

    for obs in obstacle_positions:
        if len(obs) < 2:
            continue
        ox, oy = obs[0], obs[1]
        c = int(ox / grid_size_mm)
        r = int(oy / grid_size_mm)
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = True

    return grid


def _render_maze_grid(
    board_width_mm: float,
    board_height_mm: float,
    grid_size_mm: float,
    obstacle_positions: list[list[float]],
    source_point: list[float] | tuple[float, float],
    target_point: list[float] | tuple[float, float],
    solution_path: list[list[float]] | None = None,
    width: int = 1024,
    height: int = 768,
) -> "PIL.Image.Image":
    """Render a maze grid as a PNG image.

    Grid cells are colored: white=clear, dark gray=obstacle,
    green=source, red=target, blue=path.

    Returns PIL Image of size (width, height).
    """
    import matplotlib.pyplot as plt
    import numpy as np
    from PIL import Image as PILImage

    rows = max(1, int(board_height_mm / grid_size_mm))
    cols = max(1, int(board_width_mm / grid_size_mm))

    # Build boolean grid as numpy array
    grid = np.zeros((rows, cols), dtype=int)  # 0=clear
    for obs in obstacle_positions:
        if len(obs) < 2:
            continue
        ox, oy = obs[0], obs[1]
        c = int(ox / grid_size_mm)
        r = int(oy / grid_size_mm)
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = 1  # obstacle

    # Mark source and target grid positions
    src_col = max(0, min(int(source_point[0] / grid_size_mm), cols - 1))
    src_row = max(0, min(int(source_point[1] / grid_size_mm), rows - 1))
    tgt_col = max(0, min(int(target_point[0] / grid_size_mm), cols - 1))
    tgt_row = max(0, min(int(target_point[1] / grid_size_mm), rows - 1))

    fig, ax = plt.subplots(1, 1, figsize=(width / 100, height / 100), dpi=100)
    ax.imshow(grid, cmap="Greys", vmin=0, vmax=2, alpha=0.8)

    # Draw source (green) and target (red)
    ax.plot(src_col, src_row, "gs", markersize=12, label="Source")
    ax.plot(tgt_col, tgt_row, "rs", markersize=12, label="Target")

    # Draw solution path (blue line)
    if solution_path:
        path_cols = [int(p[0] / grid_size_mm) for p in solution_path]
        path_rows = [int(p[1] / grid_size_mm) for p in solution_path]
        ax.plot(path_cols, path_rows, "b-", linewidth=2, alpha=0.6)

    ax.set_xlim(-0.5, cols - 0.5)
    ax.set_ylim(rows - 0.5, -0.5)  # Invert Y for image coordinates
    ax.set_aspect("equal")
    ax.grid(True, linewidth=0.5, alpha=0.3)
    ax.set_xlabel("Column (grid units)")
    ax.set_ylabel("Row (grid units)")

    # Convert to PIL Image
    fig.canvas.draw()
    buf = fig.canvas.buffer_rgba()
    img = PILImage.frombytes(
        "RGBA",
        fig.canvas.get_width_height(),
        buf,
    ).convert("RGB")
    plt.close(fig)  # Prevent memory leak (Pitfall 3 from RESEARCH.md)
    return img.resize((width, height))


def _render_and_save(
    sample: dict[str, Any],
    idx: int,
    images_dir: Path,
) -> Path | None:
    """Reconstruct grid from sample, render PNG, save to images_dir.

    Returns the path to the saved image, or None on failure.
    """
    try:
        img = _render_maze_grid(
            board_width_mm=float(sample["board_width_mm"]),
            board_height_mm=float(sample["board_height_mm"]),
            grid_size_mm=float(sample["grid_size_mm"]),
            obstacle_positions=sample.get("obstacle_positions", []),
            source_point=sample.get("source_point", [0.0, 0.0]),
            target_point=sample.get("target_point", [0.0, 0.0]),
            solution_path=sample.get("solution_path"),
        )
        out_path = images_dir / f"maze_{idx:06d}.png"
        img.save(out_path, "PNG")
        return out_path
    except Exception as exc:
        logger.warning("Render failed for sample %d: %s", sample.get("sample_id"), exc)
        return None


def _create_vision_messages(chain_text: str) -> list[dict[str, Any]]:
    """Build vision messages matching exact PCB vision schema format.

    Format:
    [{"role":"user","content":[{"type":"image"},{"type":"text",...}]},
     {"role":"assistant","content":[{"type":"text",...}]}]
    """
    return [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": MAZE_VISION_PROMPT},
            ],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": chain_text},
            ],
        },
    ]


def _row_to_hf_format(
    image_filename: str,
    messages: list[dict[str, Any]],
    task_type: str,
    source_file: str,
) -> dict[str, Any]:
    """Convert to HuggingFace dataset format matching PCB vision schema.

    Keys: images, messages, task_type, source_file.
    """
    return {
        "images": [f"images/{image_filename}"],
        "messages": messages,
        "task_type": task_type,
        "source_file": source_file,
    }


def _save_dataset(
    output_dir: Path,
    metadata_rows: list[dict[str, Any]],
) -> None:
    """Save converted rows as HuggingFace Dataset or JSONL fallback."""
    try:
        from datasets import Dataset, Image as HFImage, Sequence

        hf_rows = []
        for row in metadata_rows:
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
        logger.info("Saved JSONL fallback to %s", meta_path)
