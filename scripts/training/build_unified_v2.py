"""Build unified dataset v2 for Gemma 4 12B multi-skill training.

Merges ALL training data sources into a single balanced HF arrow dataset:
  1. SchGen executable (7,285 NL→SKIDL text examples)
  2. Corpus multimodal (NL→SKIDL with schematic + PCB images)
  3. Legibility critiques (schematic image → legibility analysis)
  4. Placement intelligence (PCB image → placement rationale)
  5. Diagnostic vision (PCB image → blocker diagnosis)
  6. Routing strategy (board context → strategy JSON)
  7. Maze routing (DOWNSAMPLED from 135K to 20K — spatial reasoning)
  8. Existing vision data (board analysis, component knowledge, etc.)

The dataset is REBALANCED: maze drops from 95% to ~43%, NL→SKIDL becomes
the largest category at ~31%.

Output: /Volumes/Storage/schgen/unified_v2/ (HF arrow, ~3 GB)

Usage:
    python3 build_unified_v2.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from datasets import Dataset, Image as HFImage
from PIL import Image as PILImage


SCHGEN_EXECUTABLE = Path("/Volumes/Storage/schgen/converted/schgen_skidl_sft_executable.jsonl")
CORPUS_PAIRS = Path("/Volumes/Storage/schgen/our_corpus/training_pairs.jsonl")
LEGIBILITY_PAIRS = Path("/Volumes/Storage/schgen/legibility_data/legibility_training_pairs.jsonl")
PLACEMENT_PAIRS = Path("/Volumes/Storage/schgen/placement_data/placement_training_pairs.jsonl")
DIAGNOSTIC_PAIRS = Path("/Volumes/Storage/schgen/diagnostic_vision_data/diagnostic_vision_pairs.jsonl")
STRATEGY_PAIRS = Path("/Volumes/Storage/schgen/strategy_data/strategy_training_pairs.jsonl")
EXISTING_VISION = Path("/Users/bretbouchard/apps/kicad-agent/training_output/unified_vision_data/train")
MAZE_VISION = Path("/Users/bretbouchard/apps/kicad-agent/training_output/maze_vision_data/train")
OUT_DIR = Path("/Volumes/Storage/schgen/unified_v2")

# Maze downsampling target
MAZE_TARGET = 20000

# System prompt for NL→SKIDL
SKIDL_SYSTEM = """\
You are a circuit design assistant. Generate executable SKIDL Python code from natural language descriptions. \
Use the build_board() -> Circuit pattern with proper Net() wiring. Always end with ERC()."""


def _msg_text_only(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


def _msg_image() -> dict:
    return {"type": "image"}


def _load_pil(path: str | None) -> PILImage.Image | None:
    if not path:
        return None
    try:
        img = PILImage.open(path)
        img.load()
        return img.convert("RGB")
    except Exception:
        return None


def _text_example(system: str, user: str, assistant: str, task_type: str, source: str) -> dict:
    return {
        "images": [],
        "messages": [
            {"role": "system", "content": _msg_text_only(system)},
            {"role": "user", "content": _msg_text_only(user)},
            {"role": "assistant", "content": _msg_text_only(assistant)},
        ],
        "task_type": task_type,
        "source_file": source,
    }


def _multimodal_example(system: str, user: str, assistant: str,
                        images: list[PILImage.Image], task_type: str, source: str) -> dict:
    user_content = [_msg_image() for _ in images] + _msg_text_only(user)
    return {
        "images": images,
        "messages": [
            {"role": "system", "content": _msg_text_only(system)},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": _msg_text_only(assistant)},
        ],
        "task_type": task_type,
        "source_file": source,
    }


def load_schgen() -> list[dict]:
    """Load SchGen executable examples (text-only NL→SKIDL)."""
    examples = []
    if not SCHGEN_EXECUTABLE.exists():
        print(f"  WARN: {SCHGEN_EXECUTABLE} not found", file=sys.stderr)
        return examples
    with SCHGEN_EXECUTABLE.open() as f:
        for line in f:
            d = json.loads(line)
            msgs = {m["role"]: m["content"] for m in d["messages"]}
            examples.append(_text_example(
                system=msgs.get("system", SKIDL_SYSTEM),
                user=msgs["user"],
                assistant=msgs["assistant"],
                task_type="nl_to_skidl",
                source=f"schgen/{d.get('source_id', '?')}",
            ))
    return examples


def load_corpus() -> list[dict]:
    """Load corpus multimodal examples."""
    examples = []
    if not CORPUS_PAIRS.exists():
        print(f"  WARN: {CORPUS_PAIRS} not found", file=sys.stderr)
        return examples
    with CORPUS_PAIRS.open() as f:
        for line in f:
            d = json.loads(line)
            msgs = {m["role"]: m["content"] for m in d["messages"]}
            images = []
            for img_path in d.get("images", []):
                pil = _load_pil(img_path)
                if pil:
                    images.append(pil)
            if images:
                examples.append(_multimodal_example(
                    system=msgs["system"],
                    user=msgs["user"],
                    assistant=msgs["assistant"],
                    images=images,
                    task_type="nl_to_skidl_with_image",
                    source=d.get("source_id", "corpus"),
                ))
            else:
                examples.append(_text_example(
                    system=msgs["system"],
                    user=msgs["user"],
                    assistant=msgs["assistant"],
                    task_type="nl_to_skidl",
                    source=d.get("source_id", "corpus"),
                ))
    return examples


def load_pairs_file(path: Path, task_type: str, default_system: str) -> list[dict]:
    """Generic loader for our generated pairs JSONL files."""
    examples = []
    if not path.exists():
        print(f"  WARN: {path} not found", file=sys.stderr)
        return examples
    with path.open() as f:
        for line in f:
            d = json.loads(line)
            msgs = {m["role"]: m["content"] for m in d["messages"]}
            system = msgs.get("system", default_system)
            user = msgs.get("user", "")
            assistant = msgs.get("assistant", "")

            # Load image if present
            img_path = d.get("image_path")
            pil = _load_pil(img_path) if img_path else None

            if pil:
                examples.append(_multimodal_example(
                    system=system,
                    user=user,
                    assistant=assistant,
                    images=[pil],
                    task_type=task_type,
                    source=d.get("source_file", task_type),
                ))
            else:
                examples.append(_text_example(
                    system=system,
                    user=user,
                    assistant=assistant,
                    task_type=task_type,
                    source=d.get("source_file", task_type),
                ))
    return examples


def load_existing_vision() -> list[dict]:
    """Load existing unified_vision_data (board analysis, component knowledge, etc.)."""
    examples = []
    if not EXISTING_VISION.exists():
        print(f"  WARN: {EXISTING_VISION} not found", file=sys.stderr)
        return examples

    from datasets import load_from_disk
    ds = load_from_disk(str(EXISTING_VISION))
    print(f"  Existing vision: {len(ds)} rows", file=sys.stderr)

    from collections import Counter
    task_counts = Counter(ds["task_type"])
    print(f"  Task distribution: {dict(task_counts)}", file=sys.stderr)

    # Keep non-maze tasks at full volume; downsample maze
    for row in ds:
        tt = row["task_type"]
        if tt == "maze_routing":
            continue  # Handled separately with downsampling
        examples.append({
            "images": row["images"] if row["images"] else [],
            "messages": row["messages"],
            "task_type": tt,
            "source_file": row.get("source_file", "existing"),
        })

    return examples


def load_maze_downsampled() -> list[dict]:
    """Load maze data, downsampled to MAZE_TARGET."""
    examples = []
    if not MAZE_VISION.exists():
        print(f"  WARN: {MAZE_VISION} not found", file=sys.stderr)
        return examples

    from datasets import load_from_disk
    import random
    ds = load_from_disk(str(MAZE_VISION))
    total = len(ds)
    print(f"  Maze: {total} total, downsampling to {MAZE_TARGET}", file=sys.stderr)

    rng = random.Random(42)
    indices = list(range(total))
    rng.shuffle(indices)
    selected = set(indices[:MAZE_TARGET])

    for i, row in enumerate(ds):
        if i not in selected:
            continue
        examples.append({
            "images": row["images"] if row["images"] else [],
            "messages": row["messages"],
            "task_type": "maze_routing",
            "source_file": row.get("source_file", "maze"),
        })

    return examples


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_examples: list[dict] = []

    print("Loading SchGen executable...", file=sys.stderr)
    schgen = load_schgen()
    print(f"  {len(schgen)} examples", file=sys.stderr)
    all_examples.extend(schgen)

    print("Loading corpus multimodal...", file=sys.stderr)
    corpus = load_corpus()
    print(f"  {len(corpus)} examples", file=sys.stderr)
    all_examples.extend(corpus)

    print("Loading legibility critiques...", file=sys.stderr)
    legibility = load_pairs_file(LEGIBILITY_PAIRS, "legibility_critique", "Schematic legibility analysis")
    print(f"  {len(legibility)} examples", file=sys.stderr)
    all_examples.extend(legibility)

    print("Loading placement intelligence...", file=sys.stderr)
    placement = load_pairs_file(PLACEMENT_PAIRS, "placement_intelligence", "PCB placement analysis")
    print(f"  {len(placement)} examples", file=sys.stderr)
    all_examples.extend(placement)

    print("Loading diagnostic vision...", file=sys.stderr)
    diagnostic = load_pairs_file(DIAGNOSTIC_PAIRS, "blocker_diagnosis", "PCB routing diagnosis")
    print(f"  {len(diagnostic)} examples", file=sys.stderr)
    all_examples.extend(diagnostic)

    print("Loading routing strategy...", file=sys.stderr)
    strategy = load_pairs_file(STRATEGY_PAIRS, "routing_strategy", "PCB routing strategy")
    print(f"  {len(strategy)} examples", file=sys.stderr)
    all_examples.extend(strategy)

    print("Loading existing vision (non-maze)...", file=sys.stderr)
    existing = load_existing_vision()
    print(f"  {len(existing)} examples", file=sys.stderr)
    all_examples.extend(existing)

    print("Loading maze (downsampled)...", file=sys.stderr)
    maze = load_maze_downsampled()
    print(f"  {len(maze)} examples", file=sys.stderr)
    all_examples.extend(maze)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"TOTAL: {len(all_examples)} examples", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    from collections import Counter
    task_counts = Counter(e["task_type"] for e in all_examples)
    print(f"\nTask distribution:", file=sys.stderr)
    for task, count in task_counts.most_common():
        pct = count / len(all_examples) * 100
        print(f"  {task:30s} {count:>6d} ({pct:5.1f}%)", file=sys.stderr)

    multimodal_count = sum(1 for e in all_examples if e["images"])
    print(f"\nMultimodal: {multimodal_count} ({multimodal_count/len(all_examples)*100:.1f}%)", file=sys.stderr)
    print(f"Text-only:  {len(all_examples) - multimodal_count} ({(len(all_examples)-multimodal_count)/len(all_examples)*100:.1f}%)", file=sys.stderr)

    # Build HF Dataset
    print(f"\nBuilding HF Dataset...", file=sys.stderr)
    ds = Dataset.from_list(all_examples)

    print(f"Saving to {OUT_DIR}...", file=sys.stderr)
    ds.save_to_disk(str(OUT_DIR))
    print(f"Done. {len(ds)} examples saved.", file=sys.stderr)


if __name__ == "__main__":
    main()
