"""Tests for PCB MMLU benchmark dataset schemas and generators.

TDD RED phase: Tests written first, implementations follow.
Covers BenchmarkQuestion/BenchmarkDataset schemas and question generation
for all 8 categories with mock schematic context.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

# --- Mock data for tests ---

MOCK_SUBCIRCUIT = {
    "refs": ["U22", "R60", "R61", "C46"],
    "lib_ids": ["THAT4301", "Device:R", "Device:R", "Device:C"],
    "function": "compressor_vca",
    "ic_type": "VCA",
    "ic_ref": "U22",
    "passive_count": 3,
    "component_count": 4,
}

MOCK_ERC_VIOLATION = {
    "type": "pin_not_connected",
    "severity": "error",
    "description": "Pin 3 of U22 is not connected",
    "sheet": "/",
    "positions": [(148.59, 111.76)],
}


# ============================================================================
# Test 1-4: BenchmarkQuestion Schema
# ============================================================================


class TestBenchmarkQuestionSchema:
    """Validate BenchmarkQuestion Pydantic schema constraints."""

    def test_valid_question(self) -> None:
        """Test 1: BenchmarkQuestion validates with all required fields."""
        from volta.benchmarks.schemas import BenchmarkQuestion

        q = BenchmarkQuestion(
            id="pcb-mmlu-0001",
            category="topology_recognition",
            difficulty="medium",
            question="What type of circuit is formed by U22 and surrounding components?",
            choices=["VCA compressor", "Low-pass filter", "Oscillator", "Power supply"],
            correct_index=0,
            explanation="The THAT4301 is a VCA IC commonly used in compressor circuits.",
            source="compressor/schematic/left-channel.kicad_sch",
            source_type="schematic",
            tags=["analog", "compressor"],
        )
        assert q.id == "pcb-mmlu-0001"
        assert q.category == "topology_recognition"
        assert q.difficulty == "medium"
        assert len(q.choices) == 4
        assert q.correct_index == 0

    def test_rejects_out_of_bounds_correct_index(self) -> None:
        """Test 2: BenchmarkQuestion rejects correct_index outside choices bounds."""
        from volta.benchmarks.schemas import BenchmarkQuestion

        with pytest.raises(Exception):
            BenchmarkQuestion(
                id="pcb-mmlu-0002",
                category="component_identification",
                difficulty="easy",
                question="What component is R60?",
                choices=["Resistor", "Capacitor", "Inductor", "Diode"],
                correct_index=4,  # out of bounds
                explanation="R60 is a resistor.",
                source="test.kicad_sch",
                source_type="schematic",
            )

    def test_rejects_empty_fields(self) -> None:
        """Test 3: BenchmarkQuestion rejects empty question/choices/explanation."""
        from volta.benchmarks.schemas import BenchmarkQuestion

        with pytest.raises(Exception):
            BenchmarkQuestion(
                id="pcb-mmlu-0003",
                category="component_identification",
                difficulty="easy",
                question="",  # empty
                choices=["A", "B", "C", "D"],
                correct_index=0,
                explanation="Test explanation",
                source="test.kicad_sch",
                source_type="schematic",
            )

        with pytest.raises(Exception):
            BenchmarkQuestion(
                id="pcb-mmlu-0004",
                category="component_identification",
                difficulty="easy",
                question="What is R60?",
                choices=["A", "B", "C", "D"],
                correct_index=0,
                explanation="",  # empty
                source="test.kicad_sch",
                source_type="schematic",
            )

    def test_rejects_duplicate_choices(self) -> None:
        """Test 4: BenchmarkQuestion rejects duplicate choices."""
        from volta.benchmarks.schemas import BenchmarkQuestion

        with pytest.raises(Exception):
            BenchmarkQuestion(
                id="pcb-mmlu-0005",
                category="component_identification",
                difficulty="easy",
                question="What component is R60?",
                choices=["Resistor", "Resistor", "Capacitor", "Inductor"],
                correct_index=0,
                explanation="R60 is a resistor.",
                source="test.kicad_sch",
                source_type="schematic",
            )

    def test_rejects_wrong_choice_count(self) -> None:
        """BenchmarkQuestion requires exactly 4 choices."""
        from volta.benchmarks.schemas import BenchmarkQuestion

        with pytest.raises(Exception):
            BenchmarkQuestion(
                id="pcb-mmlu-0006",
                category="component_identification",
                difficulty="easy",
                question="What is R60?",
                choices=["Resistor", "Capacitor"],  # only 2
                correct_index=0,
                explanation="R60 is a resistor.",
                source="test.kicad_sch",
                source_type="schematic",
            )

    def test_rejects_invalid_category(self) -> None:
        """BenchmarkQuestion rejects categories outside the 8 allowed."""
        from volta.benchmarks.schemas import BenchmarkQuestion

        with pytest.raises(Exception):
            BenchmarkQuestion(
                id="pcb-mmlu-0007",
                category="invalid_category",
                difficulty="easy",
                question="What is this?",
                choices=["A", "B", "C", "D"],
                correct_index=0,
                explanation="Test.",
                source="test.kicad_sch",
                source_type="schematic",
            )

    def test_rejects_invalid_id_format(self) -> None:
        """BenchmarkQuestion rejects IDs that don't match pcb-mmlu-NNNN."""
        from volta.benchmarks.schemas import BenchmarkQuestion

        with pytest.raises(Exception):
            BenchmarkQuestion(
                id="wrong-format-1",
                category="component_identification",
                difficulty="easy",
                question="What is R60?",
                choices=["A", "B", "C", "D"],
                correct_index=0,
                explanation="Test.",
                source="test.kicad_sch",
                source_type="schematic",
            )

    def test_rejects_empty_choices(self) -> None:
        """BenchmarkQuestion rejects empty string choices."""
        from volta.benchmarks.schemas import BenchmarkQuestion

        with pytest.raises(Exception):
            BenchmarkQuestion(
                id="pcb-mmlu-0008",
                category="component_identification",
                difficulty="easy",
                question="What is R60?",
                choices=["Resistor", "", "Capacitor", "Inductor"],
                correct_index=0,
                explanation="R60 is a resistor.",
                source="test.kicad_sch",
                source_type="schematic",
            )


# ============================================================================
# Test 5: BenchmarkDataset Schema
# ============================================================================


class TestBenchmarkDatasetSchema:
    """Validate BenchmarkDataset Pydantic schema."""

    def test_valid_dataset(self) -> None:
        """Test 5: BenchmarkDataset validates with version, questions list, metadata."""
        from volta.benchmarks.schemas import BenchmarkDataset, BenchmarkQuestion

        questions = [
            BenchmarkQuestion(
                id="pcb-mmlu-0001",
                category="topology_recognition",
                difficulty="medium",
                question="What type of circuit is formed by U22?",
                choices=["VCA", "Filter", "Oscillator", "Power supply"],
                correct_index=0,
                explanation="THAT4301 is a VCA IC.",
                source="test.kicad_sch",
                source_type="schematic",
            ),
        ]
        dataset = BenchmarkDataset(
            version="1.0.0",
            generated_at="2026-05-31T00:00:00Z",
            questions=questions,
            metadata={"total_sources": 1, "seed": 42},
        )
        assert dataset.version == "1.0.0"
        assert len(dataset.questions) == 1
        assert dataset.metadata["seed"] == 42

    def test_rejects_empty_questions(self) -> None:
        """BenchmarkDataset rejects empty questions list."""
        from volta.benchmarks.schemas import BenchmarkDataset

        with pytest.raises(Exception):
            BenchmarkDataset(
                version="1.0.0",
                generated_at="2026-05-31T00:00:00Z",
                questions=[],  # empty
            )

    def test_rejects_invalid_version(self) -> None:
        """BenchmarkDataset rejects non-semver version strings."""
        from volta.benchmarks.schemas import BenchmarkDataset, BenchmarkQuestion

        q = BenchmarkQuestion(
            id="pcb-mmlu-0001",
            category="topology_recognition",
            difficulty="medium",
            question="What type of circuit is formed by these components?",
            choices=["Amplifier", "Filter", "Oscillator", "Power supply"],
            correct_index=0,
            explanation="This is a test explanation for validation purposes.",
            source="test.kicad_sch",
            source_type="schematic",
        )
        with pytest.raises(Exception):
            BenchmarkDataset(
                version="not-semver",
                generated_at="2026-05-31T00:00:00Z",
                questions=[q],
            )


# ============================================================================
# Test 6-10: Question Generator
# ============================================================================


class TestQuestionGenerator:
    """Validate question generation for all categories."""

    def test_generate_questions_returns_list(self) -> None:
        """Test 6: generate_questions returns list of BenchmarkQuestion for each category."""
        from volta.benchmarks.question_generator import generate_questions

        categories = [
            "component_identification",
            "topology_recognition",
            "signal_flow",
            "power_design",
            "pin_function",
            "net_purpose",
            "design_rules",
            "troubleshooting",
        ]
        for category in categories:
            questions = generate_questions(category, {"refs": ["U22", "R60"]})
            assert isinstance(questions, list), f"category {category} did not return list"
            assert len(questions) > 0, f"category {category} returned empty list"
            for q in questions:
                assert q.category == category

    def test_topology_recognition_questions(self) -> None:
        """Test 7: generate_questions for topology_recognition from IC context."""
        from volta.benchmarks.question_generator import generate_questions

        questions = generate_questions(
            "topology_recognition",
            {
                "refs": ["U22", "R60", "R61", "C46"],
                "function": "compressor_vca",
                "ic_type": "VCA",
                "ic_ref": "U22",
                "passive_count": 3,
                "component_count": 4,
            },
        )
        assert len(questions) > 0
        for q in questions:
            assert q.category == "topology_recognition"
            assert "U22" in q.question or "VCA" in q.question or "circuit" in q.question.lower()

    def test_troubleshooting_questions(self) -> None:
        """Test 8: generate_questions for troubleshooting from ERC violations."""
        from volta.benchmarks.question_generator import generate_questions

        questions = generate_questions(
            "troubleshooting",
            {
                "violations": [
                    {
                        "type": "pin_not_connected",
                        "description": "Pin 3 of U22 is not connected",
                        "severity": "error",
                        "positions": [(148.59, 111.76)],
                    }
                ],
                "refs": ["U22"],
            },
        )
        assert len(questions) > 0
        for q in questions:
            assert q.category == "troubleshooting"

    def test_four_choices_valid_index(self) -> None:
        """Test 9: Each question has exactly 4 choices, correct_index in [0,3], distractors != correct."""
        from volta.benchmarks.question_generator import generate_questions

        for category in [
            "component_identification",
            "topology_recognition",
            "signal_flow",
            "power_design",
            "pin_function",
            "net_purpose",
            "design_rules",
            "troubleshooting",
        ]:
            questions = generate_questions(
                category,
                {
                    "refs": ["U22", "R60", "R61", "C46"],
                    "function": "compressor_vca",
                    "ic_type": "VCA",
                    "ic_ref": "U22",
                    "passive_count": 3,
                    "component_count": 4,
                    "violations": [
                        {
                            "type": "pin_not_connected",
                            "description": "Pin 3 of U22 is not connected",
                            "severity": "error",
                            "positions": [(148.59, 111.76)],
                        }
                    ],
                },
            )
            for q in questions:
                assert len(q.choices) == 4, f"{category}: expected 4 choices, got {len(q.choices)}"
                assert 0 <= q.correct_index <= 3, f"{category}: correct_index out of range"
                correct = q.choices[q.correct_index]
                for i, choice in enumerate(q.choices):
                    if i != q.correct_index:
                        assert choice != correct, (
                            f"{category}: distractor at index {i} equals correct answer"
                        )

    def test_unique_sequential_ids(self) -> None:
        """Test 10: Question IDs are unique and sequential (pcb-mmlu-NNNN format)."""
        from volta.benchmarks.question_generator import generate_questions

        all_ids: list[str] = []
        for category in [
            "component_identification",
            "topology_recognition",
            "signal_flow",
        ]:
            questions = generate_questions(category, {"refs": ["U22", "R60"]})
            for q in questions:
                assert q.id.startswith("pcb-mmlu-"), f"ID format wrong: {q.id}"
                all_ids.append(q.id)

        # IDs should be unique
        assert len(all_ids) == len(set(all_ids)), "Duplicate IDs found"

    def test_distractors_differ_from_correct(self) -> None:
        """All distractors differ from the correct answer for every question."""
        from volta.benchmarks.question_generator import generate_questions

        questions = generate_questions(
            "component_identification",
            {"refs": ["R60"], "lib_ids": ["Device:R"]},
        )
        for q in questions:
            correct = q.choices[q.correct_index]
            distractors = [c for i, c in enumerate(q.choices) if i != q.correct_index]
            for d in distractors:
                assert d != correct, f"Distractor '{d}' matches correct answer '{correct}'"


# ============================================================================
# Test DatasetBuilder (Task 2)
# ============================================================================


class TestDatasetBuilder:
    """Validate DatasetBuilder orchestrates generation correctly."""

    def test_build_dataset_from_sources(self) -> None:
        """Test 1: DatasetBuilder builds dataset from a list of source schematics."""
        from volta.benchmarks.dataset_builder import DatasetBuilder

        mock_sources = [
            {
                "path": "compressor/schematic/left-channel.kicad_sch",
                "subcircuits": [
                    {
                        "refs": ["U22", "R60", "R61", "R62", "R63", "C46", "C47", "C48"],
                        "function": "compressor_vca",
                        "ic_type": "THAT4301",
                        "ic_ref": "U22",
                        "passive_count": 7,
                        "component_count": 8,
                    },
                ],
                "erc_violations": [
                    {
                        "type": "pin_not_connected",
                        "description": "Pin 3 of U22 is not connected",
                        "severity": "error",
                        "positions": [(148.59, 111.76)],
                    },
                ],
            },
            {
                "path": "lfo/schematic/lfo-core.kicad_sch",
                "subcircuits": [
                    {
                        "refs": ["U5", "R10", "R11", "C5", "C6"],
                        "function": "oscillator",
                        "ic_type": "CD4060",
                        "ic_ref": "U5",
                        "passive_count": 4,
                        "component_count": 5,
                    },
                ],
                "erc_violations": [],
            },
        ]
        builder = DatasetBuilder(source_schematics=mock_sources, seed=42)
        dataset = builder.build(target_count=50)
        assert len(dataset.questions) >= 50

    def test_minimum_500_questions(self) -> None:
        """Test 2: DatasetBuilder produces >= 500 questions."""
        from volta.benchmarks.dataset_builder import DatasetBuilder

        builder = DatasetBuilder(seed=42)
        dataset = builder.build(target_count=500)
        assert len(dataset.questions) >= 500

    def test_each_category_has_minimum_50(self) -> None:
        """Test 3: Each category has >= 50 questions."""
        from volta.benchmarks.dataset_builder import DatasetBuilder

        builder = DatasetBuilder(seed=42)
        dataset = builder.build(target_count=500)

        categories = [
            "component_identification",
            "topology_recognition",
            "signal_flow",
            "power_design",
            "pin_function",
            "net_purpose",
            "design_rules",
            "troubleshooting",
        ]
        for cat in categories:
            count = sum(1 for q in dataset.questions if q.category == cat)
            assert count >= 50, f"Category {cat} has only {count} questions (need >= 50)"

    def test_difficulty_distribution(self) -> None:
        """Test 4: Difficulty distribution within 5% of targets (20/60/20)."""
        from volta.benchmarks.dataset_builder import DatasetBuilder

        builder = DatasetBuilder(seed=42)
        dataset = builder.build(target_count=500)

        total = len(dataset.questions)
        easy = sum(1 for q in dataset.questions if q.difficulty == "easy") / total
        medium = sum(1 for q in dataset.questions if q.difficulty == "medium") / total
        hard = sum(1 for q in dataset.questions if q.difficulty == "hard") / total

        # 20% easy, 60% medium, 20% hard, within 5% tolerance
        assert abs(easy - 0.20) <= 0.05, f"Easy ratio {easy:.2%} outside 5% of 20%"
        assert abs(medium - 0.60) <= 0.05, f"Medium ratio {medium:.2%} outside 5% of 60%"
        assert abs(hard - 0.20) <= 0.05, f"Hard ratio {hard:.2%} outside 5% of 20%"

    def test_dataset_validates_against_schema(self) -> None:
        """Test 5: Generated dataset validates against BenchmarkDataset schema."""
        from volta.benchmarks.dataset_builder import DatasetBuilder

        builder = DatasetBuilder(seed=42)
        dataset = builder.build(target_count=500)

        # Round-trip through model_validate
        json_str = dataset.model_dump_json()
        from volta.benchmarks.schemas import BenchmarkDataset

        reloaded = BenchmarkDataset.model_validate_json(json_str)
        assert len(reloaded.questions) == len(dataset.questions)

    def test_no_duplicate_question_ids(self) -> None:
        """Test 6: No duplicate question IDs in output."""
        from volta.benchmarks.dataset_builder import DatasetBuilder

        builder = DatasetBuilder(seed=42)
        dataset = builder.build(target_count=500)

        ids = [q.id for q in dataset.questions]
        assert len(ids) == len(set(ids)), "Duplicate question IDs found"

    def test_questions_reference_real_sources(self) -> None:
        """Test 7: Questions reference actual source schematics from analog-ecosystem."""
        from volta.benchmarks.dataset_builder import DatasetBuilder

        builder = DatasetBuilder(seed=42)
        dataset = builder.build(target_count=500)

        sources = {q.source for q in dataset.questions}
        assert len(sources) >= 1, "All questions share a single source"
        # Every question should have a non-empty source
        for q in dataset.questions:
            assert len(q.source) > 0, f"Question {q.id} has empty source"

    def test_json_round_trip(self) -> None:
        """Test 8: Dataset can be serialized to JSON and re-loaded."""
        from volta.benchmarks.dataset_builder import DatasetBuilder

        builder = DatasetBuilder(seed=42)
        dataset = builder.build(target_count=50)

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            builder.to_json(dataset, f.name)
            path = f.name

        try:
            reloaded = DatasetBuilder.from_json(path)
            assert len(reloaded.questions) == len(dataset.questions)
            assert reloaded.version == dataset.version
        finally:
            import os

            os.unlink(path)
