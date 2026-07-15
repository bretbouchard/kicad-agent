"""Tests for template schematic generator.

Covers:
- Empty schematic generation
- Schematic with components
- Round-trip validation
- Power symbols present when specified
"""

from pathlib import Path

from volta.generation.intent import (
    ComponentSpec,
    GenerationIntent,
    PowerSpec,
)
from volta.generation.template_schematic import generate_schematic


class TestGenerateSchematic:
    """Tests for generate_schematic function."""

    def test_generate_empty_schematic(self, tmp_path):
        """Generate schematic with no components, verify file parses."""
        output = tmp_path / "empty.kicad_sch"
        intent = GenerationIntent(
            name="Empty Test",
            power=PowerSpec(nets=[]),
        )

        result = generate_schematic(output, intent)

        assert result.sch_path == output
        assert result.component_count == 0
        assert result.net_count == 0
        assert output.exists()

        # Verify file parses
        from kiutils.schematic import Schematic

        sch = Schematic.from_file(str(output))
        assert sch.titleBlock.title == "Empty Test"

    def test_generate_schematic_with_components(self, tmp_path):
        """Generate with 3 components, verify component_count."""
        output = tmp_path / "with_comps.kicad_sch"
        intent = GenerationIntent(
            name="Component Test",
            components=[
                ComponentSpec(
                    library_id="Device:R_Small_US",
                    reference="R1",
                    value="10k",
                ),
                ComponentSpec(
                    library_id="Device:C_Small",
                    reference="C1",
                    value="100nF",
                ),
                ComponentSpec(
                    library_id="Device:LED",
                    reference="D1",
                    value="Red",
                ),
            ],
            power=PowerSpec(nets=[]),
        )

        result = generate_schematic(output, intent)

        assert result.component_count == 3
        assert result.sch_path is not None  # Has a valid path

        from kiutils.schematic import Schematic

        sch = Schematic.from_file(str(output))
        assert len(sch.schematicSymbols) == 3
        # Verify lib_symbols were added
        assert len(sch.libSymbols) >= 3

    def test_generate_schematic_round_trip(self, tmp_path):
        """Generate, re-parse via existing parser, verify success."""
        output = tmp_path / "roundtrip.kicad_sch"
        intent = GenerationIntent(
            name="Round Trip",
            components=[
                ComponentSpec(
                    library_id="Device:R_Small_US",
                    reference="R1",
                    value="4.7k",
                ),
            ],
            power=PowerSpec(nets=[]),
        )

        result = generate_schematic(output, intent)
        assert result.component_count == 1

        # Re-parse through the project's own parser
        from volta.parser import parse_schematic

        parse_result = parse_schematic(output)
        assert parse_result is not None
        assert parse_result.raw_content is not None
        assert "R1" in parse_result.raw_content

    def test_generate_schematic_power_symbols(self, tmp_path):
        """Generate with GND and VCC, verify power symbols present."""
        output = tmp_path / "power.kicad_sch"
        intent = GenerationIntent(
            name="Power Test",
            components=[
                ComponentSpec(
                    library_id="Device:R_Small_US",
                    reference="R1",
                    value="10k",
                ),
            ],
            power=PowerSpec(nets=["GND", "VCC"]),
        )

        result = generate_schematic(output, intent)
        assert result.component_count == 1

        from kiutils.schematic import Schematic

        sch = Schematic.from_file(str(output))
        # 1 component + 2 power symbols = 3 total
        assert len(sch.schematicSymbols) == 3

        # Verify power lib_symbols exist
        power_lib_ids = [sym.libId for sym in sch.libSymbols if sym.isPower]
        assert "power:GND" in power_lib_ids
        assert "power:VCC" in power_lib_ids

    def test_generate_schematic_invalid_suffix(self, tmp_path):
        """generate_schematic rejects non-.kicad_sch suffix."""
        import pytest

        output = tmp_path / "wrong.txt"
        intent = GenerationIntent(name="Bad Suffix")

        with pytest.raises(ValueError, match="Expected .kicad_sch"):
            generate_schematic(output, intent)
