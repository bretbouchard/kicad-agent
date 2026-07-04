"""Unit tests for SFTLabeller (Plan 02 Task 1, D-02 SFT path)."""
from __future__ import annotations

import json
from dataclasses import is_dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_agent.training.sft_labeller import (
    LabellerStats,
    SFTLabeller,
    SFTLabellerError,
)


FIXTURE = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch")


def _make_corrupt_sch(tmp_path: Path) -> Path:
    """Write a fake .kicad_sch that will fail parsing.

    Uses an unbalanced paren to force kiutils to choke. A well-formed but
    empty S-expression would parse cleanly (kiutils is lenient).
    """
    bad = tmp_path / "corrupt.kicad_sch"
    bad.write_text("(kicad_sch (unbalanced", encoding="utf-8")
    return bad


def test_score_file_returns_six_key_dict_on_real_fixture() -> None:
    """Test 1: score_file on Arduino_Mega returns 6-key dict."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    labeller = SFTLabeller()
    score = labeller.score_file(FIXTURE)
    assert set(score.keys()) == {
        "density", "clarity", "spacing", "organization", "overall_srs", "element_count",
    }
    for k in ("density", "clarity", "spacing", "organization", "overall_srs"):
        v = score[k]
        assert isinstance(v, float), f"{k} should be float, got {type(v)}"
        assert 0.0 <= v <= 1.0, f"{k}={v} out of [0,1]"
    assert isinstance(score["element_count"], int)
    assert score["element_count"] >= 0


def test_score_file_nonexistent_raises_filenotfound() -> None:
    """Test 2: missing path raises FileNotFoundError."""
    labeller = SFTLabeller()
    with pytest.raises(FileNotFoundError):
        labeller.score_file(Path("/nonexistent/board.kicad_sch"))


def test_score_file_corrupt_raises_sft_labeller_error(tmp_path) -> None:
    """Test 3: corrupt schematic raises SFTLabellerError (no kiutils leak)."""
    bad = _make_corrupt_sch(tmp_path)
    labeller = SFTLabeller()
    with pytest.raises(SFTLabellerError, match="corrupt.kicad_sch"):
        labeller.score_file(bad)


def test_label_to_jsonl_round_trip(tmp_path) -> None:
    """Test 4: label_to_jsonl emits valid JSON with required fields."""
    labeller = SFTLabeller(source_tag="test-source")
    sch_path = tmp_path / "test.kicad_sch"
    sch_path.write_text("(kicad_sch)", encoding="utf-8")  # path exists; not parsed here
    score = {"density": 0.8, "clarity": 0.7, "spacing": 0.6, "organization": 0.5,
             "overall_srs": 0.65, "element_count": 12}
    row = labeller.label_to_jsonl(sch_path, score)
    parsed = json.loads(row)
    assert parsed["input_path"] == str(sch_path.resolve())
    assert parsed["labels"] == score
    assert parsed["source"] == "test-source"
    # scored_at should be ISO-8601 (contains 'T' and ends with timezone or 'Z')
    assert "T" in parsed["scored_at"]


def test_label_corpus_skips_corrupt_with_warning(tmp_path, caplog) -> None:
    """Test 5: corrupt schematic in corpus is skipped with warning, not raised."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    bad = _make_corrupt_sch(tmp_path)
    labeller = SFTLabeller()
    rows = labeller.label_corpus([FIXTURE, bad])
    # Only the good one is scored
    assert len(rows) == 1
    assert labeller.stats.n_scored == 1
    assert labeller.stats.n_skipped == 1


def test_label_corpus_tracks_stats() -> None:
    """Test 6: stats counters accurate."""
    labeller = SFTLabeller(stats=LabellerStats())
    # Empty corpus
    rows = labeller.label_corpus([])
    assert rows == []
    assert labeller.stats.n_scored == 0


def test_score_file_skips_oversized_files(tmp_path) -> None:
    """Test 7: files > max_file_mb are skipped with SFTLabellerError (ME-110-10)."""
    # Create a fake large file (just touch it; we won't actually parse it)
    big = tmp_path / "huge.kicad_sch"
    big.write_text("(kicad_sch)", encoding="utf-8")
    # Patch the size check by using max_file_mb=0 — anything > 0 bytes is too big
    labeller = SFTLabeller(max_file_mb=0)
    with pytest.raises(SFTLabellerError, match="max_file_mb"):
        labeller.score_file(big)


def test_overall_srs_sourced_from_readability_report_srs() -> None:
    """Test 8: overall_srs == ReadabilityReport.srs (NOT factors['overall'])."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    from kicad_agent.analysis.readability_scorer import SchematicReadabilityScorer
    from kicad_agent.analysis.schematic_spatial import SchematicSpatialExtractor
    from kicad_agent.ir.schematic_ir import SchematicIR
    from kicad_agent.parser.schematic_parser import parse_schematic

    parse_result = parse_schematic(FIXTURE)
    ir = SchematicIR(_parse_result=parse_result)
    extractor = SchematicSpatialExtractor(ir)
    expected_srs = SchematicReadabilityScorer(extractor).score().srs

    labeller = SFTLabeller()
    score = labeller.score_file(FIXTURE)
    assert score["overall_srs"] == pytest.approx(expected_srs)


def test_density_value_matches_readability_report_factors_density() -> None:
    """Test 9: density == ReadabilityReport.factors['density'] (verified chain)."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    from kicad_agent.analysis.readability_scorer import SchematicReadabilityScorer
    from kicad_agent.analysis.schematic_spatial import SchematicSpatialExtractor
    from kicad_agent.ir.schematic_ir import SchematicIR
    from kicad_agent.parser.schematic_parser import parse_schematic

    parse_result = parse_schematic(FIXTURE)
    ir = SchematicIR(_parse_result=parse_result)
    extractor = SchematicSpatialExtractor(ir)
    expected_density = SchematicReadabilityScorer(extractor).score().factors["density"]

    # Re-parse since the extractor above consumed the IR
    parse_result = parse_schematic(FIXTURE)
    ir = SchematicIR(_parse_result=parse_result)
    extractor = SchematicSpatialExtractor(ir)

    labeller = SFTLabeller()
    score = labeller.score_file(FIXTURE)
    assert score["density"] == pytest.approx(expected_density)


def test_sft_labeller_is_frozen_dataclass() -> None:
    """Phase 100 CR-01: SFTLabeller is frozen."""
    assert is_dataclass(SFTLabeller)
    labeller = SFTLabeller()
    with pytest.raises(Exception):
        labeller.source_tag = "mutated"  # type: ignore[misc]
