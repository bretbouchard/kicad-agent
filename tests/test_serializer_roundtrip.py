"""Tests for serializer round-trip and targeted bug fixes (Plan 77-02).

Validates:
- S-BUG-001: PCB serialization avoids kiutils to_file() corruption
- S-BUG-002: Schematic placed components preserve BOM status
- S-BUG-003: UUID reinjection raises ValueError on count mismatch
- S-BUG-004: Schematic serialization uses normalizer module
- S-BUG-005: Footprint serialization uses atomic write
- Round-trip: parse -> serialize -> parse produces valid output
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "Arduino_Mega"
FIXTURE_SCH = "Arduino_Mega.kicad_sch"
FIXTURE_PCB = "Arduino_Mega.kicad_pcb"

PCB_FIXTURE = Path(__file__).parent / "fixtures" / "smd_test_board.kicad_pcb"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project with a copy of the Arduino_Mega fixture."""
    sch_src = FIXTURE_DIR / FIXTURE_SCH
    pcb_src = FIXTURE_DIR / FIXTURE_PCB
    sch_dst = tmp_path / FIXTURE_SCH
    pcb_dst = tmp_path / FIXTURE_PCB
    shutil.copy2(sch_src, sch_dst)
    shutil.copy2(pcb_src, pcb_dst)
    return tmp_path


@pytest.fixture
def pcb_dir(tmp_path: Path) -> Path:
    """Create a temporary dir with a copy of the PCB fixture."""
    dst = tmp_path / PCB_FIXTURE.name
    shutil.copy2(PCB_FIXTURE, dst)
    return tmp_path


# ---------------------------------------------------------------------------
# S-BUG-001: PCB serialization uses raw S-expression path
# ---------------------------------------------------------------------------


def test_pcb_serialize_uses_atomic_write(project_dir: Path) -> None:
    """PCB serialize writes via atomic_write, not directly via kiutils to_file."""
    from volta.parser import parse_pcb
    from volta.serializer.pcb_ser import serialize_pcb

    pcb_path = project_dir / FIXTURE_PCB
    output_path = project_dir / "output.kicad_pcb"

    parse_result = parse_pcb(pcb_path)

    with patch("volta.serializer.pcb_ser.atomic_write") as mock_atomic:
        mock_atomic.side_effect = lambda p, c: p.write_text(c, encoding="utf-8")
        serialize_pcb(parse_result, output_path)

    mock_atomic.assert_called_once()
    assert output_path.exists()


def test_pcb_serialize_temp_file_cleaned(project_dir: Path) -> None:
    """PCB serialize cleans up temp files after serialization."""
    import os

    from volta.parser import parse_pcb
    from volta.serializer.pcb_ser import serialize_pcb

    pcb_path = project_dir / FIXTURE_PCB
    output_path = project_dir / "output_clean.kicad_pcb"

    parse_result = parse_pcb(pcb_path)
    serialize_pcb(parse_result, output_path)

    # No temp files should remain in the output directory
    tmp_files = list(project_dir.glob(".kicad_pcb_*.tmp"))
    assert len(tmp_files) == 0, f"Temp files left behind: {tmp_files}"


def test_pcb_roundtrip_preserves_structure(project_dir: Path) -> None:
    """Parse PCB, serialize, parse again -- compare element counts."""
    from volta.parser import parse_pcb
    from volta.serializer.pcb_ser import serialize_pcb

    pcb_path = project_dir / FIXTURE_PCB
    output_path = project_dir / "roundtrip.kicad_pcb"

    # Parse original
    parse1 = parse_pcb(pcb_path)
    original_content = pcb_path.read_text(encoding="utf-8")
    original_footprints = original_content.count("(footprint ")

    # Serialize
    serialize_pcb(parse1, output_path)

    # Parse serialized output
    parse2 = parse_pcb(output_path)
    output_content = output_path.read_text(encoding="utf-8")
    output_footprints = output_content.count("(footprint ")

    assert output_content.startswith("(kicad_pcb")
    assert output_footprints == original_footprints, (
        f"Footprint count changed: {original_footprints} -> {output_footprints}"
    )
    assert parse2.file_type == "pcb"


# ---------------------------------------------------------------------------
# S-BUG-002: Schematic preserves BOM status
# ---------------------------------------------------------------------------


def test_schematic_preserves_in_bom_yes(project_dir: Path) -> None:
    """Schematic round-trip preserves (in_bom yes) for placed components."""
    from volta.parser import parse_schematic
    from volta.serializer.schematic_ser import serialize_schematic

    sch_path = project_dir / FIXTURE_SCH
    output_path = project_dir / "bom_test.kicad_sch"

    # Parse and serialize
    parse_result = parse_schematic(sch_path)
    serialize_schematic(parse_result, output_path)

    # Check output doesn't have the old blanket replacement bug
    output_content = output_path.read_text(encoding="utf-8")

    # Count placed symbols (outside lib_symbols) with in_bom yes
    lines = output_content.split("\n")
    in_lib_symbols = False
    placed_in_bom_yes = 0
    for line in lines:
        if "(lib_symbols" in line:
            in_lib_symbols = True
        if in_lib_symbols and line.strip() == ")":
            in_lib_symbols = False
        if not in_lib_symbols and "(in_bom yes)" in line:
            placed_in_bom_yes += 1

    # Original file has many placed components with in_bom yes
    # The fix should preserve those (not replace with in_bom no)
    original_content = sch_path.read_text(encoding="utf-8")
    original_placed_in_bom_yes = 0
    in_lib_symbols = False
    for line in original_content.split("\n"):
        if "(lib_symbols" in line:
            in_lib_symbols = True
        if in_lib_symbols and line.strip() == ")":
            in_lib_symbols = False
        if not in_lib_symbols and "(in_bom yes)" in line:
            original_placed_in_bom_yes += 1

    assert placed_in_bom_yes == original_placed_in_bom_yes, (
        f"BOM status changed: {original_placed_in_bom_yes} -> {placed_in_bom_yes}"
    )


def test_schematic_no_blanket_bom_replacement() -> None:
    """_fix_kiutils_output no longer exists (replaced by normalizer)."""
    # The old _fix_kiutils_output function should not exist anymore
    from volta.serializer import schematic_ser

    assert not hasattr(schematic_ser, "_fix_kiutils_output"), (
        "_fix_kiutils_output should be removed (S-BUG-002, S-BUG-004)"
    )


# ---------------------------------------------------------------------------
# S-BUG-003: UUID reinjection raises on count mismatch
# ---------------------------------------------------------------------------


def test_uuid_reinjector_raises_on_count_mismatch() -> None:
    """UUID reinjection raises ValueError when element counts diverge."""
    from volta.parser.uuid_extractor import UUIDEntry, UUIDMap
    from volta.serializer.uuid_reinjector import reinject_uuids

    # Create a UUID map with more entries than structural elements
    uuid_map = UUIDMap(entries=[
        UUIDEntry(uuid_value="00000000-0000-0000-0000-000000000001", parent_type="pad", parent_index=0, line_number=1),
        UUIDEntry(uuid_value="00000000-0000-0000-0000-000000000002", parent_type="pad", parent_index=1, line_number=2),
        UUIDEntry(uuid_value="00000000-0000-0000-0000-000000000003", parent_type="pad", parent_index=2, line_number=3),
    ])

    # Serialized content with only 1 pad element
    content = '  (pad 1 smd rect (at 0 0) (size 1 1) (layers F.Cu)\n  )\n'

    with pytest.raises(ValueError, match="UUID reinjection count mismatch"):
        reinject_uuids(content, uuid_map)


def test_uuid_reinjector_passes_on_matching_counts() -> None:
    """UUID reinjection succeeds when element counts match."""
    from volta.parser.uuid_extractor import UUIDEntry, UUIDMap
    from volta.serializer.uuid_reinjector import reinject_uuids

    uuid_map = UUIDMap(entries=[
        UUIDEntry(uuid_value="00000000-0000-0000-0000-000000000001", parent_type="pad", parent_index=0, line_number=1),
    ])

    content = '  (pad 1 smd rect (at 0 0) (size 1 1) (layers F.Cu)\n  )\n'
    result = reinject_uuids(content, uuid_map)

    assert "00000000-0000-0000-0000-000000000001" in result


def test_uuid_reinjector_value_error_includes_type_breakdown() -> None:
    """ValueError message includes element type counts for debugging."""
    from volta.parser.uuid_extractor import UUIDEntry, UUIDMap
    from volta.serializer.uuid_reinjector import reinject_uuids

    uuid_map = UUIDMap(entries=[
        UUIDEntry(uuid_value="00000000-0000-0000-0000-000000000001", parent_type="pad", parent_index=0, line_number=1),
        UUIDEntry(uuid_value="00000000-0000-0000-0000-000000000002", parent_type="zone", parent_index=0, line_number=2),
    ])

    content = "(kicad_pcb\n)\n"

    with pytest.raises(ValueError, match="Map types:") as exc_info:
        reinject_uuids(content, uuid_map)

    assert "pad" in str(exc_info.value)
    assert "zone" in str(exc_info.value)


# ---------------------------------------------------------------------------
# S-BUG-004: Schematic uses normalizer module
# ---------------------------------------------------------------------------


def test_schematic_uses_normalizer_module() -> None:
    """schematic_ser imports normalize_kicad_output from normalizer module."""
    from volta.serializer import schematic_ser

    # The module should import normalize_kicad_output
    assert hasattr(schematic_ser, "normalize_kicad_output"), (
        "schematic_ser should use normalize_kicad_output from normalizer (S-BUG-004)"
    )


def test_schematic_lib_name_removed_from_placed_components(project_dir: Path) -> None:
    """Schematic serialization removes (lib_name ...) from placed components."""
    from volta.parser import parse_schematic
    from volta.serializer.schematic_ser import serialize_schematic

    sch_path = project_dir / FIXTURE_SCH
    output_path = project_dir / "libname_test.kicad_sch"

    parse_result = parse_schematic(sch_path)
    serialize_schematic(parse_result, output_path)

    content = output_path.read_text(encoding="utf-8")

    # Check that (lib_name "...") does NOT appear in placed components
    # (it should only appear inside lib_symbols section if at all)
    lines = content.split("\n")
    in_lib_symbols = False
    lib_name_in_placed = 0
    for line in lines:
        if "(lib_symbols" in line:
            in_lib_symbols = True
        if in_lib_symbols and line.strip() == ")":
            in_lib_symbols = False
        if not in_lib_symbols and "(lib_name " in line:
            lib_name_in_placed += 1

    assert lib_name_in_placed == 0, (
        f"Found {lib_name_in_placed} (lib_name ...) in placed components"
    )


def test_schematic_property_id_removed_from_placed_components(project_dir: Path) -> None:
    """Schematic serialization removes (id N) from property lines."""
    from volta.parser import parse_schematic
    from volta.serializer.schematic_ser import serialize_schematic

    sch_path = project_dir / FIXTURE_SCH
    output_path = project_dir / "propid_test.kicad_sch"

    parse_result = parse_schematic(sch_path)
    serialize_schematic(parse_result, output_path)

    content = output_path.read_text(encoding="utf-8")

    # Check that (property "Key" (id N) ...) pattern is NOT present
    # in placed components (outside lib_symbols)
    import re
    pattern = re.compile(r'\(property\s+"[^"]*"\s+\(id\s+\d+\)')
    matches = pattern.findall(content)

    assert len(matches) == 0, (
        f"Found {len(matches)} (id N) in property lines: {matches[:3]}"
    )


def test_schematic_roundtrip_valid(project_dir: Path) -> None:
    """Schematic round-trip produces valid KiCad output."""
    from volta.parser import parse_schematic
    from volta.serializer.schematic_ser import serialize_schematic

    sch_path = project_dir / FIXTURE_SCH
    output_path = project_dir / "roundtrip.kicad_sch"

    parse_result = parse_schematic(sch_path)
    serialize_schematic(parse_result, output_path)

    content = output_path.read_text(encoding="utf-8")
    assert content.startswith("(kicad_sch"), "Output must start with (kicad_sch"
    assert "(version " in content, "Version must be preserved"


# ---------------------------------------------------------------------------
# S-BUG-005: Footprint uses atomic write
# ---------------------------------------------------------------------------


def test_footprint_serialize_uses_atomic_write(tmp_path: Path) -> None:
    """Footprint serialize writes via atomic_write for crash safety."""
    from volta.parser.types import ParseResult
    from volta.serializer.footprint_ser import serialize_footprint

    # Create a minimal mock footprint ParseResult
    # We can't easily create a real kiutils Footprint object, so we
    # verify the atomic_write import and code path exist
    from volta.serializer import footprint_ser

    assert hasattr(footprint_ser, "atomic_write"), (
        "footprint_ser should import atomic_write (S-BUG-005)"
    )

    # Verify atomic_write is in the serialize_footprint code path
    import inspect
    source = inspect.getsource(serialize_footprint)
    assert "atomic_write" in source, (
        "serialize_footprint should call atomic_write (S-BUG-005)"
    )


# ---------------------------------------------------------------------------
# Round-trip: parse -> serialize -> parse
# ---------------------------------------------------------------------------


def test_schematic_roundtrip_preserves_symbol_count(project_dir: Path) -> None:
    """Round-trip preserves the placed symbol count."""
    from volta.parser import parse_schematic
    from volta.serializer.schematic_ser import serialize_schematic

    sch_path = project_dir / FIXTURE_SCH
    output_path = project_dir / "count_test.kicad_sch"

    # Count symbols in original
    original_content = sch_path.read_text(encoding="utf-8")
    original_symbols = original_content.count("(symbol (lib_id")

    parse_result = parse_schematic(sch_path)
    serialize_schematic(parse_result, output_path)

    output_content = output_path.read_text(encoding="utf-8")
    output_symbols = output_content.count("(symbol (lib_id")

    assert output_symbols == original_symbols, (
        f"Symbol count changed: {original_symbols} -> {output_symbols}"
    )
