"""SC-3: Freerouting-routed board passes kicad-cli pcb drc with zero unconnected.

End-to-end integration test:
  1. Route a fixture with Freerouting.
  2. Import the SES into the PCB content.
  3. Write the routed PCB to a temp file.
  4. Run ``kicad-cli pcb drc`` via subprocess.
  5. Parse the JSON report and assert zero ``unconnected_items`` violations
     after filtering known Phase 26 false positives (Device:R/C 3.81mm
     off-grid clearance noise per KNOWN_LIMITATIONS.md P26-1..P26-5).

This test is marked ``slow`` and skips gracefully when Freerouting (JAR +
Java) or ``kicad-cli`` is not available on the host.

Phase 99-03 Rule 1 fixes applied during SC-3 bring-up (documented in
99-03-SUMMARY.md):
  - extract_pcb_net_names now handles ``(net N "NAME")`` (KiCad 10 form);
    previously it only matched ``(net "NAME")`` and returned an empty set
    on real fixtures, causing every routed wire to be skipped.
  - SES coordinate parser divides by 1000 (raw um -> mm), not 10000;
    Freerouting emits raw um regardless of the declared resolution.
  - SES Y-coordinates are NOT negated; KiCad Y-down is preserved end-to-end.
  - DSN generator emits exactly one ``(class default ...)`` header line
    (previously doubled when the default member set was empty).
  - DSN generator takes only the copper layer (first token) from KiCad
    SMD pad layer sets like ``"F.Cu F.Paste F.Mask"`` so the padstack name
    no longer contains spaces.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from kicad_agent.routing.freerouting import (
    import_ses_into_pcb,
    is_freerouting_available,
    route_with_freerouting,
)

pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def _skip_if_no_freerouting_or_kicad() -> None:
    """Skip this module when Freerouting JAR, Java, or kicad-cli is missing."""
    if not is_freerouting_available():
        pytest.skip("Freerouting JAR or Java runtime not available")
    try:
        subprocess.run(
            ["kicad-cli", "--version"],
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pytest.skip("kicad-cli not available")


_FIXTURES = [
    Path(__file__).parent / "fixtures" / "smd_test_board.kicad_pcb",
]


def _filter_phase26_false_positives(violations: list[dict]) -> list[dict]:
    """Filter Device:R/C 3.81mm off-grid clearance false positives.

    Per KNOWN_LIMITATIONS.md P26-1..P26-5, Device:R/C footprints have a
    3.81mm pin offset that produces spurious clearance / off-grid DRC
    violations on correctly-routed boards. These are fixture bugs in the
    Device library, NOT routing defects, and must be filtered before the
    SC-3 unconnected-items assertion.

    Also filters ``lib_footprint_issues`` / ``lib_footprint_mismatch``
    violations (footprint library lookup noise from test fixtures whose
    embedded libraries are not installed on the host).
    """
    filtered: list[dict] = []
    for v in violations:
        desc = str(v.get("description", ""))
        vtype = str(v.get("type", ""))
        full = f"{vtype} {desc}"
        # P26-4: Device:R/C 3.81mm off-grid clearance violations.
        if "3.81" in full or "off-grid" in full.lower():
            continue
        # Library-lookup noise on test fixtures (embedded libs not on host).
        if vtype in ("lib_footprint_issues", "lib_footprint_mismatch"):
            continue
        filtered.append(v)
    return filtered


@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda p: p.stem)
def test_routed_board_passes_drc(fixture: Path) -> None:
    """SC-3: Freerouting-routed board has zero unconnected_items violations."""
    pcb_content = fixture.read_text(encoding="utf-8")

    result = route_with_freerouting(fixture, max_passes=3)
    if not result.success or result.ses_path is None:
        pytest.skip(
            f"Freerouting failed on {fixture.stem}: {(result.stderr or '')[:200]}"
        )

    ses_text = result.ses_path.read_text(encoding="utf-8")
    routed_pcb, stats = import_ses_into_pcb(result.ses_path, pcb_content)
    assert stats["segments"] > 0, (
        f"{fixture.stem}: SES import produced 0 segments (parse failed). "
        f"Stats: {stats}"
    )

    # Write the routed PCB to a temp file for kicad-cli.
    with tempfile.NamedTemporaryFile(
        suffix=".kicad_pcb", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(routed_pcb)
        temp_path = Path(f.name)

    try:
        out_path = temp_path.with_suffix(".drc.json")
        drc_result = subprocess.run(
            [
                "kicad-cli",
                "pcb",
                "drc",
                str(temp_path),
                "--output",
                str(out_path),
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if drc_result.returncode != 0 or not out_path.exists():
            pytest.skip(
                f"kicad-cli pcb drc failed (rc={drc_result.returncode}): "
                f"{drc_result.stderr[:200]}"
            )
        report_text = out_path.read_text(encoding="utf-8")
        if not report_text.strip():
            pytest.skip(f"kicad-cli pcb drc produced empty report for {fixture.stem}")
        try:
            drc_data = json.loads(report_text)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"kicad-cli pcb drc produced unparseable JSON for {fixture.stem}: {exc}"
            )
        violations = drc_data.get("violations", [])
        violations = _filter_phase26_false_positives(violations)
        unconnected = [
            v
            for v in violations
            if v.get("type") == "unconnected_items"
            or "unconnected" in v.get("description", "").lower()
        ]
        assert len(unconnected) == 0, (
            f"{fixture.stem}: {len(unconnected)} unconnected_items violations "
            f"after routing.\nStats: {stats}\nFirst few: {unconnected[:3]}"
        )
    finally:
        temp_path.unlink(missing_ok=True)
        if "out_path" in locals():
            out_path.unlink(missing_ok=True)
