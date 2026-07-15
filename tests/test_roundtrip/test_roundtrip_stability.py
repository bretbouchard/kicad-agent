"""Round-trip stability tests for all four KiCad file types (FND-05, VAL-07).

Tests the two-pass stability strategy:
1. Parse original -> serialize -> pass1 output
2. Parse pass1 -> serialize -> pass2 output
3. Compare pass1 == pass2 (byte-identical after first normalization)

This proves kiutils output stabilizes after the first pass. UUIDs are preserved
for PCB and footprint files via the extraction/re-injection layer.
"""

import re
from pathlib import Path

import pytest

from volta.parser.uuid_extractor import extract_uuids
from volta.validation.roundtrip import round_trip_stable, round_trip_compare


class TestRoundTripStability:
    """Two-pass round-trip stability for all four file types."""

    def test_schematic_round_trip(
        self, arduino_mega_sch: Path, tmp_output_dir: Path
    ) -> None:
        """Test 1: Schematic round-trip is stable (pass1 == pass2)."""
        assert round_trip_stable(arduino_mega_sch, tmp_output_dir)

    def test_pcb_round_trip(
        self, arduino_mega_pcb: Path, tmp_output_dir: Path
    ) -> None:
        """Test 2: PCB round-trip is stable with UUID preservation."""
        assert round_trip_stable(arduino_mega_pcb, tmp_output_dir)

    def test_footprint_round_trip(
        self, arduino_mounting_hole_mod: Path, tmp_output_dir: Path
    ) -> None:
        """Test 3: Footprint round-trip is stable with UUID preservation."""
        assert round_trip_stable(arduino_mounting_hole_mod, tmp_output_dir)

    def test_symbol_lib_round_trip(
        self, sample_sym_lib: Path, tmp_output_dir: Path
    ) -> None:
        """Test 4: Symbol library round-trip is stable."""
        assert round_trip_stable(sample_sym_lib, tmp_output_dir)


class TestRoundTripDetails:
    """Detailed round-trip result verification."""

    def test_pcb_uuid_preservation(
        self, arduino_mega_pcb: Path, tmp_output_dir: Path
    ) -> None:
        """Test 7: PCB round-trip preserves UUID count from original."""
        result = round_trip_compare(arduino_mega_pcb, tmp_output_dir)
        assert result.is_stable, f"PCB not stable: {result.error}"
        assert result.uuid_preserved is True

    def test_round_trip_compare_returns_result(
        self, arduino_mega_sch: Path, tmp_output_dir: Path
    ) -> None:
        """Test 5: round_trip_compare returns RoundTripResult with is_stable=True."""
        result = round_trip_compare(arduino_mega_sch, tmp_output_dir)
        assert result.is_stable
        assert result.pass1_path is not None
        assert result.pass2_path is not None
        assert result.pass1_path.exists()
        assert result.pass2_path.exists()
        assert result.file_type == "schematic"

    def test_round_trip_compare_nonzero_sizes(
        self, arduino_mega_sch: Path, tmp_output_dir: Path
    ) -> None:
        """Test 6: Both pass1 and pass2 files have non-zero size."""
        result = round_trip_compare(arduino_mega_sch, tmp_output_dir)
        assert result.is_stable
        assert result.pass1_path.stat().st_size > 0
        assert result.pass2_path.stat().st_size > 0
