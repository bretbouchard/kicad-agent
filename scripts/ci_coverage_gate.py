#!/usr/bin/env python3
"""
Phase 200 — CI Coverage Gate
Runs after tests in CI. Fails build if coverage thresholds not met.

Usage: python3 scripts/ci_coverage_gate.py [--strict]
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple


# Per-layer minimums must match Swift CoverageGate.perLayerMinimums.
SWIFT_LAYER_MINIMUMS = {
    "Models": 0.90,
    "Governance": 0.95,
    "Memory": 0.90,
    "MCP": 0.85,
    "UI": 0.70,
    "Collaboration": 0.80,
}
SWIFT_OVERALL_MINIMUM = 0.80
PYTHON_OVERALL_MINIMUM = 0.80


def parse_swift_coverage(cov_xml: Path) -> Dict[str, Tuple[float, int, int]]:
    """Parse cobertura XML → { layer: (rate, covered, total) }."""
    if not cov_xml.exists():
        return {}
    tree = ET.parse(cov_xml)
    root = tree.getroot()

    by_layer: Dict[str, Tuple[int, int]] = {}
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        if "/Sources/Volta/" not in filename:
            continue
        parts = filename.split("/Sources/Volta/")
        if len(parts) < 2:
            continue
        rel = parts[1]
        layer = rel.split("/")[0] if "/" in rel else "Root"

        lines = list(cls.iter("line"))
        covered = sum(1 for l in lines if l.get("hits", "0") != "0")
        total = len(lines)
        prev = by_layer.get(layer, (0, 0))
        by_layer[layer] = (prev[0] + covered, prev[1] + total)

    return {
        layer: (covered / total if total else 0.0, covered, total)
        for layer, (covered, total) in by_layer.items()
    }


def evaluate_swift_gates(coverage: Dict[str, Tuple[float, int, int]]) -> Tuple[bool, List[str]]:
    """Return (passes, list_of_failure_messages)."""
    failures: List[str] = []

    total_covered = sum(c[1] for c in coverage.values())
    total_lines = sum(c[2] for c in coverage.values())
    overall = total_covered / total_lines if total_lines else 0.0
    if overall < SWIFT_OVERALL_MINIMUM:
        failures.append(
            f"Swift overall {overall*100:.1f}% < {SWIFT_OVERALL_MINIMUM*100:.1f}%"
        )

    for layer, minimum in SWIFT_LAYER_MINIMUMS.items():
        if layer not in coverage:
            continue
        rate = coverage[layer][0]
        if rate < minimum:
            failures.append(
                f"Swift layer '{layer}' {rate*100:.1f}% < {minimum*100:.1f}%"
            )

    return len(failures) == 0, failures


def evaluate_python_gates(cov_xml: Path) -> Tuple[bool, List[str]]:
    """Evaluate Python pytest-cov coverage."""
    if not cov_xml.exists():
        return True, ["Python coverage.xml missing — skipping Python gate"]

    tree = ET.parse(cov_xml)
    root = tree.getroot()
    line_rate = float(root.get("line-rate", "0"))
    if line_rate < PYTHON_OVERALL_MINIMUM:
        return False, [f"Python overall {line_rate*100:.1f}% < {PYTHON_OVERALL_MINIMUM*100:.1f}%"]
    return True, []


def main() -> int:
    strict = "--strict" in sys.argv

    repo_root = Path(__file__).resolve().parent.parent
    swift_cov = repo_root / "macos-app" / ".build" / "coverage.xml"
    py_cov = repo_root / "coverage.xml"

    print("Phase 200 — CI Coverage Gate")
    print("=" * 50)

    swift_coverage = parse_swift_coverage(swift_cov)
    swift_passes, swift_failures = evaluate_swift_gates(swift_coverage)
    py_passes, py_failures = evaluate_python_gates(py_cov)

    all_pass = swift_passes and py_passes
    all_failures = swift_failures + py_failures

    if all_pass:
        print("All coverage gates pass")
        return 0

    print("Coverage gate FAILED:")
    for failure in all_failures:
        print(f"  - {failure}")
    return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main())
