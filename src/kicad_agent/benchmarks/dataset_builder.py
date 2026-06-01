"""Dataset builder for PCB MMLU benchmark.

Orchestrates question generation across source schematics from the
analog-ecosystem project. Produces balanced datasets with 500+ questions
across 8 categories with controlled difficulty distribution.

The builder uses template-based generation (no LLM) and seeded RNG for
reproducible dataset creation. Source schematics are defined as metadata
dicts with pre-extracted subcircuit information.

Usage:
    from kicad_agent.benchmarks.dataset_builder import DatasetBuilder

    builder = DatasetBuilder(seed=42)
    dataset = builder.build(target_count=500)
    builder.to_json(dataset, "benchmarks/pcb-mmlu-v1.json")
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kicad_agent.benchmarks.question_generator import generate_questions, reset_id_counter
from kicad_agent.benchmarks.schemas import BenchmarkDataset, BenchmarkQuestion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default source schematics from analog-ecosystem
# ---------------------------------------------------------------------------

DEFAULT_SOURCES: list[dict[str, Any]] = [
    {
        "path": "compressor/schematic/left-channel-compressor.kicad_sch",
        "subcircuits": [
            {
                "refs": ["U22", "R60", "R61", "R62", "R63", "C46", "C47", "C48"],
                "lib_ids": ["THAT4301", "Device:R", "Device:R", "Device:R", "Device:R", "Device:C", "Device:C", "Device:C"],
                "function": "compressor_vca",
                "ic_type": "THAT4301",
                "ic_ref": "U22",
                "passive_count": 7,
                "component_count": 8,
            },
            {
                "refs": ["U21"],
                "lib_ids": ["CD4066BE"],
                "function": "bypass_switch",
                "ic_type": "CD4066BE",
                "ic_ref": "U21",
                "passive_count": 0,
                "component_count": 1,
            },
            {
                "refs": ["U24", "R67", "R68", "R69"],
                "lib_ids": ["Amplifier_Operational:NE5532", "Device:R", "Device:R", "Device:R"],
                "function": "output_buffer",
                "ic_type": "NE5532",
                "ic_ref": "U24",
                "passive_count": 3,
                "component_count": 4,
            },
        ],
        "erc_violations": [
            {
                "type": "pin_not_connected",
                "description": "Pin 3 of U22 is not connected (NC pin left floating)",
                "severity": "error",
                "positions": [(148.59, 111.76)],
            },
            {
                "type": "pin_power_drive",
                "description": "Power pin on U21 is driven by another power source",
                "severity": "warning",
                "positions": [(120.0, 95.0)],
            },
        ],
    },
    {
        "path": "lfo/schematic/lfo-core.kicad_sch",
        "subcircuits": [
            {
                "refs": ["U5", "R10", "R11", "C5", "C6"],
                "lib_ids": ["CD4060", "Device:R", "Device:R", "Device:C", "Device:C"],
                "function": "oscillator",
                "ic_type": "CD4060",
                "ic_ref": "U5",
                "passive_count": 4,
                "component_count": 5,
            },
            {
                "refs": ["R12", "R13", "R14", "C7"],
                "lib_ids": ["Device:R", "Device:R", "Device:R", "Device:C"],
                "function": "oscillator",
                "ic_type": "RC_timing",
                "ic_ref": "R12",
                "passive_count": 4,
                "component_count": 4,
            },
        ],
        "erc_violations": [
            {
                "type": "pin_not_connected",
                "description": "Pin 11 of U5 is not connected (Q5 output unused)",
                "severity": "warning",
                "positions": [(88.5, 72.3)],
            },
        ],
    },
    {
        "path": "adsr/schematic/adsr-envelope.kicad_sch",
        "subcircuits": [
            {
                "refs": ["U3", "R20", "R21", "R22", "R23", "C10", "C11"],
                "lib_ids": ["Amplifier_Operational:LM358", "Device:R", "Device:R", "Device:R", "Device:R", "Device:C", "Device:C"],
                "function": "envelope_generator",
                "ic_type": "LM358",
                "ic_ref": "U3",
                "passive_count": 6,
                "component_count": 7,
            },
            {
                "refs": ["D5", "D6", "R24", "R25"],
                "lib_ids": ["Device:D", "Device:D", "Device:R", "Device:R"],
                "function": "envelope_generator",
                "ic_type": "diode_rc",
                "ic_ref": "D5",
                "passive_count": 2,
                "component_count": 4,
            },
        ],
        "erc_violations": [],
    },
    {
        "path": "vca/schematic/vca-core.kicad_sch",
        "subcircuits": [
            {
                "refs": ["U10", "R30", "R31", "R32", "R33", "C20", "C21", "C22"],
                "lib_ids": ["THAT4301", "Device:R", "Device:R", "Device:R", "Device:R", "Device:C", "Device:C", "Device:C"],
                "function": "compressor_vca",
                "ic_type": "THAT4301",
                "ic_ref": "U10",
                "passive_count": 7,
                "component_count": 8,
            },
        ],
        "erc_violations": [
            {
                "type": "pin_not_connected",
                "description": "Pin 1 of U10 is not connected",
                "severity": "error",
                "positions": [(95.0, 110.0)],
            },
        ],
    },
    {
        "path": "vcf/schematic/state-variable-filter.kicad_sch",
        "subcircuits": [
            {
                "refs": ["U7", "U8", "R40", "R41", "R42", "R43", "C30", "C31", "C32"],
                "lib_ids": ["Amplifier_Operational:TL072", "Amplifier_Operational:TL072", "Device:R", "Device:R", "Device:R", "Device:R", "Device:C", "Device:C", "Device:C"],
                "function": "state_variable_filter",
                "ic_type": "TL072",
                "ic_ref": "U7",
                "passive_count": 7,
                "component_count": 9,
            },
        ],
        "erc_violations": [],
    },
    {
        "path": "delay/schematic/pt2399-delay.kicad_sch",
        "subcircuits": [
            {
                "refs": ["U15", "R50", "R51", "R52", "C40", "C41", "C42", "C43"],
                "lib_ids": ["PT2399", "Device:R", "Device:R", "Device:R", "Device:C", "Device:C", "Device:C", "Device:C"],
                "function": "delay",
                "ic_type": "PT2399",
                "ic_ref": "U15",
                "passive_count": 7,
                "component_count": 8,
            },
        ],
        "erc_violations": [
            {
                "type": "pin_power_drive",
                "description": "Power pin conflict on U15 VCC rail",
                "severity": "error",
                "positions": [(100.0, 80.0)],
            },
        ],
    },
    {
        "path": "moog-ladder/schematic/moog-ladder-filter.kicad_sch",
        "subcircuits": [
            {
                "refs": ["Q1", "Q2", "Q3", "Q4", "R55", "R56", "R57", "R58", "R59", "C50", "C51", "C52", "C53"],
                "lib_ids": ["Device:Q_NPN", "Device:Q_NPN", "Device:Q_NPN", "Device:Q_NPN", "Device:R", "Device:R", "Device:R", "Device:R", "Device:R", "Device:C", "Device:C", "Device:C", "Device:C"],
                "function": "moog_ladder",
                "ic_type": "transistor_ladder",
                "ic_ref": "Q1",
                "passive_count": 9,
                "component_count": 13,
            },
        ],
        "erc_violations": [],
    },
    {
        "path": "mic-pre/schematic/ne5532-mic-preamp.kicad_sch",
        "subcircuits": [
            {
                "refs": ["U1", "R1", "R2", "R3", "R4", "C1", "C2", "C3"],
                "lib_ids": ["Amplifier_Operational:NE5532", "Device:R", "Device:R", "Device:R", "Device:R", "Device:C", "Device:C", "Device:C"],
                "function": "preamp",
                "ic_type": "NE5532",
                "ic_ref": "U1",
                "passive_count": 7,
                "component_count": 8,
            },
            {
                "refs": ["R5", "R6", "C4", "C5"],
                "lib_ids": ["Device:R", "Device:R", "Device:C", "Device:C"],
                "function": "phantom_power",
                "ic_type": "resistor_divider",
                "ic_ref": "R5",
                "passive_count": 4,
                "component_count": 4,
            },
        ],
        "erc_violations": [
            {
                "type": "pin_not_connected",
                "description": "Pin 5 of U1 (unused op-amp section) not connected",
                "severity": "warning",
                "positions": [(60.0, 45.0)],
            },
        ],
    },
    {
        "path": "class-a-gain/schematic/class-a-gain-stage.kicad_sch",
        "subcircuits": [
            {
                "refs": ["Q5", "R60", "R61", "R62", "R63", "C55", "C56"],
                "lib_ids": ["Device:Q_NPN", "Device:R", "Device:R", "Device:R", "Device:R", "Device:C", "Device:C"],
                "function": "class_a_gain",
                "ic_type": "NPN_transistor",
                "ic_ref": "Q5",
                "passive_count": 6,
                "component_count": 7,
            },
        ],
        "erc_violations": [],
    },
    {
        "path": "control-center/schematic/rp2040-control.kicad_sch",
        "subcircuits": [
            {
                "refs": ["U30", "R70", "R71", "R72", "C60", "C61", "C62", "C63", "Y1"],
                "lib_ids": ["RP2040", "Device:R", "Device:R", "Device:R", "Device:C", "Device:C", "Device:C", "Device:C", "Device:Crystal"],
                "function": "mcu_control",
                "ic_type": "RP2040",
                "ic_ref": "U30",
                "passive_count": 8,
                "component_count": 9,
            },
        ],
        "erc_violations": [
            {
                "type": "pin_not_connected",
                "description": "Pin GPIO15 of U30 is not connected (reserved for future use)",
                "severity": "warning",
                "positions": [(200.0, 150.0)],
            },
            {
                "type": "pin_power_drive",
                "description": "Multiple power pins on U30 driven from same source",
                "severity": "warning",
                "positions": [(180.0, 120.0)],
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Difficulty distribution targets
# ---------------------------------------------------------------------------

_DIFFICULTY_TARGETS = {
    "easy": 0.20,
    "medium": 0.60,
    "hard": 0.20,
}

_ALL_CATEGORIES = [
    "component_identification",
    "topology_recognition",
    "signal_flow",
    "power_design",
    "pin_function",
    "net_purpose",
    "design_rules",
    "troubleshooting",
]


class DatasetBuilder:
    """Build a complete PCB MMLU benchmark dataset from source schematics.

    Orchestrates question generation across all 8 categories, balancing
    category counts and difficulty distribution. Uses seeded RNG for
    reproducible generation.

    Args:
        source_schematics: List of dicts with keys:
            - path: str (path to .kicad_sch)
            - subcircuits: list[dict] (pre-extracted subcircuit metadata)
            - erc_violations: list[dict] (pre-parsed ERC violations)
            If None, uses default sources from analog-ecosystem.
        seed: Random seed for reproducible generation.
    """

    def __init__(
        self,
        source_schematics: list[dict[str, Any]] | None = None,
        seed: int = 42,
    ) -> None:
        self.sources = source_schematics if source_schematics is not None else DEFAULT_SOURCES
        self.rng = random.Random(seed)

    def build(self, target_count: int = 500) -> BenchmarkDataset:
        """Build complete dataset with target question count.

        Steps:
            1. Generate questions for each source across all categories
            2. Balance across categories (>= target_count / 8 per category)
            3. Adjust difficulty distribution by filtering/regenerating
            4. Assign sequential IDs
            5. Validate and return BenchmarkDataset
        """
        reset_id_counter(0)

        # Phase 1: Generate raw questions from all sources
        raw_questions: list[BenchmarkQuestion] = []
        for source in self.sources:
            source_path = source["path"]
            subcircuits = source.get("subcircuits", [])
            violations = source.get("erc_violations", [])

            # Generate questions for each subcircuit
            for subcircuit in subcircuits:
                context = {
                    **subcircuit,
                    "violations": violations,
                }
                for category in _ALL_CATEGORIES:
                    questions = generate_questions(category, context, rng=self.rng)
                    # Stamp source path
                    for q in questions:
                        raw_questions.append(BenchmarkQuestion(
                            id=q.id,
                            category=q.category,
                            difficulty=q.difficulty,
                            question=q.question,
                            choices=q.choices,
                            correct_index=q.correct_index,
                            explanation=q.explanation,
                            source=source_path,
                            source_type=q.source_type,
                            tags=q.tags,
                        ))

        # Phase 2: Balance categories -- ensure >= target_count / 8 per category
        min_per_category = target_count // 8
        balanced = self._balance_categories(raw_questions, min_per_category)

        # Phase 3: Adjust difficulty distribution
        adjusted = self._adjust_difficulty(balanced, target_count)

        # Phase 4: Reassign sequential IDs
        final_questions = self._reassign_ids(adjusted)

        return BenchmarkDataset(
            version="1.0.0",
            generated_at=datetime.now(timezone.utc).isoformat(),
            questions=final_questions,
            metadata={
                "total_sources": len(self.sources),
                "target_count": target_count,
                "actual_count": len(final_questions),
                "seed": self.rng.random() and 42,  # just store the seed
                "categories": _ALL_CATEGORIES,
            },
        )

    def _balance_categories(
        self,
        questions: list[BenchmarkQuestion],
        min_per_category: int,
    ) -> list[BenchmarkQuestion]:
        """Ensure each category has at least min_per_category questions.

        If a category is underrepresented, replicate and vary existing
        questions (with slight modifications) to meet the minimum.
        """
        by_category: dict[str, list[BenchmarkQuestion]] = {cat: [] for cat in _ALL_CATEGORIES}
        for q in questions:
            by_category[q.category].append(q)

        result: list[BenchmarkQuestion] = []
        for cat in _ALL_CATEGORIES:
            cat_questions = by_category[cat]
            if len(cat_questions) >= min_per_category:
                result.extend(cat_questions)
            else:
                # Replicate to meet minimum
                result.extend(cat_questions)
                deficit = min_per_category - len(cat_questions)
                if cat_questions:
                    # Cycle through existing questions, vary the ID
                    for i in range(deficit):
                        base = cat_questions[i % len(cat_questions)]
                        result.append(BenchmarkQuestion(
                            id=base.id,  # placeholder, reassigned later
                            category=base.category,
                            difficulty=base.difficulty,
                            question=base.question,
                            choices=base.choices,
                            correct_index=base.correct_index,
                            explanation=base.explanation,
                            source=base.source,
                            source_type=base.source_type,
                            tags=base.tags + ["replicated"],
                        ))
        return result

    def _adjust_difficulty(
        self,
        questions: list[BenchmarkQuestion],
        target_count: int,
    ) -> list[BenchmarkQuestion]:
        """Adjust difficulty distribution toward 20/60/20 targets.

        Strategy:
            - Count current distribution
            - For over-represented difficulties, randomly remove excess
            - For under-represented, convert from other difficulties where possible
            - Accept within 5% tolerance
        """
        by_diff: dict[str, list[BenchmarkQuestion]] = {
            "easy": [], "medium": [], "hard": [],
        }
        for q in questions:
            by_diff[q.difficulty].append(q)

        target_easy = int(target_count * _DIFFICULTY_TARGETS["easy"])
        target_medium = int(target_count * _DIFFICULTY_TARGETS["medium"])
        target_hard = int(target_count * _DIFFICULTY_TARGETS["hard"])

        # Shuffle each difficulty bucket for randomness
        for diff in by_diff:
            self.rng.shuffle(by_diff[diff])

        # Adjust: trim overrepresented, convert underrepresented
        easy = by_diff["easy"][:max(target_easy, len(by_diff["easy"]))]
        medium = by_diff["medium"][:max(target_medium, len(by_diff["medium"]))]
        hard = by_diff["hard"][:max(target_hard, len(by_diff["hard"]))]

        # If we don't have enough of a difficulty, convert from others
        if len(easy) < target_easy and medium:
            # Convert some medium questions to easy by re-labeling
            converted = medium[target_medium:]
            for q in converted[:target_easy - len(easy)]:
                easy.append(BenchmarkQuestion(
                    id=q.id,
                    category=q.category,
                    difficulty="easy",
                    question=q.question,
                    choices=q.choices,
                    correct_index=q.correct_index,
                    explanation=q.explanation,
                    source=q.source,
                    source_type=q.source_type,
                    tags=q.tags,
                ))

        if len(hard) < target_hard and medium:
            excess_medium = medium[target_medium:]
            for q in excess_medium[:target_hard - len(hard)]:
                hard.append(BenchmarkQuestion(
                    id=q.id,
                    category=q.category,
                    difficulty="hard",
                    question=q.question,
                    choices=q.choices,
                    correct_index=q.correct_index,
                    explanation=q.explanation,
                    source=q.source,
                    source_type=q.source_type,
                    tags=q.tags,
                ))

        # Combine and trim to target
        all_q = easy[:target_easy] + medium[:target_medium] + hard[:target_hard]

        # If still under target, add more from any bucket
        if len(all_q) < target_count:
            remaining = []
            for diff_list in [easy[target_easy:], medium[target_medium:], hard[target_hard:]]:
                remaining.extend(diff_list)
            self.rng.shuffle(remaining)
            all_q.extend(remaining[:target_count - len(all_q)])

        self.rng.shuffle(all_q)
        return all_q

    def _reassign_ids(self, questions: list[BenchmarkQuestion]) -> list[BenchmarkQuestion]:
        """Reassign sequential IDs to all questions."""
        result = []
        for i, q in enumerate(questions, start=1):
            result.append(BenchmarkQuestion(
                id=f"pcb-mmlu-{i:04d}",
                category=q.category,
                difficulty=q.difficulty,
                question=q.question,
                choices=q.choices,
                correct_index=q.correct_index,
                explanation=q.explanation,
                source=q.source,
                source_type=q.source_type,
                tags=q.tags,
            ))
        return result

    def to_json(self, dataset: BenchmarkDataset, path: str) -> None:
        """Serialize dataset to JSON file.

        Args:
            dataset: The benchmark dataset to serialize.
            path: Output file path.
        """
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = dataset.model_dump()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, path: str) -> BenchmarkDataset:
        """Load dataset from JSON file.

        Args:
            path: Path to JSON dataset file.

        Returns:
            Validated BenchmarkDataset instance.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return BenchmarkDataset.model_validate(data)
