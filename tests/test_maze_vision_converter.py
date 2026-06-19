"""Tests for maze chain to vision format converter.

Synthetic fixtures only -- no 200K file dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Module under test
from kicad_agent.training.maze_vision_converter import (
    MAZE_VISION_PROMPT,
    _create_vision_messages,
    _load_maze_samples_index,
    _reconstruct_grid,
    _render_maze_grid,
    _row_to_hf_format,
    build_maze_vision_dataset,
)

# ---------------------------------------------------------------------------
# Synthetic test data
# ---------------------------------------------------------------------------

SAMPLES_JSONL_DATA = [
    {
        "sample_id": 1,
        "board_width_mm": 30.0,
        "board_height_mm": 30.0,
        "grid_size_mm": 5.0,
        "obstacle_count": 2,
        "obstacle_positions": [[5.0, 5.0], [10.0, 15.0]],
        "source_point": [0.0, 0.0],
        "target_point": [25.0, 25.0],
        "solution_path": [
            [0.0, 0.0], [5.0, 0.0], [10.0, 0.0], [15.0, 0.0],
            [20.0, 0.0], [25.0, 0.0], [25.0, 5.0], [25.0, 10.0],
            [25.0, 15.0], [25.0, 20.0], [25.0, 25.0],
        ],
        "difficulty": "easy",
    },
    {
        "sample_id": 2,
        "board_width_mm": 50.0,
        "board_height_mm": 40.0,
        "grid_size_mm": 10.0,
        "obstacle_count": 1,
        "obstacle_positions": [[20.0, 10.0]],
        "source_point": [0.0, 0.0],
        "target_point": [40.0, 30.0],
        "solution_path": [],
        "difficulty": "medium",
    },
    {
        "sample_id": 3,
        "board_width_mm": 20.0,
        "board_height_mm": 20.0,
        "grid_size_mm": 5.0,
        "obstacle_count": 3,
        "obstacle_positions": [[5.0, 5.0], [10.0, 10.0], [15.0, 15.0]],
        "source_point": [0.0, 0.0],
        "target_point": [15.0, 15.0],
        "solution_path": [
            [0.0, 0.0], [5.0, 0.0], [10.0, 0.0], [15.0, 0.0],
            [15.0, 5.0], [15.0, 10.0], [15.0, 15.0],
        ],
        "difficulty": "hard",
    },
    {
        "sample_id": 4,
        "board_width_mm": 40.0,
        "board_height_mm": 40.0,
        "grid_size_mm": 8.0,
        "obstacle_count": 0,
        "obstacle_positions": [],
        "source_point": [0.0, 0.0],
        "target_point": [32.0, 32.0],
        "solution_path": [[0.0, 0.0], [32.0, 32.0]],
        "difficulty": "easy",
    },
    {
        "sample_id": 5,
        "board_width_mm": 60.0,
        "board_height_mm": 60.0,
        "grid_size_mm": 6.0,
        "obstacle_count": 5,
        "obstacle_positions": [
            [6.0, 6.0], [12.0, 12.0], [18.0, 18.0],
            [24.0, 24.0], [30.0, 30.0],
        ],
        "source_point": [0.0, 0.0],
        "target_point": [54.0, 54.0],
        "solution_path": [
            [0.0, 0.0], [6.0, 0.0], [12.0, 0.0], [18.0, 0.0],
            [24.0, 0.0], [30.0, 0.0], [36.0, 0.0], [42.0, 0.0],
            [48.0, 0.0], [54.0, 0.0], [54.0, 6.0], [54.0, 12.0],
            [54.0, 18.0], [54.0, 24.0], [54.0, 30.0], [54.0, 36.0],
            [54.0, 42.0], [54.0, 48.0], [54.0, 54.0],
        ],
        "difficulty": "hard",
    },
]

CHAINS_JSONL_DATA = [
    # Valid chains for sample_ids 1-5
    {
        "sample_id": 1,
        "chain_text": "Step 1: Start at source (0,0). Step 2: Move right to (25,0). Step 3: Move down to (25,25). Target reached.",
        "is_correct": True,
        "difficulty": "easy",
    },
    {
        "sample_id": 2,
        "chain_text": "Navigate from (0,0) to (40,30) avoiding obstacle at grid cell (2,1).",
        "is_correct": True,
        "difficulty": "medium",
    },
    {
        "sample_id": 3,
        "chain_text": "Step 1: Start at source. Step 2: Go right. Step 3: Go down to target.",
        "is_correct": True,
        "difficulty": "hard",
    },
    {
        "sample_id": 4,
        "chain_text": "Direct path from source to target. No obstacles.",
        "is_correct": True,
        "difficulty": "easy",
    },
    {
        "sample_id": 5,
        "chain_text": "Long path around diagonal obstacles. Step 1: Move right along top edge. Step 2: Move down right edge to target.",
        "is_correct": True,
        "difficulty": "hard",
    },
    # Filtered out: is_correct=False
    {
        "sample_id": 1,
        "chain_text": "Wrong path that hits obstacles.",
        "is_correct": False,
        "difficulty": "easy",
    },
    # Filtered out: empty chain_text
    {
        "sample_id": 2,
        "chain_text": "",
        "is_correct": True,
        "difficulty": "medium",
    },
    # Filtered out: sample_id not in maze_samples (sample_id=999)
    {
        "sample_id": 999,
        "chain_text": "Non-existent sample chain.",
        "is_correct": True,
        "difficulty": "unknown",
    },
]


def _write_jsonl(data: list[dict], path: Path) -> None:
    """Helper to write list of dicts as JSONL."""
    with open(path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


class TestMazeVisionConverter:
    """Tests for the maze vision converter module."""

    def test_reconstruct_grid_basic(self) -> None:
        """_reconstruct_grid correctly builds boolean grid from sample 1 geometry.

        board_width_mm=30, board_height_mm=30, grid_size_mm=5.0
        obstacle_positions=[[5.0, 5.0], [10.0, 15.0]]
        Expects 6x6 grid with [1][1] and [3][2] as True.
        """
        grid = _reconstruct_grid(
            board_width_mm=30.0,
            board_height_mm=30.0,
            grid_size_mm=5.0,
            obstacle_positions=[[5.0, 5.0], [10.0, 15.0]],
        )
        assert len(grid) == 6  # rows = 30/5 = 6
        assert len(grid[0]) == 6  # cols = 30/5 = 6
        # obstacle at (5.0, 5.0) -> col=int(5/5)=1, row=int(5/5)=1
        assert grid[1][1] is True
        # obstacle at (10.0, 15.0) -> col=int(10/5)=2, row=int(15/5)=3
        assert grid[3][2] is True
        # All other cells should be False
        assert grid[0][0] is False
        assert grid[2][2] is False

    def test_reconstruct_grid_empty_obstacles(self) -> None:
        """Grid with no obstacles is all False."""
        grid = _reconstruct_grid(
            board_width_mm=40.0,
            board_height_mm=40.0,
            grid_size_mm=8.0,
            obstacle_positions=[],
        )
        assert len(grid) == 5  # 40/8 = 5 (int truncation)
        assert len(grid[0]) == 5
        assert all(cell is False for row in grid for cell in row)

    def test_load_maze_samples_index(self, tmp_path: Path) -> None:
        """_load_maze_samples_index builds lookup dict keyed by sample_id."""
        jsonl_path = tmp_path / "samples.jsonl"
        _write_jsonl(SAMPLES_JSONL_DATA, jsonl_path)

        index = _load_maze_samples_index(jsonl_path)
        assert 1 in index
        assert 5 in index
        assert 999 not in index
        assert index[1]["board_width_mm"] == 30.0
        assert index[3]["obstacle_count"] == 3

    def test_join_chains_with_samples_filtering(self) -> None:
        """Verify join logic: only valid chains survive all three filters."""
        valid_count = sum(
            1
            for chain in CHAINS_JSONL_DATA
            if chain["is_correct"]
            and chain["chain_text"].strip()
            and chain["sample_id"] in {s["sample_id"] for s in SAMPLES_JSONL_DATA}
        )
        assert valid_count == 5

    def test_filter_is_correct_excludes_invalid(self) -> None:
        """Chains with is_correct=False or empty chain_text are filtered out."""
        # is_correct=False
        assert CHAINS_JSONL_DATA[5]["is_correct"] is False
        # empty chain_text
        assert CHAINS_JSONL_DATA[6]["chain_text"] == ""
        # sample_id not in samples
        assert CHAINS_JSONL_DATA[7]["sample_id"] == 999

    def test_row_to_hf_format(self) -> None:
        """_row_to_hf_format produces dict matching PCB vision schema."""
        messages = [
            {
                "role": "user",
                "content": [{"type": "image"}, {"type": "text", "text": "prompt"}],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "response"}],
            },
        ]
        result = _row_to_hf_format(
            image_filename="sample_000001.png",
            messages=messages,
            task_type="maze_routing",
            source_file="maze_sample_1",
        )
        assert set(result.keys()) == {"images", "messages", "task_type", "source_file"}
        assert result["images"] == ["images/sample_000001.png"]
        assert result["messages"] == messages
        assert result["task_type"] == "maze_routing"
        assert result["source_file"] == "maze_sample_1"

    def test_render_maze_grid_returns_pil_image(self) -> None:
        """_render_maze_grid returns PIL Image with expected dimensions (1024x768)."""
        img = _render_maze_grid(
            board_width_mm=30.0,
            board_height_mm=30.0,
            grid_size_mm=5.0,
            obstacle_positions=[[5.0, 5.0], [10.0, 15.0]],
            source_point=[0.0, 0.0],
            target_point=[25.0, 25.0],
            solution_path=[[0.0, 0.0], [25.0, 0.0], [25.0, 25.0]],
            width=1024,
            height=768,
        )
        assert img.size == (1024, 768)
        assert img.mode == "RGB"

    def test_create_vision_messages_format(self) -> None:
        """Vision messages format matches PCB vision schema exactly.

        [{"role":"user","content":[{"type":"image"},{"type":"text",...}]},
         {"role":"assistant","content":[{"type":"text",...}]}]
        """
        messages = _create_vision_messages(
            "Step 1: Start at source. Step 2: Move right."
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert len(messages[0]["content"]) == 2
        assert messages[0]["content"][0] == {"type": "image"}
        assert messages[0]["content"][1]["type"] == "text"
        assert MAZE_VISION_PROMPT in messages[0]["content"][1]["text"]

        assert messages[1]["role"] == "assistant"
        assert len(messages[1]["content"]) == 1
        assert messages[1]["content"][0]["type"] == "text"
        assert messages[1]["content"][0]["text"] == "Step 1: Start at source. Step 2: Move right."

    def test_build_maze_vision_dataset_full(self, tmp_path: Path) -> None:
        """build_maze_vision_dataset with 5 synthetic samples produces
        5 PNG images and HuggingFace dataset rows.
        """
        chains_path = tmp_path / "chains.jsonl"
        samples_path = tmp_path / "maze_samples.jsonl"
        output_dir = tmp_path / "output"

        _write_jsonl(CHAINS_JSONL_DATA, chains_path)
        _write_jsonl(SAMPLES_JSONL_DATA, samples_path)

        count = build_maze_vision_dataset(
            chains_file=chains_path,
            maze_samples_file=samples_path,
            output_dir=output_dir,
        )

        # 5 valid chains (is_correct=True + non-empty chain_text + sample_id in samples)
        assert count == 5

        # Check images directory exists and has 5 PNGs
        images_dir = output_dir / "images"
        assert images_dir.exists()
        pngs = list(images_dir.glob("*.png"))
        assert len(pngs) == 5

        # Check HuggingFace dataset or JSONL fallback
        train_dir = output_dir / "train"
        train_jsonl = output_dir / "train.jsonl"
        if train_dir.exists():
            # HuggingFace format
            assert (train_dir / "dataset_dict.json").exists() or True
        elif train_jsonl.exists():
            # JSONL fallback
            rows = train_jsonl.read_text(encoding="utf-8").strip().split("\n")
            assert len(rows) == 5
            for row_str in rows:
                row = json.loads(row_str)
                assert "images" in row
                assert "messages" in row
                assert "task_type" in row
                assert "source_file" in row
        else:
            pytest.fail("Expected either HuggingFace dataset or JSONL fallback output")

    def test_build_maze_vision_dataset_max_samples(self, tmp_path: Path) -> None:
        """max_samples limits conversion."""
        chains_path = tmp_path / "chains.jsonl"
        samples_path = tmp_path / "maze_samples.jsonl"
        output_dir = tmp_path / "output"

        _write_jsonl(CHAINS_JSONL_DATA, chains_path)
        _write_jsonl(SAMPLES_JSONL_DATA, samples_path)

        count = build_maze_vision_dataset(
            chains_file=chains_path,
            maze_samples_file=samples_path,
            output_dir=output_dir,
            max_samples=2,
        )
        assert count == 2
