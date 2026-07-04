"""D-03 regression: auto_layout_sch SRS within 0.10 of baseline (v1 single-sheet scope).

Runs scripts/verify_autolayout_srs.py via subprocess and asserts every
non-missing fixture is within threshold. This is the automated gate
that prevents regressions in the Sugiyama layout engine from silently
shipping.

Scope (Council Gate 1 MED-5 revision): single-sheet fixtures only.
Large-board (backplane, 16-sheet) D-03 verification deferred to Phase 145
alongside physical hierarchy sub-sheet emission. See
.planning/phases/108-deterministic-autolayout-engine/108-SRS-VERIFICATION.md.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "verify_autolayout_srs.py"


def test_script_exists() -> None:
    """Regression guard: the verification script must exist."""
    assert SCRIPT.exists(), f"Verification script missing: {SCRIPT}"


def test_srs_within_threshold() -> None:
    """D-03 gate: every non-missing fixture must be within 0.10 SRS delta."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,  # generous — large fixtures can take a while
    )
    assert result.returncode in (0, 1), (
        f"Script exited with unexpected code {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    payload = json.loads(result.stdout)
    results = payload["results"]
    # At least one fixture must be present (not all MISSING).
    scored = [r for r in results if r["status"] not in ("MISSING", "ERROR")]
    assert scored, (
        f"No fixtures were scored. All statuses: "
        f"{[r['status'] for r in results]}. "
        f"Check fixture availability + script errors."
    )
    failures = [r for r in scored if r["status"] != "PASS"]
    assert not failures, (
        "D-03 SRS threshold exceeded on: "
        + ", ".join(
            f"{r['name']} (delta={r['delta']:.3f} > {r['threshold']})"
            for r in failures
        )
    )


def test_no_spatial_extractor_from_file() -> None:
    """HIGH-3 regression: SchematicSpatialExtractor.from_file does not exist.

    A future contributor re-introducing
    `SchematicSpatialExtractor.from_file(path)` would crash with
    AttributeError on the first fixture. This grep guard catches it.

    Note: `SchematicGraph.from_file` is a DIFFERENT class and DOES exist
    (used legitimately for topology building). The guard matches only
    the SchematicSpatialExtractor variant.
    """
    content = SCRIPT.read_text()
    assert "SchematicSpatialExtractor.from_file" not in content, (
        "HIGH-3 regression: scripts/verify_autolayout_srs.py must not "
        "call SchematicSpatialExtractor.from_file (it does not exist). "
        "Use the verified chain: parse_schematic -> SchematicIR -> "
        "SchematicSpatialExtractor(ir)."
    )


def test_no_ops_operation_import() -> None:
    """HIGH-2 regression: Operation lives in kicad_agent.ops.schema.

    Importing from kicad_agent.ops.operation would fail with ModuleNotFoundError.
    """
    content = SCRIPT.read_text()
    assert "from kicad_agent.ops.operation import" not in content, (
        "HIGH-2 regression: Operation must be imported from "
        "kicad_agent.ops.schema, not kicad_agent.ops.operation."
    )


def test_no_factors_overall_access() -> None:
    """ReadabilityReport API regression: report.srs is the composite score.

    report.factors has keys density/clarity/spacing/organization only —
    there is no 'overall' key. Accessing factors['overall'] raises KeyError.

    This guard strips comment lines before checking, so docstring
    mentions of the forbidden pattern don't false-positive.
    """
    content = SCRIPT.read_text()
    # Strip comment lines (lines whose first non-whitespace char is #)
    code_lines = [
        line for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    code_only = "\n".join(code_lines)
    assert 'factors["overall"]' not in code_only, (
        "ReadabilityReport API regression: report.factors has no 'overall' key. "
        "Use report.srs (the composite score) instead."
    )


def test_threshold_constant() -> None:
    """D-03 threshold pin: must be exactly 0.10."""
    content = SCRIPT.read_text()
    # Look for the DELTA_THRESHOLD assignment
    assert "DELTA_THRESHOLD = 0.10" in content, (
        "D-03 threshold changed: expected DELTA_THRESHOLD = 0.10"
    )
