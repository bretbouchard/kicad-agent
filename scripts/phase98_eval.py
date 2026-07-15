#!/usr/bin/env python3
"""Phase 98 eval harness: AI vs deterministic routing strategy comparison.

Runs both DeterministicStrategy and AiRoutingStrategy through the Phase 100
RoutingOrchestrator on 3 fixture boards, captures metrics, and emits a
comparison table.

Usage:
    python scripts/phase98_eval.py                           # all fixtures, both strategies
    python scripts/phase98_eval.py --fixtures smd_test_board # single fixture
    python scripts/phase98_eval.py --json                    # machine-readable output
    python scripts/phase98_eval.py --no-ai                   # deterministic baseline only

Success criteria (CONTEXT.md):
    SC-1: model emits parseable strategy JSON on >=95% of fixture renders
    SC-2: AI matches or beats deterministic on >=2 of {completion, vias, trace}
    SC-3: zero DRC regressions vs baseline
    SC-4: validation gate rejects 100% synthetic invalid (unit-tested in Plan 02)
    SC-5: end-to-end on >=3 fixtures
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from volta.routing.orchestrator import (
    RoutingOrchestrationResult,
    RoutingOrchestrator,
)
from volta.routing.strategy import DeterministicStrategy

_REPO_ROOT = Path(__file__).resolve().parents[1]

FIXTURES: dict[str, Path] = {
    "smd_test_board": _REPO_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb",
    "raspberrypi_uhat": _REPO_ROOT / "tests" / "fixtures" / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_pcb",
    "synthetic_4layer": _REPO_ROOT / "tests" / "fixtures" / "phase99_synthetic_4layer_mixedsignal.kicad_pcb",
}

_AI_FALLBACK_MARKER = "ai_fallback:"

# Default adapter path (CONTEXT.md locked decision).
_ADAPTER_PATH = Path("/Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v2-mlx/")


# ---------------------------------------------------------------------------
# Task 1: Data types + strategy runner + DRC runner
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyEvalResult:
    """Per-strategy per-fixture evaluation metrics.

    Captures every metric needed to evaluate SC-1 through SC-5. Mirrors the
    design in 98-RESEARCH.md "Eval Harness Design" section.
    """

    fixture_name: str
    strategy_name: str  # "DeterministicStrategy" or "AiRoutingStrategy"
    total_nets: int
    routed_nets: int
    completion_pct: float
    via_count: int
    total_trace_length_mm: float
    drc_pass: bool
    drc_unconnected: int
    elapsed_seconds: float
    # AI-specific diagnostics (always populated; meaningful for AI strategy)
    parse_success: bool
    validation_passed: bool


def run_strategy_with_orchestrator(
    strategy: Any,
    pcb_path: Path,
    project_dir: Path,
    strategy_name: str,
    *,
    drc_tag: str = "default",
) -> StrategyEvalResult:
    """Run a strategy through the orchestrator and collect eval metrics.

    Constructs a RoutingOrchestrator with the given strategy, calls
    route_board, then computes per-strategy metrics from the per_net dict.

    Args:
        strategy: A RoutingStrategy implementation (DeterministicStrategy
            or AiRoutingStrategy).
        pcb_path: Path to the .kicad_pcb file (must already be a copy in a
            temp/project dir — the orchestrator mutates it in place).
        project_dir: Project directory for audit trail output.
        strategy_name: Display name for the result ("DeterministicStrategy"
            or "AiRoutingStrategy").
        drc_tag: Tag passed to :func:`run_drc` to avoid report-path collisions
            when deterministic and AI copies share the same stem (ME-03).

    Returns:
        StrategyEvalResult with computed metrics + DRC result.
    """
    start = time.time()
    orch = RoutingOrchestrator(strategy=strategy)
    result: RoutingOrchestrationResult = orch.route_board(
        pcb_path, project_dir=project_dir
    )
    elapsed = time.time() - start

    total_nets = len(result.per_net)
    routed_nets = result.total_routed
    completion_pct = routed_nets / total_nets if total_nets > 0 else 0.0
    via_count = sum(nr.via_count for nr in result.per_net.values())
    total_trace_length_mm = sum(
        nr.route_length_mm for nr in result.per_net.values()
    )

    # AI fallback detection: if any net's notes contain the fallback marker,
    # the AI path failed and DeterministicStrategy took over.
    parse_success = True
    validation_passed = True
    if strategy_name == "AiRoutingStrategy":
        for nr in result.per_net.values():
            if _AI_FALLBACK_MARKER in nr.notes:
                parse_success = False
                validation_passed = False
                break

    drc_pass, drc_unconnected = run_drc(pcb_path, tag=drc_tag)

    return StrategyEvalResult(
        fixture_name=pcb_path.stem,
        strategy_name=strategy_name,
        total_nets=total_nets,
        routed_nets=routed_nets,
        completion_pct=round(completion_pct, 4),
        via_count=via_count,
        total_trace_length_mm=round(total_trace_length_mm, 2),
        drc_pass=drc_pass,
        drc_unconnected=drc_unconnected,
        elapsed_seconds=round(elapsed, 3),
        parse_success=parse_success,
        validation_passed=validation_passed,
    )


def run_drc(pcb_path: Path, *, tag: str = "default") -> tuple[bool, int]:
    """Run kicad-cli pcb drc on a PCB file.

    Returns:
        (drc_pass, unconnected_count). On any failure (kicad-cli missing,
        timeout, malformed report), returns (False, -1) sentinel so the
        eval harness continues without crashing.

    Args:
        pcb_path: Path to the .kicad_pcb file to check.
        tag: Tag embedded in the report filename (``<stem>.<tag>.drc.json``)
            so deterministic and AI runs on same-stem copies do not collide.
            ME-03 (Council): previously both callers wrote ``<stem>.drc.json``
            clobbering each other.

    Threat T-98-03-02: best-effort. DRC must never crash the eval harness.
    """
    out_path = pcb_path.with_suffix(f".{tag}.drc.json")
    try:
        proc = subprocess.run(
            [
                "kicad-cli", "pcb", "drc", str(pcb_path),
                "--output", str(out_path),
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, -1
    if proc.returncode != 0 or not out_path.exists():
        return False, -1
    try:
        report = json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, -1
    violations = report.get("violations", [])
    unconnected = sum(
        1 for v in violations
        if v.get("type") == "unconnected_items"
        or "unconnected" in str(v.get("description", "")).lower()
    )
    return unconnected == 0, unconnected


def load_ai_strategy(pcb_path: Path) -> Any:
    """Construct an AiRoutingStrategy with the real vision model.

    This is the ONLY function that loads the 23.8 GB model. Kept isolated so
    unit tests never trigger it.

    Args:
        pcb_path: Path to the .kicad_pcb to render for vision input.

    Returns:
        AiRoutingStrategy instance ready for orchestrator dispatch.

    Raises:
        ImportError: if mlx_vlm is not installed.
        FileNotFoundError: if the adapter path does not exist.
    """
    from volta.inference.vision_pipeline import (
        KiCadVisionConfig,
        KiCadVisionPipeline,
    )
    from volta.routing.ai_strategy import AiRoutingStrategy

    if not _ADAPTER_PATH.exists():
        raise FileNotFoundError(
            f"Vision adapter not found at {_ADAPTER_PATH}. "
            "Set the adapter path or retrain the model."
        )

    config = KiCadVisionConfig(adapter_path=_ADAPTER_PATH)
    pipeline = KiCadVisionPipeline(config)
    return AiRoutingStrategy(pipeline, pcb_path)


# ---------------------------------------------------------------------------
# Task 2: Comparison table, SC evaluators, CLI
# ---------------------------------------------------------------------------

_TABLE_COLUMNS = (
    "fixture",
    "strategy",
    "completion_pct",
    "via_count",
    "trace_length_mm",
    "drc_pass",
    "parse_success",
)


def format_comparison_table(results: list[StrategyEvalResult]) -> str:
    """Render a markdown comparison table from eval results.

    Groups rows by fixture (deterministic then AI). Includes columns for
    completion_pct, via_count, trace_length_mm, drc_pass, parse_success.

    Args:
        results: List of StrategyEvalResult (may be empty).

    Returns:
        Markdown-formatted table string. Returns "No results." when empty.
    """
    if not results:
        return "No results."

    header = "| " + " | ".join(_TABLE_COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in _TABLE_COLUMNS) + " |"
    lines = [header, separator]

    # Group by fixture, deterministic first then AI.
    by_fixture: dict[str, list[StrategyEvalResult]] = {}
    for r in results:
        by_fixture.setdefault(r.fixture_name, []).append(r)

    for fixture_name in sorted(by_fixture.keys()):
        fixture_results = by_fixture[fixture_name]
        # Sort so DeterministicStrategy appears before AiRoutingStrategy.
        fixture_results.sort(key=lambda r: r.strategy_name)
        for r in fixture_results:
            lines.append(
                f"| {r.fixture_name} | {r.strategy_name} | "
                f"{r.completion_pct:.2%} | {r.via_count} | "
                f"{r.total_trace_length_mm:.2f} | "
                f"{'PASS' if r.drc_pass else 'FAIL'} | "
                f"{'yes' if r.parse_success else 'no'} |"
            )

    return "\n".join(lines)


def evaluate_sc1(results: list[StrategyEvalResult]) -> float:
    """SC-1: parse_success rate across all AI results.

    Threshold: >= 0.95 (CONTEXT.md success criterion 1).

    The denominator is all AI strategy results; the numerator is AI results
    where parse_success=True (i.e., the model produced parseable output and
    did NOT fall back to deterministic).

    Returns:
        Float in [0.0, 1.0]. Returns 0.0 when there are no AI results.
    """
    ai_results = [r for r in results if r.strategy_name == "AiRoutingStrategy"]
    if not ai_results:
        return 0.0
    successes = sum(1 for r in ai_results if r.parse_success)
    return successes / len(ai_results)


def evaluate_sc2(
    det: StrategyEvalResult, ai: StrategyEvalResult
) -> list[str]:
    """SC-2: metrics where AI matches or beats deterministic.

    Threshold: >= 2 of 3 metrics (CONTEXT.md success criterion 2).

    M-3 (Council): "matches or beats" means ties count as a win. Direction:
        - completion_pct: higher is better (ai >= det wins)
        - via_count: lower is better (ai <= det wins)
        - total_trace_length_mm: lower is better (ai <= det wins)

    Args:
        det: Deterministic strategy result for a single fixture.
        ai: AI strategy result for the same fixture.

    Returns:
        List of metric names where AI matches or beats deterministic.
        Possible values: "completion_pct", "via_count", "total_trace_length_mm".
        Empty when the AI result is a fallback (parse_success=False) — ties
        on identical metrics must not mask "model contributed nothing".
    """
    # ME-02 (Council): short-circuit on R-6 fallback. When the AI strategy
    # fell back to DeterministicStrategy, the AI result is byte-identical to
    # the deterministic baseline, so every metric is a tie. Counting those
    # ties as wins would mask a 100%-fallback run as a perfect SC-2 score.
    if not ai.parse_success:
        return []
    winners: list[str] = []
    if ai.completion_pct >= det.completion_pct:
        winners.append("completion_pct")
    if ai.via_count <= det.via_count:
        winners.append("via_count")
    if ai.total_trace_length_mm <= det.total_trace_length_mm:
        winners.append("total_trace_length_mm")
    return winners


def evaluate_sc3(
    det: StrategyEvalResult, ai: StrategyEvalResult
) -> bool:
    """SC-3: no DRC regression — AI drc_pass >= deterministic drc_pass.

    Threshold: True (CONTEXT.md success criterion 3). If the deterministic
    baseline routed a board cleanly (drc_pass=True), the AI strategy must
    also route it cleanly. If the baseline failed DRC, AI passing is not a
    regression.

    Args:
        det: Deterministic strategy result.
        ai: AI strategy result (same fixture).

    Returns:
        True if AI drc_pass >= deterministic drc_pass (no regression).
    """
    return ai.drc_pass >= det.drc_pass


def evaluate_sc5(results: list[StrategyEvalResult]) -> int:
    """SC-5: count distinct fixtures with at least one AI result.

    Threshold: >= 3 (CONTEXT.md success criterion 5 — end-to-end on >= 3
    fixtures).

    Returns:
        Integer count of distinct fixture_name values among AI results.
    """
    ai_fixtures = {
        r.fixture_name
        for r in results
        if r.strategy_name == "AiRoutingStrategy"
    }
    return len(ai_fixtures)


def _compute_fallback_rate(results: list[StrategyEvalResult]) -> float:
    """M-4 (Council): compute fallback_rate diagnostic.

    Fraction of AI results that fell back to deterministic (parse_success=False).
    Complements SC-1: SC-1 measures parse success, fallback_rate measures how
    often the orchestrator had to invoke the R-6 safety net.
    """
    ai_results = [r for r in results if r.strategy_name == "AiRoutingStrategy"]
    if not ai_results:
        return 0.0
    fallbacks = sum(1 for r in ai_results if not r.parse_success)
    return fallbacks / len(ai_results)


def _copy_fixture_to_tmp(fixture_path: Path, tmp_dir: Path) -> Path:
    """Copy a fixture PCB into a temp dir (T-98-03-01 tampering mitigation).

    The orchestrator mutates the PCB file in place. Running on the checked-in
    fixture would corrupt it. This function copies the fixture to a temp dir
    so the original is never touched.

    Args:
        fixture_path: Path to the checked-in fixture .kicad_pcb.
        tmp_dir: Temporary directory to copy into.

    Returns:
        Path to the copied PCB file inside tmp_dir.
    """
    dest = tmp_dir / fixture_path.name
    shutil.copy2(fixture_path, dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the Phase 98 eval harness.

    Flags:
        --fixtures: Comma-separated fixture names or "all" (default: all).
        --json: Emit machine-readable JSON instead of markdown table.
        --no-ai: Run deterministic baseline only (skip AI strategy).

    Returns:
        0 on success, non-zero on error (unknown fixture, all fixtures missing).
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fixtures",
        type=str,
        default="all",
        help="Comma-separated fixture names (e.g. 'smd_test_board,synthetic_4layer') "
             "or 'all'. Available: " + ", ".join(sorted(FIXTURES.keys())),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output (for CI / downstream tools).",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Run deterministic baseline only (skip AI strategy). Useful for "
             "CI environments without the 23.8 GB vision model.",
    )
    args = parser.parse_args(argv)

    # Resolve fixture list.
    if args.fixtures == "all":
        fixture_names = sorted(FIXTURES.keys())
    else:
        fixture_names = [n.strip() for n in args.fixtures.split(",") if n.strip()]

    unknown = [n for n in fixture_names if n not in FIXTURES]
    if unknown:
        print(
            f"ERROR: unknown fixture(s): {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(FIXTURES.keys()))}",
            file=sys.stderr,
        )
        return 1

    results: list[StrategyEvalResult] = []

    for name in fixture_names:
        fixture_path = FIXTURES[name]
        if not fixture_path.exists():
            print(f"WARNING: fixture {name} not found at {fixture_path}, skipping", file=sys.stderr)
            continue

        with tempfile.TemporaryDirectory(prefix=f"phase98_eval_{name}_") as tmp:
            tmp_dir = Path(tmp)
            project_dir = tmp_dir / "project"
            project_dir.mkdir(exist_ok=True)

            # Deterministic baseline (always runs).
            pcb_copy = _copy_fixture_to_tmp(fixture_path, tmp_dir)
            try:
                det_result = run_strategy_with_orchestrator(
                    DeterministicStrategy(),
                    pcb_path=pcb_copy,
                    project_dir=project_dir,
                    strategy_name="DeterministicStrategy",
                    drc_tag="det",
                )
                results.append(det_result)
            except Exception as exc:
                print(f"WARNING: deterministic strategy failed on {name}: {exc}", file=sys.stderr)

            # AI strategy (unless --no-ai).
            if not args.no_ai:
                pcb_copy_ai = _copy_fixture_to_tmp(fixture_path, tmp_dir)
                try:
                    ai_strategy = load_ai_strategy(pcb_copy_ai)
                    ai_result = run_strategy_with_orchestrator(
                        ai_strategy,
                        pcb_path=pcb_copy_ai,
                        project_dir=project_dir,
                        strategy_name="AiRoutingStrategy",
                        drc_tag="ai",
                    )
                    results.append(ai_result)
                except Exception as exc:
                    print(f"WARNING: AI strategy failed on {name}: {exc}", file=sys.stderr)

    if not results:
        print("ERROR: no results collected (all fixtures failed or missing).", file=sys.stderr)
        return 1

    # Compute SC evaluators.
    sc1 = evaluate_sc1(results)
    sc5 = evaluate_sc5(results)
    fallback_rate = _compute_fallback_rate(results)

    # SC-2 and SC-3 are per-fixture (need det + ai for same fixture).
    sc2_winners_per_fixture: dict[str, list[str]] = {}
    sc3_pass_per_fixture: dict[str, bool] = {}
    by_fixture: dict[str, list[StrategyEvalResult]] = {}
    for r in results:
        by_fixture.setdefault(r.fixture_name, []).append(r)
    for fixture_name, fixture_results in by_fixture.items():
        det = next((r for r in fixture_results if r.strategy_name == "DeterministicStrategy"), None)
        ai = next((r for r in fixture_results if r.strategy_name == "AiRoutingStrategy"), None)
        if det and ai:
            sc2_winners_per_fixture[fixture_name] = evaluate_sc2(det, ai)
            sc3_pass_per_fixture[fixture_name] = evaluate_sc3(det, ai)

    if args.json:
        payload = {
            "results": [asdict(r) for r in results],
            "sc1_parse_success_rate": round(sc1, 4),
            "sc2_winners_per_fixture": sc2_winners_per_fixture,
            "sc3_no_regression_per_fixture": sc3_pass_per_fixture,
            "sc5_distinct_fixtures": sc5,
            # M-4 (Council): fallback_rate diagnostic for interpreting SC-1.
            "fallback_rate": round(fallback_rate, 4),
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_comparison_table(results))
        print()
        print(f"SC-1 (parse_success rate): {sc1:.2%} (target: >=95%)")
        print(f"SC-5 (distinct AI fixtures): {sc5} (target: >=3)")
        print(f"fallback_rate: {fallback_rate:.2%}")
        for fixture_name, winners in sc2_winners_per_fixture.items():
            print(f"SC-2 ({fixture_name}): AI wins {len(winners)}/3 metrics: {winners}")
        for fixture_name, passed in sc3_pass_per_fixture.items():
            status = "PASS" if passed else "REGRESSION"
            print(f"SC-3 ({fixture_name}): {status}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
