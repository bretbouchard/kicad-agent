"""VAL-07: Round-trip fidelity regression test suite.

Comprehensive regression suite that validates all four KiCad file types
(.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod) against multiple
real-world sample files with varying complexity.

Tests two-pass stability (deterministic output) and UUID preservation
for PCB/footprint files.
"""

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"

# Synthetic test fixtures not suitable for roundtrip validation.
# smd_test_board is a minimal board for auto-routing unit tests — its element
# ordering differs from real KiCad output, causing UUID reinjector mismatches.
# phase99_synthetic_4layer is a hand-crafted DSN test fixture (Phase 99 R-3/R-4)
# with minimal structure — not a real KiCad-exported file.
_SKIP_FILES = {"smd_test_board.kicad_pcb", "phase99_synthetic_4layer_mixedsignal.kicad_pcb"}


# ---------------------------------------------------------------------------
# Test 1: run_regression_suite discovers all fixture files
# ---------------------------------------------------------------------------


def test_regression_suite_finds_all_fixture_files(tmp_path: Path) -> None:
    """run_regression_suite scans fixture_dir and finds all KiCad files."""
    from volta.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(FIXTURE_DIR, tmp_path, skip_files=_SKIP_FILES)

    # Must find at least: 2 schematics, 2 PCBs, 1 footprint, 1 symbol = 6 files
    assert result.total_files >= 5, (
        f"Expected at least 5 fixture files, found {result.total_files}"
    )


# ---------------------------------------------------------------------------
# Test 2: run_regression_suite returns all_passed=True
# ---------------------------------------------------------------------------


def test_regression_suite_all_passed(tmp_path: Path) -> None:
    """All fixture files pass the two-pass round-trip stability test."""
    from volta.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(FIXTURE_DIR, tmp_path, skip_files=_SKIP_FILES)

    assert result.all_passed is True, (
        f"Regression suite had {result.failed} failures out of {result.total_files} files"
    )


# ---------------------------------------------------------------------------
# Test 3: total_files count covers all four file types
# ---------------------------------------------------------------------------


def test_regression_suite_file_type_coverage(tmp_path: Path) -> None:
    """The suite covers schematics, PCBs, footprints, and symbol libraries."""
    from volta.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(FIXTURE_DIR, tmp_path, skip_files=_SKIP_FILES)

    file_types = {r.file_type for r in result.results}
    assert "schematic" in file_types, "No schematic files in regression suite"
    assert "pcb" in file_types, "No PCB files in regression suite"
    assert "footprint" in file_types, "No footprint files in regression suite"
    assert "symbol_lib" in file_types, "No symbol library files in regression suite"


# ---------------------------------------------------------------------------
# Test 4: Each individual file reports is_stable=True
# ---------------------------------------------------------------------------


def test_each_file_is_stable(tmp_path: Path) -> None:
    """Each file in the regression suite passes the two-pass stability test."""
    from volta.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(FIXTURE_DIR, tmp_path, skip_files=_SKIP_FILES)

    unstable = [r for r in result.results if not r.is_stable]
    assert len(unstable) == 0, (
        f"{len(unstable)} files failed stability: "
        + ", ".join(f"{r.file_path.name} ({r.error or 'not stable'})" for r in unstable)
    )


# ---------------------------------------------------------------------------
# Test 5: PCB files report uuid_preserved=True
# ---------------------------------------------------------------------------


def test_pcb_uuid_preserved(tmp_path: Path) -> None:
    """PCB regression tests report uuid_preserved=True."""
    from volta.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(FIXTURE_DIR, tmp_path, skip_files=_SKIP_FILES)

    pcb_results = [r for r in result.results if r.file_type == "pcb"]
    assert len(pcb_results) >= 2, "Need at least 2 PCB files for UUID test"

    for r in pcb_results:
        assert r.uuid_preserved is True, (
            f"UUID not preserved for {r.file_path.name}: "
            f"uuid_preserved={r.uuid_preserved}"
        )


# ---------------------------------------------------------------------------
# Test 6: Full regression suite (pytest exit code 0)
# This test runs the full suite and asserts comprehensive pass
# ---------------------------------------------------------------------------


def test_full_regression_suite(tmp_path: Path) -> None:
    """Full regression suite validates parse/serialize pipeline for all file types.

    This is the VAL-07 acceptance test: running the full suite with a single
    command validates the entire parse/serialize pipeline.
    """
    from volta.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(FIXTURE_DIR, tmp_path, skip_files=_SKIP_FILES)

    # All files must be stable
    assert result.all_passed is True
    # Must cover at least 5 files across all four types
    assert result.total_files >= 5
    # No errors
    errors = [r for r in result.results if r.error is not None]
    assert len(errors) == 0, (
        f"Errors in regression suite: "
        + "; ".join(f"{r.file_path.name}: {r.error}" for r in errors)
    )


# ---------------------------------------------------------------------------
# Per-file-type regression tests
# ---------------------------------------------------------------------------


def test_schematic_regression(tmp_path: Path) -> None:
    """Each .kicad_sch fixture passes round-trip stability."""
    from volta.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(FIXTURE_DIR, tmp_path, skip_files=_SKIP_FILES)

    sch_results = [r for r in result.results if r.file_type == "schematic"]
    assert len(sch_results) >= 2, "Need at least 2 schematic files"
    for r in sch_results:
        assert r.is_stable is True, f"Schematic {r.file_path.name} not stable"


def test_pcb_regression(tmp_path: Path) -> None:
    """Each .kicad_pcb fixture passes round-trip with UUID preservation."""
    from volta.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(FIXTURE_DIR, tmp_path, skip_files=_SKIP_FILES)

    pcb_results = [r for r in result.results if r.file_type == "pcb"]
    assert len(pcb_results) >= 2, "Need at least 2 PCB files"
    for r in pcb_results:
        assert r.is_stable is True, f"PCB {r.file_path.name} not stable"
        assert r.uuid_preserved is True, f"PCB {r.file_path.name} UUID not preserved"


def test_footprint_regression(tmp_path: Path) -> None:
    """Each .kicad_mod fixture passes round-trip stability."""
    from volta.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(FIXTURE_DIR, tmp_path, skip_files=_SKIP_FILES)

    mod_results = [r for r in result.results if r.file_type == "footprint"]
    assert len(mod_results) >= 1, "Need at least 1 footprint file"
    for r in mod_results:
        assert r.is_stable is True, f"Footprint {r.file_path.name} not stable"


def test_symbol_lib_regression(tmp_path: Path) -> None:
    """Each .kicad_sym fixture passes round-trip stability."""
    from volta.validation.roundtrip_regression import run_regression_suite

    result = run_regression_suite(FIXTURE_DIR, tmp_path, skip_files=_SKIP_FILES)

    sym_results = [r for r in result.results if r.file_type == "symbol_lib"]
    assert len(sym_results) >= 1, "Need at least 1 symbol library file"
    for r in sym_results:
        assert r.is_stable is True, f"Symbol lib {r.file_path.name} not stable"
