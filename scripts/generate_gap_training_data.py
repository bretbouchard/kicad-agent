#!/usr/bin/env python3
"""Generate gap-filling training data for Gemma 4 12B fine-tuning.

Produces 5000+ training examples in Gemma ChatML format with PCB renders.
Uses TaskGenerator with multiple seeds for synthetic tasks, plus real PCB gap analysis.

Output: train.jsonl + val.jsonl in Gemma ChatML format.

Usage:
    python3 scripts/generate_gap_training_data.py --output-dir training_output/gemma_sft_data
    python3 scripts/generate_gap_training_data.py --seeds 50 --output-dir training_output/gemma_sft_data
    python3 scripts/generate_gap_training_data.py --pcbs tests/fixtures/Arduino_Mega --output-dir training_output/gemma_sft_data
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# Gemma ChatML format
# ---------------------------------------------------------------------------

_GEMMA_SYSTEM_PROMPT = (
    "You are a PCB design expert with vision capabilities. "
    "Analyze the provided PCB render and answer spatial reasoning "
    "questions. For numeric answers, respond with just the number. "
    "For yes/no questions, respond with 'yes' or 'no'. "
    "For fix selection, respond with 'Fix N: <description>'. "
    "For path questions, describe waypoints as (x, y) coordinates."
)


def format_gemma_chatml(
    system: str,
    user_content: str,
    assistant_content: str,
) -> tuple[list[dict[str, str]], str]:
    """Format a training example in Gemma ChatML.

    Returns:
        (messages_list, text_string) where messages_list is the list of message dicts
        and text_string has the raw ChatML text.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": assistant_content},
    ]
    text_parts = []
    for msg in messages:
        role = msg["role"]
        if role == "assistant":
            role = "model"
        text_parts.append(f"<start_of_turn>{role}\n{msg['content']}<end_of_turn>")
    text = "\n".join(text_parts)
    return messages, text


def parse_gemma_chatml(text: str) -> list[dict[str, str]] | None:
    """Parse <start_of_turn>role\\ncontent<end_of_turn> into message dicts.

    Returns None if fewer than 2 messages found.
    """
    messages: list[dict[str, str]] = []
    parts = text.split("<start_of_turn>")
    for part in parts:
        if not part.strip():
            continue
        role_end = part.find("\n")
        if role_end < 0:
            continue
        role = part[:role_end].strip()
        content = part[role_end + 1 :]
        # Strip <end_of_turn> and any trailing whitespace/newlines
        if "<end_of_turn>" in content:
            content = content[: content.index("<end_of_turn>")]
        content = content.strip()
        if role in ("system", "user", "model", "assistant") and content:
            # Normalize "model" back to "assistant" for internal use
            if role == "model":
                role = "assistant"
            messages.append({"role": role, "content": content})
    return messages if len(messages) >= 2 else None


# ---------------------------------------------------------------------------
# Data generation: benchmark tasks
# ---------------------------------------------------------------------------

_VISION_CATEGORIES = frozenset({
    "routing_feasibility",
    "clearance_diagnosis",
    "net_completion",
    "drc_fix_selection",
    "unrouted_cause",
})


def generate_from_benchmark_tasks(
    output_dir: Path,
    n_seeds: int = 50,
    vision_only: bool = True,
) -> int:
    """Generate training examples from TaskGenerator with multiple seeds.

    Args:
        output_dir: Directory for train.jsonl and val.jsonl.
        n_seeds: Number of different seeds to generate tasks from.
        vision_only: If True, only include vision-category tasks.

    Returns:
        Total number of examples generated.
    """
    from volta.analysis.spatial_benchmark import TaskGenerator, SpatialReasoningTask

    examples: list[dict[str, Any]] = []

    for seed in range(n_seeds):
        gen = TaskGenerator(seed=seed)
        tasks = gen.generate_all()

        for task in tasks:
            if task.input_type == "text" and vision_only:
                continue
            if vision_only and task.task_type.value not in _VISION_CATEGORIES:
                continue

            messages, text = format_gemma_chatml(
                _GEMMA_SYSTEM_PROMPT,
                task.question,
                task.ground_truth,
            )
            examples.append({
                "messages": messages,
                "text": text,
                "task_type": task.task_type.value,
                "task_id": task.task_id,
                "difficulty": task.difficulty,
                "seed": seed,
            })

    return _write_split(examples, output_dir)


# ---------------------------------------------------------------------------
# Data generation: real PCB gap analysis
# ---------------------------------------------------------------------------


def generate_from_gap_analysis(
    pcb_paths: list[Path],
    output_dir: Path,
    render_dir: Path | None = None,
) -> int:
    """Generate training examples from real PCB gap analysis.

    Analyzes each PCB with GapAnalyzer and converts gaps into Q&A pairs.

    Args:
        pcb_paths: List of PCB files to analyze.
        output_dir: Directory for train.jsonl and val.jsonl.
        render_dir: Directory for PCB renders (optional).

    Returns:
        Total number of examples generated.
    """
    from volta.analysis.gap_analyzer import GapAnalyzer

    if render_dir:
        render_dir.mkdir(parents=True, exist_ok=True)

    analyzer = GapAnalyzer()
    examples: list[dict[str, Any]] = []

    for pcb_path in pcb_paths:
        try:
            report = analyzer.analyze(str(pcb_path), run_drc=True)
        except Exception as exc:
            print(f"  Warning: failed to analyze {pcb_path}: {exc}", file=sys.stderr)
            continue

        # Unrouted nets
        for net in report.unrouted_nets:
            question = (
                f"Net '{net.net_name}' has {net.pad_count} pads but zero routed "
                f"segments. Pin positions: {net.pin_positions}. "
                f"Nearest obstacle distance: {net.nearest_obstacle_distance:.2f}mm. "
                f"Complete the route by suggesting waypoints."
            )
            answer = (
                f"Suggested waypoints for net '{net.net_name}': "
                f"Start at {net.pin_positions[0]}, "
                f"route through available channels, "
                f"end at {net.pin_positions[-1]}."
            )
            messages, text = format_gemma_chatml(_GEMMA_SYSTEM_PROMPT, question, answer)
            example = {
                "messages": messages,
                "text": text,
                "task_type": "net_completion",
                "source": str(pcb_path),
            }
            if render_dir:
                example["render_path"] = str(render_dir / f"{net.net_name}_render.png")
            examples.append(example)

        # DRC violations
        for violation in report.drc_violations:
            fix_text = "; ".join(
                f"{fs.action}: {fs.rationale}" for fs in violation.fix_suggestions
            ) if violation.fix_suggestions else "No automated fix available for this violation type."
            question = (
                f"DRC violation: {violation.violation_type}. "
                f"Description: {violation.description}. "
                f"What fix should be applied?"
            )
            answer = f"Fix: {fix_text}"
            messages, text = format_gemma_chatml(_GEMMA_SYSTEM_PROMPT, question, answer)
            example = {
                "messages": messages,
                "text": text,
                "task_type": "drc_fix_selection",
                "source": str(pcb_path),
            }
            if render_dir:
                example["render_path"] = str(render_dir / f"drc_{violation.violation_type}.png")
            examples.append(example)

        # Naming issues
        for issue in report.net_naming_issues:
            question = (
                f"Net named '{issue.current_name}' does not follow "
                f"KiCad naming conventions. Suggested rename: '{issue.suggested_name}'. "
                f"Accept or reject this suggestion?"
            )
            answer = f"Accept: rename '{issue.current_name}' to '{issue.suggested_name}'. Reason: {issue.reason}"
            messages, text = format_gemma_chatml(_GEMMA_SYSTEM_PROMPT, question, answer)
            examples.append({
                "messages": messages,
                "text": text,
                "task_type": "net_naming",
                "source": str(pcb_path),
            })

    return _write_split(examples, output_dir)


# ---------------------------------------------------------------------------
# Train/val split
# ---------------------------------------------------------------------------


def _write_split(
    examples: list[dict[str, Any]],
    output_dir: Path,
    val_ratio: float = 0.1,
    seed: int = 42,
) -> int:
    """Write train.jsonl and val.jsonl splits.

    Args:
        examples: All training examples.
        output_dir: Output directory.
        val_ratio: Fraction for validation (default 10%).
        seed: Random seed for reproducibility.

    Returns:
        Total examples written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    rng.shuffle(examples)

    val_count = max(1, int(len(examples) * val_ratio))
    val_examples = examples[:val_count]
    train_examples = examples[val_count:]

    train_path = output_dir / "train.jsonl"
    val_path = output_dir / "val.jsonl"

    with open(train_path, "w", encoding="utf-8") as f:
        for ex in train_examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    with open(val_path, "w", encoding="utf-8") as f:
        for ex in val_examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"  Train: {len(train_examples)} examples -> {train_path}")
    print(f"  Val:   {len(val_examples)} examples -> {val_path}")
    return len(examples)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate gap-filling training data for Gemma 4 12B fine-tuning.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("training_output/gemma_sft_data"))
    parser.add_argument("--seeds", type=int, default=50, help="Number of TaskGenerator seeds")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation split ratio")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--pcbs", nargs="*", type=Path, help="PCB files for gap analysis")
    args = parser.parse_args()

    print("Generating Gemma 12B training data")
    print(f"  Seeds: {args.seeds}")
    print(f"  Output: {args.output_dir}")

    total = generate_from_benchmark_tasks(
        args.output_dir,
        n_seeds=args.seeds,
        vision_only=True,
    )

    if args.pcbs:
        total += generate_from_gap_analysis(
            args.pcbs,
            args.output_dir,
        )

    print(f"\nTotal examples: {total}")
    if total >= 5000:
        print("PASS: Exceeds 5000 example minimum.")
    else:
        print(f"WARN: {total} < 5000. Increase --seeds or add more PCBs.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
