"""Build unified dataset v2 for Gemma 4 12B multi-skill training.

Outputs a JSONL manifest with image PATHS (not inline PIL images).
The Vast.ai trainer loads images lazily from these paths during training.
This avoids the 14GB RAM blowup of loading all images into memory at once.

Output: /Volumes/Storage/schgen/unified_v2/
  - manifest.jsonl     (all examples with image paths)
  - stats.json         (task distribution summary)

Usage:
    python3 build_unified_v2.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


SCHGEN_EXECUTABLE = Path("/Volumes/Storage/schgen/converted/schgen_skidl_sft_executable.jsonl")
CORPUS_PAIRS = Path("/Volumes/Storage/schgen/our_corpus/training_pairs.jsonl")
LEGIBILITY_PAIRS = Path("/Volumes/Storage/schgen/legibility_data/legibility_training_pairs.jsonl")
PLACEMENT_PAIRS = Path("/Volumes/Storage/schgen/placement_data_v2/placement_training_pairs.jsonl")
DIAGNOSTIC_PAIRS = Path("/Volumes/Storage/schgen/diagnostic_vision_data/diagnostic_vision_pairs.jsonl")
STRATEGY_PAIRS = Path("/Volumes/Storage/schgen/strategy_data_v2/strategy_training_pairs.jsonl")
OUT_DIR = Path("/Volumes/Storage/schgen/unified_v2")

# Maze downsampling target (the maze data is in HF arrow format, we reference it)
MAZE_VISION = Path("/Users/bretbouchard/apps/volta/training_output/maze_vision_data/train")
MAZE_TARGET = 20000


SKIDL_SYSTEM = """\
You are a circuit design assistant. Generate executable SKIDL Python code from natural language descriptions. \
Use the build_board() -> Circuit pattern with proper Net() wiring. Always end with ERC()."""


def _msg_text_only(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


def load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file."""
    examples = []
    if not path.exists():
        print(f"  WARN: {path} not found", file=sys.stderr)
        return examples
    with path.open() as f:
        for line in f:
            try:
                examples.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return examples


def normalize_example(ex: dict, default_task_type: str, default_system: str) -> dict:
    """Normalize any example to the unified format with image paths."""
    msgs = ex.get("messages", [])
    system = next((m["content"] for m in msgs if m["role"] == "system"), default_system)
    user = next((m["content"] for m in msgs if m["role"] == "user"), "")
    assistant = next((m["content"] for m in msgs if m["role"] == "assistant"), "")

    # Collect image paths
    image_paths = []
    # From "images" field (corpus pairs)
    if "images" in ex and isinstance(ex["images"], list):
        for img in ex["images"]:
            if isinstance(img, str) and Path(img).exists():
                image_paths.append(img)
    # From "image_path" field (our generated pairs)
    if "image_path" in ex and ex["image_path"] and Path(ex["image_path"]).exists():
        image_paths.append(ex["image_path"])

    return {
        "system": system,
        "user": user,
        "assistant": assistant,
        "task_type": ex.get("task_type", default_task_type),
        "source_file": ex.get("source_file", ex.get("source_id", default_task_type)),
        "image_paths": image_paths,
        "has_images": len(image_paths) > 0,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_examples: list[dict] = []

    # 1. SchGen executable (text-only NL→SKIDL)
    print("Loading SchGen executable...", file=sys.stderr)
    schgen = load_jsonl(SCHGEN_EXECUTABLE)
    for ex in schgen:
        all_examples.append(normalize_example(ex, "nl_to_skidl", SKIDL_SYSTEM))
    print(f"  {len(schgen)} examples", file=sys.stderr)

    # 2. Corpus multimodal (NL→SKIDL with images)
    print("Loading corpus multimodal...", file=sys.stderr)
    corpus = load_jsonl(CORPUS_PAIRS)
    corpus_count = 0
    for ex in corpus:
        norm = normalize_example(ex, "nl_to_skidl_with_image", SKIDL_SYSTEM)
        if norm["has_images"]:
            norm["task_type"] = "nl_to_skidl_with_image"
        all_examples.append(norm)
        corpus_count += 1
    print(f"  {corpus_count} examples", file=sys.stderr)

    # 3. Legibility critiques
    print("Loading legibility critiques...", file=sys.stderr)
    legibility = load_jsonl(LEGIBILITY_PAIRS)
    for ex in legibility:
        all_examples.append(normalize_example(ex, "legibility_critique", "Schematic legibility analysis"))
    print(f"  {len(legibility)} examples", file=sys.stderr)

    # 4. Placement intelligence
    print("Loading placement intelligence...", file=sys.stderr)
    placement = load_jsonl(PLACEMENT_PAIRS)
    for ex in placement:
        all_examples.append(normalize_example(ex, "placement_intelligence", "PCB placement analysis"))
    print(f"  {len(placement)} examples", file=sys.stderr)

    # 5. Diagnostic vision
    print("Loading diagnostic vision...", file=sys.stderr)
    diagnostic = load_jsonl(DIAGNOSTIC_PAIRS)
    for ex in diagnostic:
        all_examples.append(normalize_example(ex, "blocker_diagnosis", "PCB routing diagnosis"))
    print(f"  {len(diagnostic)} examples", file=sys.stderr)

    # 6. Routing strategy
    print("Loading routing strategy...", file=sys.stderr)
    strategy = load_jsonl(STRATEGY_PAIRS)
    for ex in strategy:
        all_examples.append(normalize_example(ex, "routing_strategy", "PCB routing strategy"))
    print(f"  {len(strategy)} examples", file=sys.stderr)

    # 7. Maze routing (downsampled) — reference the arrow dataset
    print("Loading maze routing (downsampled reference)...", file=sys.stderr)
    if MAZE_VISION.exists():
        from datasets import load_from_disk
        import random
        ds = load_from_disk(str(MAZE_VISION))
        total = len(ds)
        rng = random.Random(42)
        indices = list(range(total))
        rng.shuffle(indices)
        selected = set(indices[:MAZE_TARGET])

        maze_count = 0
        for i in range(total):
            if i not in selected:
                continue
            row = ds[i]
            all_examples.append({
                "system": "Analyze the maze routing board and provide spatial reasoning.",
                "user": "",  # Will be filled from the row's messages
                "assistant": "",
                "task_type": "maze_routing",
                "source_file": f"maze/{i}",
                "image_paths": [],  # Maze images are in the arrow dataset, not paths
                "has_images": True,  # Mark as having images (loaded from arrow)
                "maze_dataset_index": i,  # Reference for lazy loading
            })
            maze_count += 1
        print(f"  {maze_count} examples (downsampled from {total})", file=sys.stderr)
    else:
        print(f"  WARN: Maze data not found at {MAZE_VISION}", file=sys.stderr)

    # Summary
    total = len(all_examples)
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"TOTAL: {total} examples", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    task_counts = Counter(e["task_type"] for e in all_examples)
    print(f"\nTask distribution:", file=sys.stderr)
    for task, count in task_counts.most_common():
        pct = count / total * 100
        print(f"  {task:30s} {count:>6d} ({pct:5.1f}%)", file=sys.stderr)

    multimodal_count = sum(1 for e in all_examples if e["has_images"])
    print(f"\nMultimodal: {multimodal_count} ({multimodal_count/total*100:.1f}%)", file=sys.stderr)
    print(f"Text-only:  {total - multimodal_count} ({(total-multimodal_count)/total*100:.1f}%)", file=sys.stderr)

    # Write manifest JSONL
    manifest_path = OUT_DIR / "manifest.jsonl"
    with manifest_path.open("w") as f:
        for ex in all_examples:
            f.write(json.dumps(ex) + "\n")

    # Write stats
    stats = {
        "total": total,
        "task_distribution": dict(task_counts.most_common()),
        "multimodal": multimodal_count,
        "text_only": total - multimodal_count,
        "sources": {
            "schgen_executable": len(schgen),
            "corpus_multimodal": corpus_count,
            "legibility": len(legibility),
            "placement": len(placement),
            "diagnostic": len(diagnostic),
            "strategy": len(strategy),
            "maze_downsampled": MAZE_TARGET,
        },
    }
    stats_path = OUT_DIR / "stats.json"
    stats_path.write_text(json.dumps(stats, indent=2))

    print(f"\nManifest: {manifest_path}", file=sys.stderr)
    print(f"Stats:    {stats_path}", file=sys.stderr)
    print(f"Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
