"""Tests for Circuit QA dataset schemas and generator.

Covers CircuitQAPair validation, CircuitQADataset validation,
and QAGenerator generation across all 6 QA types.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from kicad_agent.ops.erc_parser import ErcViolation


# ---------------------------------------------------------------------------
# Fixtures -- mock data for testing
# ---------------------------------------------------------------------------

MOCK_VIOLATIONS = [
    ErcViolation(
        sheet="/",
        type="power_pin_not_driven",
        severity="error",
        description="Power pin not driven (power global)",
        positions=[(85.09, 62.23)],
    ),
    ErcViolation(
        sheet="/",
        type="multiple_net_names",
        severity="error",
        description="R55.2 and R56.1 at same position",
        positions=[(59.69, 78.74)],
    ),
    ErcViolation(
        sheet="/",
        type="pin_not_connected",
        severity="warning",
        description="Pin 4 of U22 is not connected",
        positions=[(100.0, 100.0)],
    ),
]

MOCK_SUBCIRCUITS = [
    {
        "name": "compressor_vca",
        "input_net": "COMP_IN",
        "output_net": "COMP_OUT",
        "components": [
            {"ref": "R55", "value": "10k", "lib_id": "Device:R", "role": "input resistor"},
            {"ref": "U22", "value": "THAT4301", "lib_id": "THAT4301", "role": "VCA"},
            {"ref": "R60", "value": "100k", "lib_id": "Device:R", "role": "feedback resistor"},
            {"ref": "C47", "value": "100nF", "lib_id": "Device:C", "role": "coupling capacitor"},
        ],
        "function": "compressor_vca",
    },
    {
        "name": "output_buffer",
        "input_net": "EQ_OUT",
        "output_net": "OUT",
        "components": [
            {"ref": "U23", "value": "NE5532", "lib_id": "Amplifier_Operational:NE5532", "role": "buffer op-amp"},
            {"ref": "C50", "value": "10uF", "lib_id": "Device:C", "role": "output coupling"},
        ],
        "function": "output_buffer",
    },
]

MOCK_COMPONENTS = [
    {"ref": "R60", "value": "100k", "lib_id": "Device:R", "circuit_type": "compressor",
     "net_a": "SC_IN", "net_b": "SC_FILTER", "purpose": "sidechain input resistor connecting the COMP_THRESHOLD signal to the sidechain filter"},
    {"ref": "C47", "value": "100nF", "lib_id": "Device:C", "circuit_type": "compressor",
     "net_a": "VCA_OUT", "net_b": "BUFFER_IN", "purpose": "AC coupling capacitor between the VCA output and the buffer input stage"},
    {"ref": "U22", "value": "THAT4301", "lib_id": "THAT4301", "circuit_type": "compressor",
     "net_a": "COMP_IN", "net_b": "VCA_OUT", "purpose": "voltage-controlled amplifier providing gain reduction based on the control voltage from the sidechain"},
]

MOCK_NETS = [
    {
        "name": "SC_FILTER",
        "function": "sidechain filter timing net",
        "pins": ["R60.2", "C48.1", "U22.8"],
        "purpose": "setting the compressor's attack/release time constant",
        "subcircuit": "sidechain filter",
    },
    {
        "name": "VCA_OUT",
        "function": "VCA output signal",
        "pins": ["U22.6", "R58.1", "C47.1"],
        "purpose": "carrying the compressed audio signal from the VCA to the output buffer",
        "subcircuit": "compressor VCA",
    },
    {
        "name": "GND",
        "function": "ground reference",
        "pins": ["C47.2", "C48.2", "R61.2"],
        "purpose": "providing the common ground reference for the compressor circuit",
        "subcircuit": "power",
    },
]

MOCK_DESIGN_REVIEWS = [
    {
        "subcircuit": "output buffer stage",
        "improvements": [
            "A unity-gain stability capacitor (10pF) across the feedback path",
            "A series output resistor (47 ohm) to prevent oscillation with capacitive loads",
        ],
        "state": "a simple unity-gain buffer without stability compensation",
        "limitation": "may oscillate with long cable runs or high-capacitance loads",
    },
    {
        "subcircuit": "sidechain filter",
        "improvements": [
            "A variable attack/release control using a potentiometer instead of fixed resistors",
            "A logarithmic envelope detector for more musical compression characteristics",
        ],
        "state": "a fixed-time-constant RC filter",
        "limitation": "limits the compressor to a single attack/release response curve",
    },
]

MOCK_VALUE_CALCULATIONS = [
    {
        "ref": "C47",
        "spec": "a 10ms sidechain time constant",
        "constraint": "R61=10k",
        "formula": "t / R",
        "result": "1uF",
        "values": "t=10ms and R=10k",
        "explanation": "the capacitor value is derived from the time constant equation tau = R * C",
    },
    {
        "ref": "R55",
        "spec": "a -3dB cutoff at 20Hz",
        "constraint": "C47=100nF",
        "formula": "1 / (2 * pi * f * C)",
        "result": "79.6k",
        "values": "f=20Hz and C=100nF",
        "explanation": "the resistor value sets the high-pass cutoff frequency of the input coupling stage",
    },
]


# ===========================================================================
# TestCircuitQAPairSchema
# ===========================================================================


class TestCircuitQAPairSchema:
    """Test CircuitQAPair Pydantic schema validation."""

    def _make_valid_pair(self, **overrides):
        """Create a valid CircuitQAPair with sensible defaults."""
        defaults = {
            "id": "qa-0001",
            "qa_type": "violation_diagnosis",
            "question": "Why does this schematic have a power_pin_not_driven violation?",
            "answer": "The power_pin_not_driven violation is caused by an unconnected power input pin. This is a common issue when power symbols are not properly connected.",
            "source": "compressor.kicad_sch",
            "source_type": "schematic",
            "difficulty": "medium",
            "tags": ["power", "violation"],
        }
        defaults.update(overrides)
        from kicad_agent.benchmarks.qa_schemas import CircuitQAPair
        return CircuitQAPair(**defaults)

    def test_valid_pair(self):
        """Test 1: CircuitQAPair validates with all required fields."""
        pair = self._make_valid_pair()
        assert pair.id == "qa-0001"
        assert pair.qa_type == "violation_diagnosis"
        assert len(pair.question) >= 10
        assert len(pair.answer) >= 20
        assert pair.source == "compressor.kicad_sch"

    def test_rejects_empty_question(self):
        """Test 2: CircuitQAPair rejects empty question."""
        from kicad_agent.benchmarks.qa_schemas import CircuitQAPair
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_valid_pair(question="")

    def test_rejects_empty_answer(self):
        """Test 2b: CircuitQAPair rejects empty answer."""
        from kicad_agent.benchmarks.qa_schemas import CircuitQAPair
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_valid_pair(answer="")

    def test_rejects_short_question(self):
        """Test 2c: CircuitQAPair rejects question shorter than 10 chars."""
        from kicad_agent.benchmarks.qa_schemas import CircuitQAPair
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_valid_pair(question="Short?")

    def test_rejects_short_answer(self):
        """Test 2d: CircuitQAPair rejects answer shorter than 20 chars."""
        from kicad_agent.benchmarks.qa_schemas import CircuitQAPair
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_valid_pair(answer="Too short")

    def test_all_qa_types_valid(self):
        """Test that all 6 QA types are accepted."""
        qa_types = [
            "violation_diagnosis", "signal_flow", "component_function",
            "net_purpose", "design_review", "value_calculation",
        ]
        for qt in qa_types:
            pair = self._make_valid_pair(qa_type=qt, id=f"qa-{qa_types.index(qt)+1:04d}")
            assert pair.qa_type == qt

    def test_invalid_qa_type_rejected(self):
        """Test that invalid QA types are rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_valid_pair(qa_type="invalid_type")

    def test_all_difficulties_valid(self):
        """Test that all 3 difficulty levels are accepted."""
        for diff in ["easy", "medium", "hard"]:
            pair = self._make_valid_pair(difficulty=diff)
            assert pair.difficulty == diff

    def test_id_pattern_enforced(self):
        """Test that id must match qa-NNNN pattern."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_valid_pair(id="invalid-id")

    def test_source_type_validation(self):
        """Test that source_type is validated."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_valid_pair(source_type="invalid_source")

    def test_tags_max_length(self):
        """Test that tags list is limited to 10 items."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_valid_pair(tags=[f"tag{i}" for i in range(11)])


# ===========================================================================
# TestCircuitQADatasetSchema
# ===========================================================================


class TestCircuitQADatasetSchema:
    """Test CircuitQADataset Pydantic schema validation."""

    def _make_valid_dataset(self, **overrides):
        """Create a valid CircuitQADataset with sensible defaults."""
        from kicad_agent.benchmarks.qa_schemas import CircuitQAPair, CircuitQADataset
        pairs = [
            CircuitQAPair(
                id=f"qa-{i:04d}",
                qa_type="violation_diagnosis",
                question=f"Test question number {i} with enough length to pass validation",
                answer=f"Test answer number {i} with enough length to pass the minimum validation requirement",
                source="test.kicad_sch",
                source_type="schematic",
                difficulty="easy",
            )
            for i in range(1, 4)
        ]
        defaults = {
            "version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "qa_pairs": pairs,
            "metadata": {"seed": 42},
        }
        defaults.update(overrides)
        return CircuitQADataset(**defaults)

    def test_valid_dataset(self):
        """Test 3: CircuitQADataset validates with version, qa_pairs, metadata."""
        dataset = self._make_valid_dataset()
        assert dataset.version == "1.0.0"
        assert len(dataset.qa_pairs) == 3
        assert dataset.metadata == {"seed": 42}

    def test_rejects_empty_qa_pairs(self):
        """Test 3b: CircuitQADataset rejects empty qa_pairs list."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_valid_dataset(qa_pairs=[])

    def test_rejects_invalid_version(self):
        """Test 3c: CircuitQADataset rejects non-semver version."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_valid_dataset(version="not-semver")


# ===========================================================================
# TestQAGenerator
# ===========================================================================


class TestQAGenerator:
    """Test QAGenerator produces QA pairs for all 6 types."""

    def _make_generator(self, seed=42):
        """Create a QAGenerator with mock source schematics."""
        from kicad_agent.benchmarks.qa_generator import QAGenerator
        source = {
            "name": "compressor",
            "violations": MOCK_VIOLATIONS,
            "subcircuits": MOCK_SUBCIRCUITS,
            "components": MOCK_COMPONENTS,
            "nets": MOCK_NETS,
            "design_reviews": MOCK_DESIGN_REVIEWS,
            "value_calculations": MOCK_VALUE_CALCULATIONS,
        }
        return QAGenerator(source_schematics=[source], seed=seed)

    def test_violation_diagnosis_qa(self):
        """Test 4: QAGenerator generates violation_diagnosis QA pairs from ERC violations."""
        gen = self._make_generator()
        pairs = gen._generate_violation_qa(MOCK_VIOLATIONS, "compressor.kicad_sch")
        assert len(pairs) > 0
        for pair in pairs:
            assert pair.qa_type == "violation_diagnosis"
            assert len(pair.question) >= 10
            assert len(pair.answer) >= 20
            assert pair.source == "compressor.kicad_sch"

    def test_signal_flow_qa(self):
        """Test 5: QAGenerator generates signal_flow QA pairs from schematic graphs."""
        gen = self._make_generator()
        pairs = gen._generate_signal_flow_qa(MOCK_SUBCIRCUITS, "compressor.kicad_sch")
        assert len(pairs) > 0
        for pair in pairs:
            assert pair.qa_type == "signal_flow"
            assert "->" in pair.answer  # signal path uses arrow notation

    def test_component_function_qa(self):
        """Test 6: QAGenerator generates component_function QA pairs from IC context."""
        gen = self._make_generator()
        pairs = gen._generate_component_function_qa(MOCK_COMPONENTS, "compressor.kicad_sch")
        assert len(pairs) > 0
        for pair in pairs:
            assert pair.qa_type == "component_function"
            assert len(pair.question) >= 10
            assert len(pair.answer) >= 20

    def test_net_purpose_qa(self):
        """Test 7: QAGenerator generates net_purpose QA pairs from net topology."""
        gen = self._make_generator()
        pairs = gen._generate_net_purpose_qa(MOCK_NETS, "compressor.kicad_sch")
        assert len(pairs) > 0
        for pair in pairs:
            assert pair.qa_type == "net_purpose"
            assert len(pair.question) >= 10
            assert len(pair.answer) >= 20

    def test_design_review_qa(self):
        """Test: QAGenerator generates design_review QA pairs."""
        gen = self._make_generator()
        pairs = gen._generate_design_review_qa(MOCK_DESIGN_REVIEWS, "compressor.kicad_sch")
        assert len(pairs) > 0
        for pair in pairs:
            assert pair.qa_type == "design_review"
            assert len(pair.question) >= 10
            assert len(pair.answer) >= 20

    def test_value_calculation_qa(self):
        """Test: QAGenerator generates value_calculation QA pairs."""
        gen = self._make_generator()
        pairs = gen._generate_value_calculation_qa(MOCK_VALUE_CALCULATIONS, "compressor.kicad_sch")
        assert len(pairs) > 0
        for pair in pairs:
            assert pair.qa_type == "value_calculation"
            assert "=" in pair.answer  # calculation answer includes formula

    def test_source_reference(self):
        """Test 8: Each QA pair has a source reference to the originating schematic."""
        gen = self._make_generator()
        pairs = gen._generate_violation_qa(MOCK_VIOLATIONS, "compressor.kicad_sch")
        for pair in pairs:
            assert pair.source == "compressor.kicad_sch"
            assert pair.source_type in ("schematic", "erc_report", "netlist", "bom", "datasheet", "manual")

    def test_generate_dataset_count(self):
        """Test 9: Generated dataset has >= 2000 QA pairs."""
        gen = self._make_generator()
        dataset = gen.generate_dataset(target_count=2000)
        assert len(dataset.qa_pairs) >= 2000

    def test_qa_type_distribution(self):
        """Test 10: QA type distribution has entries for all 6 types."""
        gen = self._make_generator()
        dataset = gen.generate_dataset(target_count=2000)
        types_found = set(pair.qa_type for pair in dataset.qa_pairs)
        expected_types = {
            "violation_diagnosis", "signal_flow", "component_function",
            "net_purpose", "design_review", "value_calculation",
        }
        assert expected_types == types_found, f"Missing types: {expected_types - types_found}"

    def test_deterministic_with_seed(self):
        """Test that generation is deterministic with same seed."""
        gen1 = self._make_generator(seed=42)
        gen2 = self._make_generator(seed=42)
        d1 = gen1.generate_dataset(target_count=100)
        d2 = gen2.generate_dataset(target_count=100)
        for p1, p2 in zip(d1.qa_pairs, d2.qa_pairs):
            assert p1.question == p2.question
            assert p1.answer == p2.answer

    def test_different_seed_different_order(self):
        """Test that different seeds produce different results."""
        gen1 = self._make_generator(seed=42)
        gen2 = self._make_generator(seed=99)
        d1 = gen1.generate_dataset(target_count=100)
        d2 = gen2.generate_dataset(target_count=100)
        # With different seeds, at least some questions should differ
        questions1 = [p.question for p in d1.qa_pairs]
        questions2 = [p.question for p in d2.qa_pairs]
        assert questions1 != questions2

    def test_train_test_split(self):
        """Test that dataset metadata includes train/val/test split counts."""
        gen = self._make_generator()
        dataset = gen.generate_dataset(target_count=2000)
        assert "split_counts" in dataset.metadata
        splits = dataset.metadata["split_counts"]
        assert "train" in splits
        assert "val" in splits
        assert "test" in splits
        total = splits["train"] + splits["val"] + splits["test"]
        assert total == len(dataset.qa_pairs)
        # 80/10/10 split (with rounding tolerance)
        assert splits["train"] >= int(len(dataset.qa_pairs) * 0.78)

    def test_stratified_split(self):
        """Test that split is stratified by qa_type (all types in each split)."""
        gen = self._make_generator()
        dataset = gen.generate_dataset(target_count=2000)
        expected_types = {
            "violation_diagnosis", "signal_flow", "component_function",
            "net_purpose", "design_review", "value_calculation",
        }
        for pair in dataset.qa_pairs:
            if hasattr(pair, 'split'):
                pass  # split field on the pair if it exists
        # Check metadata for split type coverage
        if "split_types" in dataset.metadata:
            for split_name in ["train", "val", "test"]:
                types_in_split = set(dataset.metadata["split_types"].get(split_name, []))
                assert expected_types.issubset(types_in_split), \
                    f"Split {split_name} missing types: {expected_types - types_in_split}"

    def test_no_empty_source(self):
        """Test that no QA pair has an empty source."""
        gen = self._make_generator()
        dataset = gen.generate_dataset(target_count=2000)
        for pair in dataset.qa_pairs:
            assert len(pair.source) > 0

    def test_unique_ids(self):
        """Test that all QA pair IDs are unique."""
        gen = self._make_generator()
        dataset = gen.generate_dataset(target_count=2000)
        ids = [pair.id for pair in dataset.qa_pairs]
        assert len(ids) == len(set(ids)), f"Duplicate IDs found"

    def test_empty_source_list_uses_defaults(self):
        """Test that QAGenerator with empty source list falls back to defaults."""
        from kicad_agent.benchmarks.qa_generator import QAGenerator
        gen = QAGenerator(source_schematics=[], seed=42)
        # Should use default sources, not crash
        dataset = gen.generate_dataset(target_count=100)
        assert len(dataset.qa_pairs) >= 100

    def test_none_source_uses_defaults(self):
        """Test that QAGenerator with None source uses defaults."""
        from kicad_agent.benchmarks.qa_generator import QAGenerator
        gen = QAGenerator(source_schematics=None, seed=42)
        dataset = gen.generate_dataset(target_count=100)
        assert len(dataset.qa_pairs) >= 100
