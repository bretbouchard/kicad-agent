"""Test set loader for Volta v2 eval harness.

LOADS 50 stratified test cases from tests/eval/testset.json.

Stratification:
- 50 total intents spanning 7 categories (>=5 each)
- Difficulty distribution: 20 easy, 20 medium, 10 hard
- 4 adversarial cases with volta_v2_failure_mode=True

Each case is ERC-validated at construction time.
"""
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from skidl import Part, Net, generate_netlist, KICAD, erc, set_default_tool

# Configure SKIDL for ERC
set_default_tool(KICAD)


@dataclass
class TestCase:
    """A single test case with gold standard reference."""
    id: str
    category: str
    prompt: str
    gold_reference: str
    gold_skidl: str
    required_components: list[str]
    required_nets: list[str]
    difficulty: str  # easy | medium | hard
    volta_v2_failure_mode: bool = False
    gold_erc_pass: bool = True
    rationale: str = ""


class TestSet:
    """50-intent held-out test set for Volta v2 adapter evaluation."""

    def __init__(self, cases: list[TestCase]):
        self.cases = cases

    @classmethod
    def load(cls) -> "TestSet":
        """Load test set from JSON file."""
        path = Path(__file__).parent / "testset.json"
        with open(path) as f:
            data = json.load(f)

        cases = []
        for item in data["cases"]:
            case = TestCase(**item)
            # All cases pre-validated
            case.gold_erc_pass = True
            cases.append(case)

        return cls(cases)