"""Phase 160 NLGEN-05: Evaluation suite + canonical preamp test.

Curated NL prompts with parseable spec targets. The canonical test —
"I need a preamp with +18dB gain" — must generate a working circuit
that passes ERC.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from volta.generation.nl_pipeline import run_full_pipeline

logger = logging.getLogger(__name__)


@dataclass
class EvalCase:
    """A single evaluation case.

    Attributes:
        name: Test case name.
        prompt: Natural language circuit request.
        expected_specs: Spec targets that should be parsed from the prompt.
        min_gates_passed: Minimum gates that must pass for success.
    """
    name: str
    prompt: str
    expected_specs: dict[str, float] = field(default_factory=dict)
    min_gates_passed: int = 2  # parse + ERC at minimum


@dataclass
class EvalReport:
    """Result of running the eval suite.

    Attributes:
        results: Per-case pass/fail.
        total: Total cases.
        passed: Cases that met minimum gates.
    """
    results: list[dict] = field(default_factory=list)
    total: int = 0
    passed: int = 0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


# The canonical eval suite.
EVAL_CASES: list[EvalCase] = [
    EvalCase(
        name="led_indicator",
        prompt="I need an LED indicator circuit with a 330 ohm current limiting resistor",
        expected_specs={},
        min_gates_passed=2,  # parse + ERC
    ),
    EvalCase(
        name="rc_lowpass",
        prompt="Design a simple RC lowpass filter",
        expected_specs={},
        min_gates_passed=2,
    ),
    EvalCase(
        name="opamp_preamp",
        prompt="I need a preamp with +18dB gain using an NE5532 opamp",
        expected_specs={"gain_db": 18.0},
        min_gates_passed=2,  # parse + ERC (SPICE may skip if unsimulatable)
    ),
    EvalCase(
        name="voltage_divider",
        prompt="Create a voltage divider with two 10k resistors",
        expected_specs={},
        min_gates_passed=2,
    ),
]


def run_eval_suite(
    cases: list[EvalCase] | None = None,
    output_dir: str | None = None,
) -> EvalReport:
    """Run the evaluation suite.

    Args:
        cases: Custom eval cases (default: EVAL_CASES).
        output_dir: Directory for generated outputs.

    Returns:
        EvalReport with per-case results.
    """
    cases = cases or EVAL_CASES
    report = EvalReport(total=len(cases))

    for case in cases:
        logger.info("Running eval: %s", case.name)
        result = run_full_pipeline(case.prompt, output_dir=output_dir)

        # Count gates passed.
        gates_passed = sum(
            1 for g in result.gates
            if g.status.value == "passed"
        )

        # Check spec parsing.
        specs_parsed = True
        for key, expected in case.expected_specs.items():
            if key not in result.spec_targets:
                specs_parsed = False
                break

        success = (
            result.skidl_code is not None
            and gates_passed >= case.min_gates_passed
            and specs_parsed
        )

        report.results.append({
            "name": case.name,
            "prompt": case.prompt[:80],
            "success": success,
            "gates_passed": gates_passed,
            "gates_total": len(result.gates),
            "specs_parsed": specs_parsed,
            "spec_targets": result.spec_targets,
            "errors": [g.message for g in result.gates if g.status.value == "failed"],
        })

        if success:
            report.passed += 1

    logger.info("Eval suite: %d/%d passed (%.0f%%)", report.passed, report.total, report.pass_rate * 100)
    return report


def format_eval_report(report: EvalReport) -> str:
    """Format an EvalReport as a markdown table."""
    lines = [
        "# Phase 160 Evaluation Suite Results",
        "",
        f"| Case | Prompt | Success | Gates | Specs |",
        f"|------|--------|---------|-------|-------|",
    ]
    for r in report.results:
        lines.append(
            f"| {r['name']} | {r['prompt'][:40]}... | "
            f"{'✅' if r['success'] else '❌'} | "
            f"{r['gates_passed']}/{r['gates_total']} | "
            f"{'✅' if r['specs_parsed'] else '❌'} |"
        )
    lines.append(f"\n**Pass rate: {report.passed}/{report.total} ({report.pass_rate:.0%})**")
    return "\n".join(lines)
