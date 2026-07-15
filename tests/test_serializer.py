"""Tests for serializer modules (Plan 24-04, Task 2).

Validates schematic and PCB serializers, the normalizer, and round-trip
consistency (parse -> serialize -> compare).

Uses fixture files for realistic test data.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from volta.parser import parse_schematic

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "Arduino_Mega"
FIXTURE_SCH = "Arduino_Mega.kicad_sch"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project with a copy of the Arduino_Mega fixture."""
    sch_src = FIXTURE_DIR / FIXTURE_SCH
    sch_dst = tmp_path / FIXTURE_SCH
    shutil.copy2(sch_src, sch_dst)
    return tmp_path


# ---------------------------------------------------------------------------
# serialize_schematic
# ---------------------------------------------------------------------------


def test_serialize_schematic_produces_valid_output(project_dir: Path) -> None:
    """serialize_schematic writes a valid .kicad_sch file."""
    from volta.serializer import serialize_schematic

    sch_path = project_dir / FIXTURE_SCH
    output_path = project_dir / "output.kicad_sch"

    parse_result = parse_schematic(sch_path)
    result_path = serialize_schematic(parse_result, output_path)

    assert result_path == output_path.resolve()
    assert output_path.exists(), "Serialized file must exist"

    content = output_path.read_text(encoding="utf-8")
    assert content.startswith("(kicad_sch"), "Output must start with (kicad_sch"


def test_serialize_schematic_rejects_wrong_file_type(project_dir: Path) -> None:
    """serialize_schematic raises ValueError for non-schematic parse results."""
    from volta.parser.types import ParseResult

    mock_result = MagicMock_parse_result(file_type="pcb")
    output_path = project_dir / "bad_output.kicad_sch"

    from volta.serializer.schematic_ser import serialize_schematic

    with pytest.raises(ValueError, match="file_type"):
        serialize_schematic(mock_result, output_path)


# ---------------------------------------------------------------------------
# normalize_kicad_output
# ---------------------------------------------------------------------------


def test_normalizer_fixes_scientific_notation() -> None:
    """Normalizer converts scientific notation to fixed-point."""
    from volta.serializer.normalizer import normalize_kicad_output

    content = "  (xy 1.5e-07 2.3e+05)\n"
    normalized = normalize_kicad_output(content)
    assert "e" not in normalized.lower().split(")")[0], (
        f"Scientific notation should be converted: {normalized}"
    )
    assert "0.000000" in normalized or "230000" in normalized


def test_normalizer_preserves_quoted_strings() -> None:
    """Normalizer does not modify scientific-looking text inside quoted strings."""
    from volta.serializer.normalizer import normalize_kicad_output

    content = '(property "Value" "1.5e-07 resistor")\n'
    normalized = normalize_kicad_output(content)
    assert '"1.5e-07 resistor"' in normalized, (
        "Quoted strings must be preserved unchanged"
    )


def test_normalizer_converts_tabs_to_spaces() -> None:
    """Normalizer converts tabs to spaces."""
    from volta.serializer.normalizer import normalize_kicad_output

    content = "(kicad_sch\n\t(version 20231115)\n)"
    normalized = normalize_kicad_output(content)
    assert "\t" not in normalized, "Tabs should be converted to spaces"


# ---------------------------------------------------------------------------
# Round-trip: parse -> serialize -> compare
# ---------------------------------------------------------------------------


def test_schematic_round_trip(project_dir: Path) -> None:
    """Parse a schematic, serialize it, and verify the output is valid."""
    from volta.serializer import normalize_kicad_output, serialize_schematic

    sch_path = project_dir / FIXTURE_SCH
    output_path = project_dir / "roundtrip.kicad_sch"

    parse_result = parse_schematic(sch_path)
    serialize_schematic(parse_result, output_path)

    content = output_path.read_text(encoding="utf-8")
    normalized = normalize_kicad_output(content)

    assert normalized.startswith("(kicad_sch"), "Round-tripped file must be valid KiCad"
    assert "(version " in normalized, "Version must be preserved"


def test_schematic_round_trip_preserves_components(project_dir: Path) -> None:
    """Round-trip preserves the component count."""
    from volta.serializer import serialize_schematic

    sch_path = project_dir / FIXTURE_SCH
    output_path = project_dir / "roundtrip_count.kicad_sch"

    # Count components in original
    original_content = sch_path.read_text(encoding="utf-8")
    original_symbols = original_content.count("(symbol (lib_id")

    # Parse, serialize, count again
    parse_result = parse_schematic(sch_path)
    serialize_schematic(parse_result, output_path)

    output_content = output_path.read_text(encoding="utf-8")
    output_symbols = output_content.count("(symbol (lib_id")

    assert output_symbols == original_symbols, (
        f"Component count changed: {original_symbols} -> {output_symbols}"
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


class MagicMock_parse_result:
    """Minimal mock for ParseResult with a configurable file_type."""

    def __init__(self, file_type: str = "schematic"):
        self.file_type = file_type
