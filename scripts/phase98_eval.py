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

from kicad_agent.routing.orchestrator import (
    RoutingOrchestrationResult,
    RoutingOrchestrator,
)
from kicad_agent.routing.strategy import DeterministicStrategy

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
    model_output_chars: int
    parse_success: bool
    validation_passed: bool


def run_strategy_with_orchestrator(
    strategy: Any,
    pcb_path: Path,
    project_dir: Path,
    strategy_name: str,
    *,
    model_output_chars: int = 0,
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
        model_output_chars: For AI strategy, length of raw model output.
            Used as a diagnostic. Defaults to 0 for deterministic.

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

    drc_pass, drc_unconnected = run_drc(pcb_path)

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
        model_output_chars=model_output_chars,
        parse_success=parse_success,
        validation_passed=validation_passed,
    )


def run_drc(pcb_path: Path) -> tuple[bool, int]:
    """Run kicad-cli pcb drc on a PCB file.

    Returns:
        (drc_pass, unconnected_count). On any failure (kicad-cli missing,
        timeout, malformed report), returns (False, -1) sentinel so the
        eval harness continues without crashing.

    Threat T-98-03-02: best-effort. DRC must never crash the eval harness.
    """
    out_path = pcb_path.with_suffix(".drc.json")
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
    from kicad_agent.inference.vision_pipeline import (
        KiCadVisionConfig,
        KiCadVisionPipeline,
    )
    from kicad_agent.routing.ai_strategy import AiRoutingStrategy

    if not _ADAPTER_PATH.exists():
        raise FileNotFoundError(
            f"Vision adapter not found at {_ADAPTER_PATH}. "
            "Set the adapter path or retrain the model."
        )

    config = KiCadVisionConfig(adapter_path=_ADAPTER_PATH)
    pipeline = KiCadVisionPipeline(config)
    return AiRoutingStrategy(pipeline, pcb_path)


# ---------------------------------------------------------------------------
# CLI + comparison table + SC evaluators are added in Task 2.
# Stub main so the module is importable without the full CLI.
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Implemented in Task 2."""
    raise NotImplementedError("CLI is implemented in Task 2")


if __name__ == "__main__":
    sys.exit(main())
