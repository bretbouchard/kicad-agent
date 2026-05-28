"""Tests for InferenceWrapper and generate_analysis."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.inference.best_of_n import ScoredChain


# ---------------------------------------------------------------------------
# _extract_board_stats
# ---------------------------------------------------------------------------


def test_extract_board_stats_pcb(tmp_path: Path) -> None:
    """_extract_board_stats returns BoardStats for .kicad_pcb file."""
    pcb_file = tmp_path / "test.kicad_pcb"
    pcb_file.write_text("(kicad_pcb (version 20221018) (generator pcbnew))")

    mock_board = MagicMock()
    mock_board.footprints = [MagicMock(), MagicMock(), MagicMock()]
    mock_board.nets = [MagicMock(), MagicMock()]

    # Wrap in ParseResult-like object
    mock_result = MagicMock()
    mock_result.kiutils_obj = mock_board
    mock_result.raw_content = "(kicad_pcb)"

    with patch("kicad_agent.parser.pcb_parser.parse_pcb", return_value=mock_result):
        from kicad_agent.inference.wrapper import InferenceWrapper

        stats = InferenceWrapper._extract_board_stats(pcb_file)

    assert stats.board_name == "test"
    assert stats.n_components == 3
    assert stats.n_nets == 2
    assert stats.file_path == str(pcb_file)


def test_extract_board_stats_sch(tmp_path: Path) -> None:
    """_extract_board_stats returns BoardStats for .kicad_sch file."""
    sch_file = tmp_path / "test.kicad_sch"
    sch_file.write_text("(kicad_sch (version 20230121))")

    mock_sch = MagicMock()
    mock_sch.get_components.return_value = [MagicMock(), MagicMock()]
    mock_sch.get_nets.return_value = [MagicMock()]

    # Wrap in ParseResult-like object
    mock_result = MagicMock()
    mock_result.kiutils_obj = mock_sch

    with patch("kicad_agent.parser.schematic_parser.parse_schematic", return_value=mock_result):
        from kicad_agent.inference.wrapper import InferenceWrapper

        stats = InferenceWrapper._extract_board_stats(sch_file)

    assert stats.board_name == "test"
    assert stats.n_components == 2
    assert stats.n_nets == 1


def test_extract_board_stats_invalid_extension(tmp_path: Path) -> None:
    """_extract_board_stats raises ValueError for non-KiCad extension."""
    bad_file = tmp_path / "test.txt"
    bad_file.write_text("not a kicad file")

    from kicad_agent.inference.wrapper import InferenceWrapper

    with pytest.raises(ValueError, match="Unsupported"):
        InferenceWrapper._extract_board_stats(bad_file)


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_contains_board_metadata() -> None:
    """_build_prompt produces ChatML messages with board name and dimensions."""
    from kicad_agent.inference.wrapper import BoardStats, InferenceWrapper

    stats = BoardStats(
        board_name="TestBoard",
        n_components=50,
        n_nets=30,
        n_layers=4,
        width_mm=100.0,
        height_mm=75.0,
        file_path="/path/to/board.kicad_pcb",
    )

    wrapper = MagicMock(spec=InferenceWrapper)
    wrapper._SYSTEM_PROMPT = InferenceWrapper._SYSTEM_PROMPT

    messages = InferenceWrapper._build_prompt(wrapper, stats)

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "PCB design expert" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "TestBoard" in messages[1]["content"]
    assert "50" in messages[1]["content"]
    assert "100.0" in messages[1]["content"]


# ---------------------------------------------------------------------------
# generate_analysis
# ---------------------------------------------------------------------------


def test_generate_analysis_returns_scored_chain(tmp_path: Path) -> None:
    """generate_analysis returns ScoredChain with chain_text and scores."""
    pcb_file = tmp_path / "test.kicad_pcb"
    pcb_file.write_text("(kicad_pcb (version 20221018))")

    mock_chain_text = "Observation: Board has components at <point 5.0,10.0>"

    with patch("kicad_agent.inference.wrapper.InferenceWrapper.analyze") as mock_analyze:
        mock_analyze.return_value = ScoredChain(
            chain_text=mock_chain_text,
            format_score=0.85,
            quality_score=0.72,
            accuracy_score=0.78,
            composite_score=(0.85 + 0.72 + 0.78) / 3.0,
            generation_time_s=1.5,
        )

        from kicad_agent.inference.wrapper import generate_analysis

        result = generate_analysis(str(pcb_file))

    assert isinstance(result, ScoredChain)
    assert result.chain_text == mock_chain_text
    assert result.composite_score > 0.0


def test_generate_analysis_file_not_found() -> None:
    """generate_analysis raises FileNotFoundError for missing file."""
    from kicad_agent.inference.wrapper import InferenceWrapper

    wrapper = InferenceWrapper.__new__(InferenceWrapper)
    wrapper._n_best = 4
    wrapper._llm_client = MagicMock()
    wrapper._reward_model = None

    with pytest.raises(FileNotFoundError):
        wrapper.analyze("/nonexistent/path.kicad_pcb")


def test_generate_analysis_invalid_extension(tmp_path: Path) -> None:
    """generate_analysis raises ValueError for non-KiCad file."""
    bad_file = tmp_path / "test.txt"
    bad_file.write_text("not a kicad file")

    from kicad_agent.inference.wrapper import InferenceWrapper

    wrapper = InferenceWrapper.__new__(InferenceWrapper)
    wrapper._n_best = 4
    wrapper._llm_client = MagicMock()
    wrapper._reward_model = None

    with pytest.raises(ValueError, match="Unsupported"):
        wrapper.analyze(str(bad_file))
