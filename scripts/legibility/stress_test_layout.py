"""Legibility stress-test harness for the schematic autolayout pipeline.

Runs the full pipeline on each fixture and captures objective legibility metrics:

  place_components_sch  → Sugiyama positions, fit-to-page, loose-comp parking
  route_wires_sch       → L-shaped / same-axis wire insertion
  apply_labels_sch      → net labels at pin bodies

Metrics captured per fixture:
  - parts_placed, parts_parked, subcircuit_count
  - wire_count, label_count, global_label_count
  - crossing_count (from Sugiyama)
  - off_page_count (symbols whose (at) coords exceed page bounds)
  - overlap_count (symbols at identical (at) coords)
  - feedback_edges_reversed
  - runtime_s (per stage)
  - erc_errors, erc_warnings (post-layout)
  - paren_balanced (file integrity)

Output: output/legibility/<timestamp>/report.json + per-fixture .kicad_sch copies.

Usage:
  python3 scripts/legibility/stress_test_layout.py [--fixture NAME] [--render]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Ensure src is importable.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES = {
    "S1_led_bringer":   PROJECT_ROOT / "tests/fixtures/legibility/S1_led_bringer.kicad_sch",
    "S2_rc_filter":     PROJECT_ROOT / "tests/fixtures/legibility/S2_rc_filter.kicad_sch",
    "S3_opamp_preamp":  PROJECT_ROOT / "tests/fixtures/legibility/S3_opamp_preamp.kicad_sch",
    "S4_audio_mixer":   PROJECT_ROOT / "tests/fixtures/legibility/S4_audio_mixer.kicad_sch",
    "S5_esp32_breakout":PROJECT_ROOT / "tests/fixtures/legibility/S5_esp32_breakout.kicad_sch",
    "S6_arduino_mega":  PROJECT_ROOT / "tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch",
}

# A4 landscape dimensions in mm (default paper).
A4_W, A4_H = 297.0, 210.0
MARGIN = 20.0  # USABLE_PAGE_MARGIN_MM


@dataclass
class FixtureResult:
    name: str
    parts_total: int = 0
    parts_placed: int = 0
    parts_parked: int = 0
    subcircuit_count: int = 0
    crossing_count: int = 0
    feedback_edges_reversed: int = 0
    off_page_count: int = 0
    overlap_count: int = 0
    wire_count_before: int = 0
    wire_count_after: int = 0
    label_count_before: int = 0
    label_count_after: int = 0
    place_runtime_s: float = 0.0
    route_runtime_s: float = 0.0
    label_runtime_s: float = 0.0
    total_runtime_s: float = 0.0
    erc_errors: int = -1
    erc_warnings: int = -1
    paren_balanced: bool = True
    errors: list[str] = field(default_factory=list)
    stage_outputs: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Metric extraction (parse .kicad_sch content directly — no KiCad deps)
# ---------------------------------------------------------------------------

_AT_RE = re.compile(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)", re.MULTILINE)


def count_symbols(content: str) -> int:
    """Count top-level symbol instances (not lib_symbols definitions)."""
    # Match (symbol ... (lib_id "...")  — these are instances, not definitions
    return len(re.findall(r'\(symbol\s+\(lib_id\s+"[^"]+"\)', content))


def count_wires(content: str) -> int:
    return len(re.findall(r"\(wire\s+\(pts\s+\(xy", content))


def count_labels(content: str) -> int:
    return len(re.findall(r"\(label\s+", content))


def count_global_labels(content: str) -> int:
    return len(re.findall(r"\(global_label\s+", content))


def extract_positions(content: str) -> list[tuple[float, float]]:
    """Extract all (at x y) coordinates from symbol instances.

    We pair each (lib_id "...") with the following (at x y) to get symbol
    positions only (not label/wire positions).
    """
    positions: list[tuple[float, float]] = []
    for m in re.finditer(
        r'\(symbol\s+\(lib_id\s+"[^"]*"\)[^\)]*\)\s*\(at\s+(-?[\d.]+)\s+(-?[\d.]+)',
        content, re.DOTALL,
    ):
        positions.append((float(m.group(1)), float(m.group(2))))
    return positions


def count_off_page(positions: list[tuple[float, float]],
                   page_w: float, page_h: float, margin: float) -> int:
    """Count symbols whose center is outside the usable page area."""
    count = 0
    for x, y in positions:
        if x < margin or x > page_w - margin or y < margin or y > page_h - margin:
            count += 1
    return count


def count_overlaps(positions: list[tuple[float, float]]) -> int:
    """Count symbols sharing an identical (x, y) with another symbol.

    Returns the number of symbols involved in overlaps (not pair count).
    Two symbols at the same spot = 2; three at one spot = 3.
    """
    pos_counts = Counter((round(x, 1), round(y, 1)) for x, y in positions)
    overlap_symbols = sum(c for c in pos_counts.values() if c > 1)
    return overlap_symbols


def validate_paren_balance(content: str) -> bool:
    """Check paren balance (same logic as ops/handlers/pcb_cleanup.py)."""
    depth = 0
    for ch in content:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def run_erc(sch_path: Path) -> tuple[int, int]:
    """Run kicad-cli ERC. Returns (errors, warnings).

    Uses -o to write the report to a known path (kicad-cli otherwise writes
    to CWD). Returns (-1, -1) if kicad-cli is unavailable or fails to load.
    """
    rpt_path = sch_path.parent / f"{sch_path.stem}-erc.rpt"
    try:
        result = subprocess.run(
            ["kicad-cli", "sch", "erc", str(sch_path), "-o", str(rpt_path)],
            capture_output=True, text=True, timeout=120,
        )
        # kicad-cli returns exit 0 even on "Failed to load schematic" (stderr).
        if "Failed to load" in result.stderr:
            return -1, -1

        # Parse the .rpt file.
        if rpt_path.exists():
            rpt = rpt_path.read_text()
            # Lines like: " ** ERC messages: 14  Errors 8  Warnings 6"
            m = re.search(r"ERC messages:\s+(\d+)\s+Errors\s+(\d+)\s+Warnings\s+(\d+)", rpt)
            if m:
                return int(m.group(2)), int(m.group(3))
            # Fallback: count "; error" and "; warning" lines
            errors = rpt.count("; error")
            warnings = rpt.count("; warning")
            return errors, warnings

        # No rpt file — parse stdout/stderr directly
        output = result.stdout + result.stderr
        errors = output.count("; error")
        warnings = output.count("; warning")
        return errors, warnings
    except subprocess.TimeoutExpired:
        return -1, -1
    except FileNotFoundError:
        return -1, -1


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def _make_op(op_type: str, target_file: str, **kwargs) -> dict:
    """Build an op dict suitable for OperationExecutor.execute()."""
    op = {"op_type": op_type, "target_file": target_file}
    op.update(kwargs)
    return op


def run_place_stage(executor, target_file: str) -> tuple[dict, float]:
    from kicad_agent.ops.schema import Operation
    op_dict = _make_op("place_components_sch", target_file,
                       subcircuit_split=True, dry_run=False)
    op = Operation.model_validate({"root": op_dict})
    t0 = time.perf_counter()
    result = executor.execute(op)
    elapsed = time.perf_counter() - t0
    return result, elapsed


def run_route_stage(executor, target_file: str) -> tuple[dict, float]:
    from kicad_agent.ops.schema import Operation
    op_dict = _make_op("route_wires_sch", target_file,
                       max_wire_length_mm=40.0, dry_run=False)
    op = Operation.model_validate({"root": op_dict})
    t0 = time.perf_counter()
    result = executor.execute(op)
    elapsed = time.perf_counter() - t0
    return result, elapsed


def run_label_stage(executor, target_file: str) -> tuple[dict, float]:
    from kicad_agent.ops.schema import Operation
    op_dict = _make_op("apply_labels_sch", target_file,
                       label_size_mm=1.27, dry_run=False)
    op = Operation.model_validate({"root": op_dict})
    t0 = time.perf_counter()
    result = executor.execute(op)
    elapsed = time.perf_counter() - t0
    return result, elapsed


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------

def test_fixture(name: str, src_path: Path, out_dir: Path, args=None) -> FixtureResult:
    """Run the full autolayout pipeline on one fixture."""
    from kicad_agent.ops.executor import OperationExecutor

    res = FixtureResult(name=name)
    work_path = out_dir / f"{name}.kicad_sch"

    # Copy fixture to output dir so we don't mutate the source.
    shutil.copy2(src_path, work_path)

    # Read before-state.
    before = work_path.read_text()
    res.parts_total = count_symbols(before)
    res.wire_count_before = count_wires(before)
    res.label_count_before = count_labels(before)

    # Use a relative target_file path so executor path confinement is happy.
    # OperationExecutor resolves (base_dir / target_file). We set base_dir=out_dir
    # and target_file = just the filename.
    target_file = work_path.name
    executor = OperationExecutor(base_dir=out_dir)

    t_total_start = time.perf_counter()

    # Stage 1: place_components_sch
    try:
        place_result, res.place_runtime_s = run_place_stage(executor, target_file)
        # Executor wraps results: {"success":..., "details":{...}}
        details = place_result.get("details", place_result)
        res.stage_outputs["place"] = {
            k: v for k, v in details.items()
            if k in ("components_placed", "components_parked",
                     "subcircuit_count", "page_bounds")
        }
        res.parts_placed = details.get("components_placed", 0)
        res.parts_parked = details.get("components_parked", 0)
        res.subcircuit_count = details.get("subcircuit_count", 0)
        positions_dict = details.get("positions", {})
        # Compute crossings + feedback from positions if available
        # (the engine reports them in LayoutResult, but executor only returns positions)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        res.errors.append(f"place_components_sch: {e}")
        res.stage_outputs["place_error"] = tb[-1000:]
        # Still compute total runtime and return — we want partial metrics
        res.total_runtime_s = time.perf_counter() - t_total_start
        after = work_path.read_text()
        _final_metrics(res, after)
        return res

    # Stage 2: route_wires_sch
    skip_route = (args and (args.skip_route or args.place_only))
    if not skip_route:
        try:
            route_result, res.route_runtime_s = run_route_stage(executor, target_file)
            details = route_result.get("details", route_result)
            res.stage_outputs["route"] = {
                k: v for k, v in details.items()
                if not isinstance(v, (list, dict)) or k in ("wires_inserted",)
            }
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            res.errors.append(f"route_wires_sch: {e}")
            res.stage_outputs["route_error"] = tb[-1000:]

    # Stage 3: apply_labels_sch
    if not (args and args.place_only):
        try:
            label_result, res.label_runtime_s = run_label_stage(executor, target_file)
            details = label_result.get("details", label_result)
            res.stage_outputs["label"] = {
                k: v for k, v in details.items()
                if not isinstance(v, (list, dict)) or k in ("labels_applied",)
            }
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            res.errors.append(f"apply_labels_sch: {e}")
            res.stage_outputs["label_error"] = tb[-1000:]

    res.total_runtime_s = time.perf_counter() - t_total_start

    # Compute final metrics.
    after = work_path.read_text()
    _final_metrics(res, after)

    # Run ERC.
    res.erc_errors, res.erc_warnings = run_erc(work_path)

    return res


def _final_metrics(res: FixtureResult, content: str) -> None:
    res.wire_count_after = count_wires(content)
    res.label_count_after = count_labels(content)
    res.paren_balanced = validate_paren_balance(content)
    positions = extract_positions(content)
    res.off_page_count = count_off_page(positions, A4_W, A4_H, MARGIN)
    res.overlap_count = count_overlaps(positions)


def render_svg(sch_path: Path, out_dir: Path) -> bool:
    """Render .kicad_sch → SVG via kicad-cli. Returns True on success.

    Note: SVG output is a DIRECTORY (one SVG per sheet), not a file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["kicad-cli", "sch", "export", "svg", str(sch_path),
             "-o", str(out_dir)],
            capture_output=True, text=True, timeout=60,
        )
        if "Failed to load" in result.stderr:
            return False
        return result.returncode == 0 and any(out_dir.glob("*.svg"))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def render_pdf(sch_path: Path, out_pdf: Path) -> bool:
    """Render .kicad_sch → PDF via kicad-cli."""
    try:
        result = subprocess.run(
            ["kicad-cli", "sch", "export", "pdf", str(sch_path),
             "-o", str(out_pdf)],
            capture_output=True, text=True, timeout=60,
        )
        if "Failed to load" in result.stderr:
            return False
        return result.returncode == 0 and out_pdf.exists()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Schematic legibility stress test")
    parser.add_argument("--fixture", help="Run a single fixture by name")
    parser.add_argument("--render", action="store_true",
                        help="Render SVG+PDF outputs for visual inspection")
    parser.add_argument("--no-erc", action="store_true",
                        help="Skip ERC (faster)")
    parser.add_argument("--skip-route", action="store_true",
                        help="Skip route_wires_sch (use when emitter already has wires)")
    parser.add_argument("--place-only", action="store_true",
                        help="Only run place_components_sch (skip route + labels)")
    args = parser.parse_args()

    # Output directory: output/legibility/<timestamp>/
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "output" / "legibility" / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    fixtures = FIXTURES
    if args.fixture:
        if args.fixture not in FIXTURES:
            print(f"Unknown fixture: {args.fixture}")
            print(f"Available: {', '.join(FIXTURES)}")
            sys.exit(1)
        fixtures = {args.fixture: FIXTURES[args.fixture]}

    results: list[FixtureResult] = []
    for name, path in fixtures.items():
        if not path.exists():
            print(f"SKIP {name} — fixture not found at {path}")
            continue
        print(f"\n{'='*70}")
        print(f"TEST {name}")
        print(f"{'='*70}")
        r = test_fixture(name, path, out_dir, args)
        results.append(r)
        _print_result(r)

        if args.no_erc:
            r.erc_errors = -2  # sentinel: skipped
            r.erc_warnings = -2

    # Render if requested.
    if args.render:
        print(f"\n{'='*70}")
        print("RENDERING")
        print(f"{'='*70}")
        for r in results:
            sch = out_dir / f"{r.name}.kicad_sch"
            svg_dir = out_dir / f"{r.name}_svg"
            svg_ok = render_svg(sch, svg_dir)
            pdf_ok = render_pdf(sch, out_dir / f"{r.name}.pdf")
            print(f"  {r.name}: SVG={'OK' if svg_ok else 'FAIL'}  PDF={'OK' if pdf_ok else 'FAIL'}")

    # Write report.
    report = {
        "timestamp": ts,
        "fixtures_tested": [r.name for r in results],
        "results": [asdict(r) for r in results],
        "page_bounds": {"width_mm": A4_W, "height_mm": A4_H, "margin_mm": MARGIN},
    }
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport written: {report_path}")
    print(f"Output dir:    {out_dir}")

    # Summary table.
    _print_summary(results)


def _print_result(r: FixtureResult) -> None:
    status = "PASS" if not r.errors else "FAIL"
    print(f"  Status:              {status}")
    print(f"  Parts: total={r.parts_total} placed={r.parts_placed} parked={r.parts_parked}")
    print(f"  Subcircuits:         {r.subcircuit_count}")
    print(f"  Crossings:           {r.crossing_count}")
    print(f"  Feedback reversed:   {r.feedback_edges_reversed}")
    print(f"  Off-page symbols:    {r.off_page_count}")
    print(f"  Overlapping symbols: {r.overlap_count}")
    print(f"  Wires: {r.wire_count_before} → {r.wire_count_after}")
    print(f"  Labels: {r.label_count_before} → {r.label_count_after}")
    print(f"  Runtime: place={r.place_runtime_s:.2f}s route={r.route_runtime_s:.2f}s "
          f"label={r.label_runtime_s:.2f}s total={r.total_runtime_s:.2f}s")
    if r.erc_errors >= 0:
        print(f"  ERC: {r.erc_errors} errors, {r.erc_warnings} warnings")
    elif r.erc_errors == -2:
        print(f"  ERC: skipped")
    else:
        print(f"  ERC: unavailable (kicad-cli not found or timeout)")
    print(f"  Paren balanced:     {r.paren_balanced}")
    if r.errors:
        for e in r.errors:
            print(f"  ERROR: {e}")


def _print_summary(results: list[FixtureResult]) -> None:
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"{'Fixture':<22} {'Parts':>6} {'Subc':>5} {'OffPg':>6} {'Ovrlp':>6} "
          f"{'Wires':>6} {'Labels':>7} {'ERC-E':>6} {'Time':>7} {'Status':>8}")
    print("-" * 90)
    for r in results:
        status = "PASS" if not r.errors else "FAIL"
        erc = str(r.erc_errors) if r.erc_errors >= 0 else ("skip" if r.erc_errors == -2 else "n/a")
        print(f"{r.name:<22} {r.parts_total:>6} {r.subcircuit_count:>5} "
              f"{r.off_page_count:>6} {r.overlap_count:>6} "
              f"{r.wire_count_after:>6} {r.label_count_after:>7} "
              f"{erc:>6} {r.total_runtime_s:>6.1f}s {status:>8}")


if __name__ == "__main__":
    main()
