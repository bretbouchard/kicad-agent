"""Phase 108 verification: D-03 SRS + Task 2 on-page geometry gates.

Runs scripts/verify_autolayout_srs.py via subprocess and asserts every
non-missing fixture (1) passes overall AND (2) has every placed symbol
on-page with no stacks. The geometry gate (Phase 108 Task 2) is the hard
gate that prevents the worst-case failure mode the SRS scorer missed:
components off the side of the page + 125-deep label stacks.

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


def _run_verification() -> dict:
    """Run verify_autolayout_srs.py --json and return the parsed payload."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        timeout=300,  # generous — large fixtures can take a while
    )
    assert result.returncode in (0, 1), (
        f"Script exited with unexpected code {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return json.loads(result.stdout)


def test_script_exists() -> None:
    """Regression guard: the verification script must exist."""
    assert SCRIPT.exists(), f"Verification script missing: {SCRIPT}"


def test_srs_within_threshold() -> None:
    """D-03 gate: every non-missing fixture must PASS overall.

    Per Phase 108 Task 2: PASS now requires BOTH geometry gate (off_page=0,
    max_stack<=1) AND (informationally) SRS delta. The geometry gate is the
    hard requirement — SRS delta is reported but doesn't fail overall when
    a corrupt baseline produces an artificially low reference (Arduino_Mega
    has 125 stacked R? symbols in the fixture — autolayout fixes them,
    legitimately exceeding the 0.10 delta).
    """
    payload = _run_verification()
    results = payload["results"]
    scored = [r for r in results if r["status"] not in ("MISSING", "ERROR")]
    assert scored, (
        f"No fixtures were scored. All statuses: "
        f"{[r['status'] for r in results]}. "
        f"Check fixture availability + script errors."
    )
    failures = [r for r in scored if r["status"] != "PASS"]
    assert not failures, (
        "Verification FAILED on: "
        + ", ".join(
            f"{r['name']} (off_page={r.get('off_page_count')}, "
            f"max_stack={r.get('max_stack_depth')}, "
            f"srs_delta={r.get('delta', 0):.3f})"
            for r in failures
        )
    )


def test_no_components_off_page() -> None:
    """Phase 108 Task 2 geometry gate: every placed symbol must be on-page.

    This is the gate that would have caught the original failure: Arduino_Mega
    autolayout produced 4 components off-page (including one at (5000,5000))
    but SRS scorer reported PASS. The geometry gate is now a hard FAIL.

    Page bounds: paper minus USABLE_PAGE_MARGIN_MM (20mm) on each edge.
    A4 landscape = 297x210mm, usable = [20,277]x[20,190].
    """
    payload = _run_verification()
    results = payload["results"]
    off_page = [
        (r["name"], r["off_page_count"])
        for r in results
        if r["status"] not in ("MISSING", "ERROR") and r["off_page_count"] > 0
    ]
    assert not off_page, (
        "Off-page components detected (Phase 108 Task 2 geometry gate): "
        + ", ".join(f"{n}={c}" for n, c in off_page)
    )


def test_no_stacked_components() -> None:
    """Phase 108 Task 2 geometry gate: no two symbols at the same (X, Y).

    The Arduino_Mega fixture had 125 resistors stacked at (50,30) — visually
    illegible. The on-page fix parks each at a unique grid spot; this test
    pins that max_stack_depth stays <= 1.
    """
    payload = _run_verification()
    results = payload["results"]
    stacked = [
        (r["name"], r["max_stack_depth"])
        for r in results
        if r["status"] not in ("MISSING", "ERROR") and r["max_stack_depth"] > 1
    ]
    assert not stacked, (
        "Stacked components detected (Phase 108 Task 2 geometry gate): "
        + ", ".join(f"{n} max_stack={c}" for n, c in stacked)
    )


def test_parked_components_reported() -> None:
    """Phase 108 Task 2 reporting: components_parked key present per fixture.

    The park+report approach (per user answer) surfaces fixture corruption:
    a healthy fixture has components_parked=0; a corrupt one like
    Arduino_Mega reports ~130. Either way the key must be present so
    downstream consumers can inspect fixture health.
    """
    payload = _run_verification()
    results = payload["results"]
    missing_key = [
        r["name"]
        for r in results
        if r["status"] not in ("MISSING", "ERROR")
        and "components_parked" not in r
    ]
    assert not missing_key, (
        "components_parked key missing from results: "
        + ", ".join(missing_key)
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
    """HIGH-2 regression: Operation lives in volta.ops.schema.

    Importing from volta.ops.operation would fail with ModuleNotFoundError.
    """
    content = SCRIPT.read_text()
    assert "from volta.ops.operation import" not in content, (
        "HIGH-2 regression: Operation must be imported from "
        "volta.ops.schema, not volta.ops.operation."
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
