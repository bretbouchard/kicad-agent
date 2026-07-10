"""Tests for read_board_metadata, set_board_metadata, set_board_revision ops (META-01..03, META-06)."""
import pytest
from pathlib import Path

from kicad_agent.ops._schema_pcb import (
    ReadBoardMetadataOp,
    SetBoardMetadataOp,
    SetBoardRevisionOp,
)


@pytest.fixture(autouse=True)
def _clear_ir_registry():
    from kicad_agent.ir.base import _clear_registry
    _clear_registry()
    yield
    _clear_registry()


def _create_pcb_with_title_block(tmpdir: Path) -> Path:
    """Create a minimal PCB with a full title_block for testing."""
    pcb_path = tmpdir / "test_meta.kicad_pcb"
    content = '''(kicad_pcb (version 20241229) (generator "test")
  (general (thickness 1.6) (layers 2))
  (paper "A4")
  (title_block
    (title "Old Title")
    (date "2020-01-01")
    (rev "1.0")
    (company "Old Co")
  )
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
  )
)
'''
    pcb_path.write_text(content, encoding="utf-8")
    return pcb_path


def _build_ir(pcb_path: Path):
    """Parse PCB and build PcbIR (mimics executor setup)."""
    from kicad_agent.parser.pcb_parser import parse_pcb
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.parser.uuid_extractor import extract_uuids
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)


def test_read_board_metadata_full(tmp_path):
    """read_board_metadata returns all title_block fields (META-01)."""
    from kicad_agent.ops.handlers.query import _QUERY_HANDLERS
    pcb_path = _create_pcb_with_title_block(tmp_path)
    ir = _build_ir(pcb_path)
    handler = _QUERY_HANDLERS["read_board_metadata"]
    result = handler(ReadBoardMetadataOp(target_file="test_meta.kicad_pcb"), ir, pcb_path)
    assert result["title"] == "Old Title"
    assert result["date"] == "2020-01-01"
    assert result["rev"] == "1.0"
    assert result["company"] == "Old Co"
    assert result["board_spec"] is None  # no sidecar


def test_read_board_metadata_no_title_block(tmp_path):
    """read_board_metadata on a board with no title_block returns empty fields."""
    from kicad_agent.ops.handlers.query import _QUERY_HANDLERS
    pcb_path = tmp_path / "notb.kicad_pcb"
    pcb_path.write_text('(kicad_pcb (version 20241229) (generator "test") (paper "A4") (layers (0 "F.Cu" signal)))', encoding="utf-8")
    ir = _build_ir(pcb_path)
    handler = _QUERY_HANDLERS["read_board_metadata"]
    result = handler(ReadBoardMetadataOp(target_file="notb.kicad_pcb"), ir, pcb_path)
    assert result["title"] == ""
    assert result["rev"] == ""


def test_set_board_revision_round_trip(tmp_path):
    """set_board_revision writes rev; re-read returns new rev (META-02, META-06)."""
    from kicad_agent.ops.handlers.pcb import _PCB_HANDLERS
    from kicad_agent.ops.handlers.query import _QUERY_HANDLERS
    pcb_path = _create_pcb_with_title_block(tmp_path)
    ir = _build_ir(pcb_path)
    # Set revision
    handler = _PCB_HANDLERS["set_board_revision"]
    result = handler(SetBoardRevisionOp(rev="2.1", target_file="test_meta.kicad_pcb"), ir, pcb_path)
    assert result["rev"] == "2.1"
    # Re-read from ir (raw_content was committed in-memory)
    read_handler = _QUERY_HANDLERS["read_board_metadata"]
    re_read = read_handler(ReadBoardMetadataOp(target_file="test_meta.kicad_pcb"), ir, pcb_path)
    assert re_read["rev"] == "2.1"
    assert re_read["title"] == "Old Title"  # partial update preserves other fields


def test_set_board_metadata_partial_update(tmp_path):
    """set_board_metadata partial update changes only provided fields (META-03)."""
    from kicad_agent.ops.handlers.pcb import _PCB_HANDLERS
    from kicad_agent.ops.handlers.query import _QUERY_HANDLERS
    pcb_path = _create_pcb_with_title_block(tmp_path)
    ir = _build_ir(pcb_path)
    handler = _PCB_HANDLERS["set_board_metadata"]
    handler(SetBoardMetadataOp(title="New Title", company="New Co", target_file="test_meta.kicad_pcb"), ir, pcb_path)
    # Re-read
    read_handler = _QUERY_HANDLERS["read_board_metadata"]
    result = read_handler(ReadBoardMetadataOp(target_file="test_meta.kicad_pcb"), ir, pcb_path)
    assert result["title"] == "New Title"
    assert result["company"] == "New Co"
    assert result["rev"] == "1.0"  # unchanged
    assert result["date"] == "2020-01-01"  # unchanged


def test_set_board_metadata_comments(tmp_path):
    """set_board_metadata writes comments and round-trips them (META-03, META-06)."""
    from kicad_agent.ops.handlers.pcb import _PCB_HANDLERS
    from kicad_agent.ops.handlers.query import _QUERY_HANDLERS
    pcb_path = _create_pcb_with_title_block(tmp_path)
    ir = _build_ir(pcb_path)
    handler = _PCB_HANDLERS["set_board_metadata"]
    handler(SetBoardMetadataOp(comments=["Project X", "Rev B", "Do not modify"], target_file="test_meta.kicad_pcb"), ir, pcb_path)
    read_handler = _QUERY_HANDLERS["read_board_metadata"]
    result = read_handler(ReadBoardMetadataOp(target_file="test_meta.kicad_pcb"), ir, pcb_path)
    assert result["comments"] == ["Project X", "Rev B", "Do not modify"]


def test_set_board_metadata_inserts_when_absent(tmp_path):
    """set_board_metadata inserts a title_block when none exists."""
    from kicad_agent.ops.handlers.pcb import _PCB_HANDLERS
    from kicad_agent.ops.handlers.query import _QUERY_HANDLERS
    pcb_path = tmp_path / "notb.kicad_pcb"
    pcb_path.write_text('(kicad_pcb (version 20241229) (generator "test") (paper "A4") (layers (0 "F.Cu" signal)))', encoding="utf-8")
    ir = _build_ir(pcb_path)
    handler = _PCB_HANDLERS["set_board_metadata"]
    handler(SetBoardMetadataOp(title="Inserted", rev="1.0", target_file="notb.kicad_pcb"), ir, pcb_path)
    read_handler = _QUERY_HANDLERS["read_board_metadata"]
    result = read_handler(ReadBoardMetadataOp(target_file="notb.kicad_pcb"), ir, pcb_path)
    assert result["title"] == "Inserted"
    assert result["rev"] == "1.0"


def test_title_block_special_chars_round_trip(tmp_path):
    """Special characters (parens, ampersands, escaped quotes) round-trip (META-07, Pitfall 2)."""
    from kicad_agent.ops.handlers.pcb import _PCB_HANDLERS
    from kicad_agent.ops.handlers.query import _QUERY_HANDLERS
    pcb_path = _create_pcb_with_title_block(tmp_path)
    ir = _build_ir(pcb_path)
    handler = _PCB_HANDLERS["set_board_metadata"]
    handler(SetBoardMetadataOp(
        title="Board v2.1 (prototype)",
        company="Smith & Co.",
        target_file="test_meta.kicad_pcb"
    ), ir, pcb_path)
    read_handler = _QUERY_HANDLERS["read_board_metadata"]
    result = read_handler(ReadBoardMetadataOp(target_file="test_meta.kicad_pcb"), ir, pcb_path)
    assert result["title"] == "Board v2.1 (prototype)"
    assert result["company"] == "Smith & Co."


def test_modified_pcb_loads_in_kicad_cli(tmp_path):
    """kicad-cli pcb export stats confirms the modified file is structurally valid."""
    import subprocess
    import shutil
    if not shutil.which("kicad-cli"):
        pytest.skip("kicad-cli not available")
    from kicad_agent.ops.handlers.pcb import _PCB_HANDLERS
    pcb_path = _create_pcb_with_title_block(tmp_path)
    ir = _build_ir(pcb_path)
    _PCB_HANDLERS["set_board_revision"](SetBoardRevisionOp(rev="3.0", target_file="test_meta.kicad_pcb"), ir, pcb_path)
    # commit_raw_content writes to disk — verify kicad-cli can load it
    result = subprocess.run(
        ["kicad-cli", "pcb", "export", "stats", str(pcb_path)],
        capture_output=True, text=True, timeout=30
    )
    # kicad-cli returns 0 even on some failures; check stdout for the success
    # message (RESEARCH RQ3: success outputs "Wrote board statistics ...").
    assert result.returncode == 0, f"kicad-cli failed: {result.stderr}"
    assert "board statistics" in result.stdout.lower(), \
        f"Board failed to load in kicad-cli: {result.stdout}"
