"""Mass synthetic circuit generation with parallel execution.

Generates 10,000+ unique circuits across all templates using
ProcessPoolExecutor for parallel generation. Includes deduplication,
JSONL packaging, and train/val/test splitting.

Usage::

    from volta.training.mass_generate import MassGenerationConfig, run_mass_generation

    config = MassGenerationConfig(target_count=10000, n_workers=4)
    result = run_mass_generation(config)
    print(f"Generated {result.total_generated} circuits")

CLI::

    python -m volta.training.mass_generate --target 100 --workers 4 --dry-run
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from volta.training.circuit_templates import CircuitTemplate, get_all_templates
from volta.training.synthetic_generator import (
    GenerationAttempt,
    SyntheticGenerator,
    attempt_to_dict,
)

logger = logging.getLogger(__name__)


class MassGenerationConfig(BaseModel):
    """Configuration for mass generation run.

    Attributes:
        target_count: Total number of unique circuits to generate.
        n_workers: Number of parallel workers (ProcessPoolExecutor).
        seed: Base seed for deterministic generation.
        output_dir: Directory for JSONL output files.
        run_validation: Whether to run ERC validation (significantly slower).
        samples_per_template: Override for per-template count.
             If None, divides target_count equally across templates.
    """

    target_count: int = Field(default=10000, ge=1, le=1000000)
    n_workers: int = Field(default=4, ge=1, le=32)
    seed: int = Field(default=42)
    output_dir: str = Field(default="training_data/synthetic-circuits")
    run_validation: bool = Field(default=False)
    samples_per_template: int | None = Field(default=None)

    @field_validator("n_workers")
    @classmethod
    def _workers_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("n_workers must be >= 1")
        return v


@dataclass(frozen=True)
class MassGenerationResult:
    """Results of a mass generation run.

    Attributes:
        total_generated: Number of unique valid circuits generated.
        total_failed: Number of failed generation attempts.
        total_duplicates: Number of duplicates removed.
        erc_pass_count: Number of circuits that passed ERC.
        erc_fail_count: Number that failed ERC.
        train_count: Number in train split.
        val_count: Number in val split.
        test_count: Number in test split.
        output_dir: Directory containing JSONL files.
    """

    total_generated: int
    total_failed: int = 0
    total_duplicates: int = 0
    erc_pass_count: int = 0
    erc_fail_count: int = 0
    train_count: int = 0
    val_count: int = 0
    test_count: int = 0
    output_dir: str = ""


@dataclass(frozen=True)
class QualityMetrics:
    """Quality metrics for a synthetic circuit dataset.

    Attributes:
        total_circuits: Total number of unique circuits.
        template_coverage: Fraction of templates with >= 1 circuit (0.0-1.0).
        per_template_counts: Dict of template_name -> count.
        component_diversity: Number of unique library_id values across dataset.
        parameter_coverage: Average fraction of parameter range explored per template.
        erc_pass_rate: Fraction of validated circuits that passed ERC.
    """

    total_circuits: int
    template_coverage: float
    per_template_counts: dict[str, int]
    component_diversity: int
    parameter_coverage: float
    erc_pass_rate: float


def _generate_template_chunk(args: tuple) -> list[dict]:
    """Generate circuits for a single template in a subprocess.

    Returns list of dicts (not GenerationAttempt) to avoid pickling.
    """
    template_name, n_samples, seed_start, template_defs = args

    # Reconstruct template from serialized form (avoid pickling CircuitTemplate)
    template = None
    for t in template_defs:
        if t["name"] == template_name:
            template = CircuitTemplate.model_validate(t)
            break
    if template is None:
        return []

    gen = SyntheticGenerator()
    results = gen.generate_batch(
        template=template,
        n_samples=n_samples,
        seed_start=seed_start,
        validate=False,  # No ERC in subprocess (would need kicad-cli)
    )

    return [attempt_to_dict(r) for r in results if r.intent is not None]


def run_mass_generation(config: MassGenerationConfig | None = None) -> MassGenerationResult:
    """Execute mass generation pipeline.

    Steps:
    1. Load all templates
    2. Distribute target_count across templates
    3. Generate in parallel using ProcessPoolExecutor
    4. Deduplicate by circuit hash
    5. Split into train/val/test (80/10/10)
    6. Write JSONL files

    Args:
        config: Generation configuration. Uses defaults if None.

    Returns:
        MassGenerationResult with generation statistics.
    """
    import random
    from concurrent.futures import ProcessPoolExecutor

    if config is None:
        config = MassGenerationConfig()

    templates = get_all_templates()
    n_templates = len(templates)

    # Distribute samples across templates
    if config.samples_per_template is not None:
        per_template = config.samples_per_template
    else:
        per_template = math.ceil(config.target_count / n_templates)

    # Serialize templates for subprocess communication
    template_defs = [t.model_dump() for t in templates]

    # Build work items
    work_items = []
    for i, t in enumerate(templates):
        seed_offset = config.seed + i * per_template
        work_items.append((t.name, per_template, seed_offset, template_defs))

    # Parallel generation
    all_dicts: list[dict] = []
    with ProcessPoolExecutor(max_workers=config.n_workers) as pool:
        for chunk_results in pool.map(_generate_template_chunk, work_items):
            all_dicts.extend(chunk_results)

    # Deduplication by circuit hash
    seen_hashes: set[str] = set()
    unique_dicts: list[dict] = []
    duplicates = 0

    for d in all_dicts:
        h = d.get("circuit_hash", "")
        if h and h not in seen_hashes:
            seen_hashes.add(h)
            unique_dicts.append(d)
        else:
            duplicates += 1

    # Deterministic train/val/test split
    rng = random.Random(config.seed)
    rng.shuffle(unique_dicts)

    n_total = len(unique_dicts)
    n_train = int(n_total * 0.8)
    n_val = int(n_total * 0.1)

    train = unique_dicts[:n_train]
    val = unique_dicts[n_train : n_train + n_val]
    test = unique_dicts[n_train + n_val :]

    # Write JSONL files
    output_path = Path(config.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for split_name, split_data in [("train", train), ("val", val), ("test", test)]:
        jsonl_path = output_path / f"synthetic-{split_name}.jsonl"
        with open(jsonl_path, "w") as f:
            for d in split_data:
                f.write(json.dumps(d) + "\n")

    # Also write combined
    combined_path = output_path / "synthetic-all.jsonl"
    with open(combined_path, "w") as f:
        for d in unique_dicts:
            f.write(json.dumps(d) + "\n")

    # Count ERC results
    erc_pass = sum(1 for d in unique_dicts if d.get("erc_pass") is True)
    erc_fail = sum(1 for d in unique_dicts if d.get("erc_pass") is False)

    result = MassGenerationResult(
        total_generated=n_total,
        total_failed=len(all_dicts) - n_total + duplicates,
        total_duplicates=duplicates,
        erc_pass_count=erc_pass,
        erc_fail_count=erc_fail,
        train_count=len(train),
        val_count=len(val),
        test_count=len(test),
        output_dir=str(output_path),
    )

    logger.info(
        f"Mass generation complete: {result.total_generated} circuits, "
        f"{result.train_count} train / {result.val_count} val / "
        f"{result.test_count} test, {result.total_duplicates} duplicates removed"
    )

    return result


def compute_metrics(attempts: list[dict]) -> QualityMetrics:
    """Compute quality metrics from a list of serialized GenerationAttempt dicts.

    Args:
        attempts: List of attempt dicts (from JSONL or in-memory).

    Returns:
        QualityMetrics with computed statistics.
    """
    if not attempts:
        return QualityMetrics(
            total_circuits=0,
            template_coverage=0.0,
            per_template_counts={},
            component_diversity=0,
            parameter_coverage=0.0,
            erc_pass_rate=0.0,
        )

    # Template coverage
    template_counts: dict[str, int] = {}
    unique_libs: set[str] = set()

    for d in attempts:
        tname = d.get("template_name", "unknown")
        template_counts[tname] = template_counts.get(tname, 0) + 1

        intent = d.get("intent")
        if intent and "components" in intent:
            for comp in intent["components"]:
                unique_libs.add(comp.get("library_id", ""))

    n_templates = len(get_all_templates())
    coverage = len(template_counts) / n_templates if n_templates > 0 else 0.0

    # ERC pass rate
    validated = [d for d in attempts if d.get("erc_pass") is not None]
    erc_passes = sum(1 for d in validated if d["erc_pass"] is True)
    erc_rate = erc_passes / len(validated) if validated else 0.0

    return QualityMetrics(
        total_circuits=len(attempts),
        template_coverage=coverage,
        per_template_counts=template_counts,
        component_diversity=len(unique_libs),
        parameter_coverage=0.0,  # Computed via parameter analysis (expensive)
        erc_pass_rate=erc_rate,
    )


def main():
    """CLI entry point for mass generation."""
    import argparse

    parser = argparse.ArgumentParser(description="Mass synthetic circuit generation")
    parser.add_argument("--target", type=int, default=10000, help="Target circuit count")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers")
    parser.add_argument("--seed", type=int, default=42, help="Base seed")
    parser.add_argument(
        "--output",
        type=str,
        default="training_data/synthetic-circuits",
        help="Output directory",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print plan without generating"
    )

    args = parser.parse_args()

    config = MassGenerationConfig(
        target_count=args.target,
        n_workers=args.workers,
        seed=args.seed,
        output_dir=args.output,
    )

    if args.dry_run:
        templates = get_all_templates()
        per_template = math.ceil(args.target / len(templates))
        print(f"Templates: {len(templates)}")
        print(f"Per template: {per_template}")
        print(f"Workers: {args.workers}")
        print(f"Output: {args.output}")
        return

    result = run_mass_generation(config)
    print(f"Generated: {result.total_generated}")
    print(f"Train: {result.train_count} / Val: {result.val_count} / Test: {result.test_count}")
    print(f"Duplicates removed: {result.total_duplicates}")
    print(f"Output: {result.output_dir}")


if __name__ == "__main__":
    main()
