"""Tests for StripShortsOp and RemoveDanglingTracksOp schemas (TDD RED phase).

Tests will FAIL until schemas are implemented.
"""

import pytest
from pydantic import ValidationError

from volta.ops._schema_gap import StripShortsOp, RemoveDanglingTracksOp


# ---------------------------------------------------------------------------
# StripShortsOp — valid cases
# ---------------------------------------------------------------------------

class TestStripShortsOpValid:
    def test_defaults(self):
        s = StripShortsOp(target_file="test.kicad_pcb")
        assert s.op_type == "strip_shorts"
        assert s.tolerance_mm == 0.01
        assert s.drc_report is None

    def test_custom_tolerance(self):
        s = StripShortsOp(target_file="test.kicad_pcb", tolerance_mm=0.005)
        assert s.tolerance_mm == 0.005

    def test_with_drc_report(self):
        s = StripShortsOp(target_file="test.kicad_pcb", drc_report="board-drc.rpt")
        assert s.drc_report == "board-drc.rpt"

    def test_json_round_trip(self):
        s = StripShortsOp(target_file="test.kicad_pcb", tolerance_mm=0.02)
        data = s.model_dump()
        s2 = StripShortsOp.model_validate(data)
        assert s2.tolerance_mm == 0.02
        assert s2.op_type == "strip_shorts"


# ---------------------------------------------------------------------------
# StripShortsOp — invalid cases
# ---------------------------------------------------------------------------

class TestStripShortsOpInvalid:
    def test_tolerance_zero(self):
        with pytest.raises(ValidationError):
            StripShortsOp(target_file="test.kicad_pcb", tolerance_mm=0)

    def test_tolerance_negative(self):
        with pytest.raises(ValidationError):
            StripShortsOp(target_file="test.kicad_pcb", tolerance_mm=-0.01)

    def test_tolerance_too_large(self):
        with pytest.raises(ValidationError):
            StripShortsOp(target_file="test.kicad_pcb", tolerance_mm=2.0)

    def test_drc_report_empty_string(self):
        """Empty string is not a valid file path."""
        with pytest.raises(ValidationError):
            StripShortsOp(target_file="test.kicad_pcb", drc_report="")

    def test_target_file_invalid_extension(self):
        with pytest.raises(ValidationError):
            StripShortsOp(target_file="test.txt")


# ---------------------------------------------------------------------------
# RemoveDanglingTracksOp — valid cases
# ---------------------------------------------------------------------------

class TestRemoveDanglingTracksOpValid:
    def test_defaults(self):
        r = RemoveDanglingTracksOp(target_file="test.kicad_pcb")
        assert r.op_type == "remove_dangling_tracks"
        assert r.max_iterations == 30
        assert r.tolerance_mm == 0.001

    def test_custom_max_iterations(self):
        r = RemoveDanglingTracksOp(target_file="test.kicad_pcb", max_iterations=10)
        assert r.max_iterations == 10

    def test_custom_tolerance(self):
        r = RemoveDanglingTracksOp(target_file="test.kicad_pcb", tolerance_mm=0.01)
        assert r.tolerance_mm == 0.01

    def test_json_round_trip(self):
        r = RemoveDanglingTracksOp(target_file="test.kicad_pcb", max_iterations=5)
        data = r.model_dump()
        r2 = RemoveDanglingTracksOp.model_validate(data)
        assert r2.max_iterations == 5
        assert r2.op_type == "remove_dangling_tracks"


# ---------------------------------------------------------------------------
# RemoveDanglingTracksOp — invalid cases
# ---------------------------------------------------------------------------

class TestRemoveDanglingTracksOpInvalid:
    def test_max_iterations_zero(self):
        with pytest.raises(ValidationError):
            RemoveDanglingTracksOp(target_file="test.kicad_pcb", max_iterations=0)

    def test_max_iterations_too_large(self):
        with pytest.raises(ValidationError):
            RemoveDanglingTracksOp(target_file="test.kicad_pcb", max_iterations=200)

    def test_tolerance_zero(self):
        with pytest.raises(ValidationError):
            RemoveDanglingTracksOp(target_file="test.kicad_pcb", tolerance_mm=0)

    def test_tolerance_too_large(self):
        with pytest.raises(ValidationError):
            RemoveDanglingTracksOp(target_file="test.kicad_pcb", tolerance_mm=5.0)

    def test_target_file_invalid_extension(self):
        with pytest.raises(ValidationError):
            RemoveDanglingTracksOp(target_file="notes.md")
