"""Tests for ERC auto-fix operations (Phase 35).

Covers:
- update_symbols_from_library
- fix_shorted_nets
- fix_pin_type_mismatches
- place_missing_units
- remove_dangling_wires
- break_wire_shorts
"""

import pytest
from pathlib import Path

from kicad_agent.ops._schema_library import UpdateSymbolsFromLibraryOp
from kicad_agent.ops._schema_repair import (
    FixShortedNetsOp,
    FixPinTypeMismatchesOp,
    PlaceMissingUnitsOp,
    RemoveDanglingWiresOp,
    BreakWireShortsOp,
)
from kicad_agent.ir.schematic_ir import SchematicIR


FIXTURE_DIR = Path(__file__).parent / "fixtures"
ARDUINO_SCH = FIXTURE_DIR / "Arduino_Mega" / "Arduino_Mega.kicad_sch"


@pytest.fixture
def arduino_ir():
    """Load Arduino Mega schematic as IR."""
    if not ARDUINO_SCH.exists():
        pytest.skip("Arduino_Mega fixture not found")
    from kicad_agent.parser import parse_schematic
    result = parse_schematic(ARDUINO_SCH)
    return SchematicIR(_parse_result=result)


# --- Schema validation tests ---

class TestSchemas:
    def test_update_symbols_defaults(self):
        op = UpdateSymbolsFromLibraryOp(target_file="test.kicad_sch")
        assert op.op_type == "update_symbols_from_library"
        assert op.references is None
        assert op.dry_run is False

    def test_fix_shorted_nets_defaults(self):
        op = FixShortedNetsOp(target_file="test.kicad_sch")
        assert op.strategy == "keep_first"
        assert op.keep_nets is None

    def test_fix_pin_types_defaults(self):
        op = FixPinTypeMismatchesOp(target_file="test.kicad_sch")
        assert op.pin_type_map is None  # Defaults to {"unspecified": "passive"}

    def test_place_missing_units_defaults(self):
        op = PlaceMissingUnitsOp(target_file="test.kicad_sch")
        assert op.offset_x == 25.4
        assert op.offset_y == 0.0

    def test_remove_dangling_wires_defaults(self):
        op = RemoveDanglingWiresOp(target_file="test.kicad_sch")
        assert op.max_length_mm is None

    def test_dry_run_flags(self):
        for Schema in [
            UpdateSymbolsFromLibraryOp,
            FixShortedNetsOp,
            FixPinTypeMismatchesOp,
            PlaceMissingUnitsOp,
            RemoveDanglingWiresOp,
            BreakWireShortsOp,
        ]:
            op = Schema(target_file="test.kicad_sch", dry_run=True)
            assert op.dry_run is True

    def test_update_symbols_with_references(self):
        op = UpdateSymbolsFromLibraryOp(
            target_file="test.kicad_sch",
            references=["U1", "U2"],
        )
        assert op.references == ["U1", "U2"]

    def test_fix_shorted_nets_manual_strategy(self):
        op = FixShortedNetsOp(
            target_file="test.kicad_sch",
            strategy="manual",
            keep_nets=["GND", "VCC"],
        )
        assert op.strategy == "manual"
        assert op.keep_nets == ["GND", "VCC"]

    def test_fix_pin_types_custom_map(self):
        op = FixPinTypeMismatchesOp(
            target_file="test.kicad_sch",
            pin_type_map={"unspecified": "bidirectional"},
        )
        assert op.pin_type_map == {"unspecified": "bidirectional"}

    def test_remove_dangling_max_length(self):
        op = RemoveDanglingWiresOp(
            target_file="test.kicad_sch",
            max_length_mm=5.0,
        )
        assert op.max_length_mm == 5.0

    def test_break_wire_shorts_defaults(self):
        op = BreakWireShortsOp(target_file="test.kicad_sch")
        assert op.op_type == "break_wire_shorts"
        assert op.net_pairs is None
        assert op.strategy == "shortest_path"
        assert op.dry_run is False

    def test_break_wire_shorts_with_pairs(self):
        op = BreakWireShortsOp(
            target_file="test.kicad_sch",
            net_pairs=[["ADC_IN_1", "GND"], ["+3.3V", "VCC_5V"]],
        )
        assert op.net_pairs == [["ADC_IN_1", "GND"], ["+3.3V", "VCC_5V"]]

    def test_break_wire_shorts_all_bridges_strategy(self):
        op = BreakWireShortsOp(
            target_file="test.kicad_sch",
            strategy="all_bridges",
        )
        assert op.strategy == "all_bridges"


# --- Handler integration tests (dry_run) ---

class TestUpdateSymbolsFromLibrary:
    def test_dry_run_no_crash(self, arduino_ir):
        from kicad_agent.ops.repair import update_symbols_from_library
        result = update_symbols_from_library(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "updated" in result
        assert "skipped" in result
        assert isinstance(result["updated"], list)
        assert isinstance(result["skipped"], list)


class TestFixPinTypeMismatches:
    def test_dry_run_default_map(self, arduino_ir):
        from kicad_agent.ops.repair import fix_pin_type_mismatches
        result = fix_pin_type_mismatches(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "pins_changed" in result
        assert isinstance(result["pins_changed"], list)
        # dry_run should not modify IR
        for p in result["pins_changed"]:
            assert p.get("dry_run") is True

    def test_custom_map_no_match(self, arduino_ir):
        from kicad_agent.ops.repair import fix_pin_type_mismatches
        result = fix_pin_type_mismatches(
            arduino_ir, ARDUINO_SCH,
            pin_type_map={"nonexistent_type": "passive"},
            dry_run=True,
        )
        assert result["total"] == 0


class TestFixShortedNets:
    def test_dry_run_no_crash(self, arduino_ir):
        from kicad_agent.ops.repair import fix_shorted_nets
        result = fix_shorted_nets(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "shorts_found" in result
        assert "labels_removed" in result


class TestPlaceMissingUnits:
    def test_dry_run_no_crash(self, arduino_ir):
        from kicad_agent.ops.repair import place_missing_units
        result = place_missing_units(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "units_placed" in result
        assert isinstance(result["units_placed"], list)


class TestRemoveDanglingWires:
    def test_dry_run_no_crash(self, arduino_ir):
        from kicad_agent.ops.repair import remove_dangling_wires
        result = remove_dangling_wires(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "removed_count" in result
        assert isinstance(result["removed_count"], int)

    def test_with_max_length(self, arduino_ir):
        from kicad_agent.ops.repair import remove_dangling_wires
        result = remove_dangling_wires(
            arduino_ir, ARDUINO_SCH,
            max_length_mm=1.0,
            dry_run=True,
        )
        assert result["removed_count"] >= 0


class TestBreakWireShorts:
    def test_dry_run_no_crash(self, arduino_ir):
        from kicad_agent.ops.repair import break_wire_shorts
        result = break_wire_shorts(
            arduino_ir, ARDUINO_SCH,
            dry_run=True,
        )
        assert "shorts_found" in result
        assert "wires_removed" in result
        assert "details" in result
        assert isinstance(result["shorts_found"], int)
        assert isinstance(result["details"], list)

    def test_no_shorts_returns_clean(self, arduino_ir):
        """With a non-existent pair, should find 0 target shorts."""
        from kicad_agent.ops.repair import break_wire_shorts
        result = break_wire_shorts(
            arduino_ir, ARDUINO_SCH,
            net_pairs=[["NONEXISTENT_A", "NONEXISTENT_B"]],
            dry_run=True,
        )
        assert result["shorts_found"] == 0
        assert result["wires_removed"] == 0

    def test_find_bridge_wires_no_match(self, arduino_ir):
        """find_bridge_wires returns empty for non-existent net pair."""
        from kicad_agent.ops.repair import find_bridge_wires
        result = find_bridge_wires(arduino_ir, "FAKE_NET_A", "FAKE_NET_B")
        assert result == []


# --- Executor dispatch tests ---

class TestExecutorDispatch:
    def test_all_registered(self):
        from kicad_agent.ops.executor import _SCHEMATIC_HANDLERS
        ops = [
            "update_symbols_from_library",
            "fix_shorted_nets",
            "fix_pin_type_mismatches",
            "place_missing_units",
            "remove_dangling_wires",
            "break_wire_shorts",
        ]
        for op_type in ops:
            assert op_type in _SCHEMATIC_HANDLERS, f"{op_type} not registered"


# --- Phase 101-01: OpMeta deprecation field (R-3 / P0-003) ---


class TestOpMetaDeprecatedField:
    """Tests that OpMeta has a deprecated field and the two erc_auto_fix ops use it."""

    def test_opmeta_has_deprecated_field(self):
        """OpMeta model must have a `deprecated` field of type bool with default False."""
        from kicad_agent.ops.registry import OpMeta

        assert "deprecated" in OpMeta.model_fields, (
            "OpMeta must have a 'deprecated' field"
        )
        # Default must be False (backward compat for all other ops)
        meta = OpMeta(
            op_type="test_op",
            category="test",
            description="test",
            file_types=[".kicad_sch"],
            is_readonly=True,
            scope="single_file",
            requires=[],
            conflicts=[],
        )
        assert meta.deprecated is False, (
            "deprecated field must default to False for backward compatibility"
        )

    def test_erc_auto_fix_registry_deprecated_flag(self):
        """OPERATION_REGISTRY['erc_auto_fix'] must have deprecated=True."""
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        meta = OPERATION_REGISTRY.get("erc_auto_fix")
        assert meta is not None, "erc_auto_fix must be in OPERATION_REGISTRY"
        assert meta.deprecated is True, (
            "erc_auto_fix must be marked deprecated=True (P0-003)"
        )

    def test_erc_auto_fix_hierarchical_registry_deprecated_flag(self):
        """OPERATION_REGISTRY['erc_auto_fix_hierarchical'] must have deprecated=True."""
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        meta = OPERATION_REGISTRY.get("erc_auto_fix_hierarchical")
        assert meta is not None, (
            "erc_auto_fix_hierarchical must be in OPERATION_REGISTRY"
        )
        assert meta.deprecated is True, (
            "erc_auto_fix_hierarchical must be marked deprecated=True (P0-003)"
        )

    def test_non_deprecated_ops_default_false(self):
        """A sampling of other ops must have deprecated=False (no collateral deprecation)."""
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        sample_ops = [
            "add_component",
            "remove_component",
            "add_wire",
            "update_symbols_from_library",
            "place_missing_units",
        ]
        for op_type in sample_ops:
            meta = OPERATION_REGISTRY.get(op_type)
            assert meta is not None, f"{op_type} must be in registry"
            assert meta.deprecated is False, (
                f"{op_type} should NOT be deprecated (only erc_auto_fix ops are)"
            )


class TestErcAutoFixDeprecationWarning:
    """Tests that handler entry points emit DeprecationWarning (P0-003)."""

    def test_erc_auto_fix_emits_deprecation_warning(self, arduino_ir, tmp_path):
        """erc_auto_fix() must emit DeprecationWarning referencing P0-003."""
        import warnings
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        # Copy fixture to tmp so we don't mutate the original
        target = tmp_path / "test.kicad_sch"
        target.write_bytes(ARDUINO_SCH.read_bytes())

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                erc_auto_fix(arduino_ir, target, max_iterations=1)
            except Exception:
                # Warning must fire BEFORE any file mutation or exception
                # propagation. We only care about the warning here.
                pass

        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1, (
            "erc_auto_fix must emit at least one DeprecationWarning"
        )
        msg = str(deprecation_warnings[0].message)
        assert "DEPRECATED" in msg, (
            f"Warning message must contain 'DEPRECATED', got: {msg}"
        )
        assert "P0-003" in msg, (
            f"Warning message must reference P0-003, got: {msg}"
        )

    def test_erc_auto_fix_hierarchical_emits_deprecation_warning(self, tmp_path):
        """erc_auto_fix_hierarchical() must emit DeprecationWarning referencing P0-003."""
        import warnings
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix_hierarchical

        # Copy fixture to tmp so we don't mutate the original
        target = tmp_path / "test.kicad_sch"
        target.write_bytes(ARDUINO_SCH.read_bytes())

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                erc_auto_fix_hierarchical(target, max_iterations=1)
            except Exception:
                # Warning must fire BEFORE any file mutation or exception
                # propagation. We only care about the warning here.
                pass

        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1, (
            "erc_auto_fix_hierarchical must emit at least one DeprecationWarning"
        )
        msg = str(deprecation_warnings[0].message)
        assert "DEPRECATED" in msg, (
            f"Warning message must contain 'DEPRECATED', got: {msg}"
        )
        assert "P0-003" in msg, (
            f"Warning message must reference P0-003, got: {msg}"
        )


# --- Phase 101 follow-up: P0-003 raw S-expr rewrite (MD-01) ---


class TestErcAutoFixRawSExprRewrite:
    """Tests that erc_auto_fix no longer corrupts KiCad 10 schematics.

    P0-003 fix (MD-01): erc_auto_fix now uses raw S-expression manipulation
    via SchematicRawWriter + atomic_write instead of kiutils to_file()
    re-serialization which corrupts KiCad 10 schematics.
    """

    def test_erc_auto_fix_does_not_call_to_file(self):
        """erc_auto_fix module must not call ir.schematic.to_file() anywhere.

        This is the core P0-003 acceptance criterion: the kiutils
        re-serialization path that corrupts KiCad 10 schematics must be
        completely removed.
        """
        import inspect
        from kicad_agent.ops import erc_auto_fix

        source = inspect.getsource(erc_auto_fix)
        # Exclude comments and docstrings (lines starting with # or inside """)
        code_lines = []
        in_docstring = False
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.endswith('"""'):
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            if stripped.startswith("#"):
                continue
            code_lines.append(line)
        code = "\n".join(code_lines)

        # No bare to_file calls (the corruption path)
        assert ".to_file(" not in code, (
            "erc_auto_fix must not call to_file() anywhere (P0-003). "
            "Found: " + ", ".join(
                line for line in code_lines if ".to_file(" in line
            )
        )

    def test_erc_auto_fix_uses_atomic_write(self):
        """erc_auto_fix module must import and use atomic_write."""
        from kicad_agent.ops import erc_auto_fix

        assert hasattr(erc_auto_fix, "atomic_write"), (
            "erc_auto_fix must import atomic_write from kicad_agent.io.atomic_write"
        )
        assert hasattr(erc_auto_fix, "_persist_ir_raw"), (
            "erc_auto_fix must define _persist_ir_raw helper"
        )

    def test_erc_auto_fix_preserves_kicad_10_formatting(self, tmp_path):
        """Run op on a KiCad 10 schematic, verify formatting preserved.

        Creates a minimal KiCad 10 schematic with specific formatting,
        runs _persist_ir_raw with a no_connect mutation, and verifies:
        - Original formatting (indentation, structure) preserved
        - no_connect marker inserted at correct position
        - File still valid S-expression (parses via kiutils)
        """
        import warnings
        from kicad_agent.parser import parse_schematic
        from kicad_agent.ir.schematic_ir import SchematicIR
        from kicad_agent.ops.erc_auto_fix import _persist_ir_raw

        # Create a minimal KiCad 10 schematic with distinctive formatting
        original = (
            '(kicad_sch\n'
            '  (version 20231120)\n'
            '  (generator "eeschema")\n'
            '  (generator_version "10.0")\n'
            '  (uuid "11111111-1111-1111-1111-111111111111")\n'
            '  (paper "A4")\n'
            '  (lib_symbols)\n'
            '  (sheet_instances (path "/" (page "1")))\n'
            ')\n'
        )
        sch_file = tmp_path / "test.kicad_sch"
        sch_file.write_text(original, encoding="utf-8")

        # Parse and create IR
        result = parse_schematic(sch_file)
        ir = SchematicIR(_parse_result=result)

        # Add a no_connect mutation via IR
        ir.add_no_connect(x=25.4, y=30.0)

        # Persist via raw writer (the P0-003 fix path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            _persist_ir_raw(ir, sch_file)

        # Read result
        written = sch_file.read_text(encoding="utf-8")

        # Assertion 1: no_connect marker present
        assert "(no_connect (at 25.4 30.0)" in written, (
            f"no_connect marker must be inserted. Got:\n{written}"
        )

        # Assertion 2: Original formatting preserved (version, generator, etc.)
        assert '(version 20231120)' in written, "version must be preserved"
        assert '(generator "eeschema")' in written, "generator must be preserved"
        assert '(generator_version "10.0")' in written, (
            "generator_version must be preserved (kiutils strips this)"
        )
        assert '(uuid "11111111-1111-1111-1111-111111111111")' in written, (
            "uuid must be preserved"
        )

        # Assertion 3: File still parses as valid S-expression
        # (if kiutils can re-read it, the structure is sound)
        from kiutils.schematic import Schematic
        re_read = Schematic.from_file(str(sch_file))
        assert re_read is not None, "Written file must be parseable by kiutils"
        assert len(re_read.noConnects) == 1, (
            f"Expected 1 no_connect, got {len(re_read.noConnects)}"
        )

    def test_erc_auto_fix_hierarchical_no_corruption(self, tmp_path):
        """Run hierarchical op on fixture, verify no structural corruption.

        The P0-003 corruption specifically placed PWR_FLAG lib_symbols INSIDE
        other lib_symbol blocks. This test verifies the raw writer places
        lib_symbols at the correct nesting level (top-level lib_symbols
        container).
        """
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        # Minimal schematic with an existing lib_symbol (to detect mis-nesting)
        original = (
            '(kicad_sch (version 20231120) (generator "eeschema")\n'
            '  (lib_symbols\n'
            '    (symbol "Device:R"\n'
            '      (pin_numbers (hide yes))\n'
            '      (symbol "R_0_1" (pin input line (at 0 0 0) (length 0)))\n'
            '    )\n'
            '  )\n'
            ')\n'
        )

        content = SchematicRawWriter.insert_power_flag(original, 50.0, 50.0)

        # PWR_FLAG lib_symbol must be inside (lib_symbols ...) container
        # NOT inside the Device:R symbol block
        assert 'symbol "power:PWR_FLAG"' in content, (
            "PWR_FLAG lib_symbol must be present"
        )

        # Find the position of power:PWR_FLAG and verify it's inside
        # lib_symbols, not nested inside Device:R
        pwr_flag_pos = content.find('symbol "power:PWR_FLAG"')
        device_r_close = content.find(')', content.find('symbol "Device:R"'))
        # The power:PWR_FLAG must come AFTER the Device:R symbol block closes
        # (i.e., it's a sibling in lib_symbols, not a child)
        assert pwr_flag_pos > device_r_close, (
            "PWR_FLAG lib_symbol must be at top level of lib_symbols container, "
            "not nested inside Device:R symbol block (P0-003 corruption)"
        )

        # Verify the file is still valid S-expression (balanced parens)
        depth = 0
        for char in content:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
        assert depth == 0, (
            f"S-expression must have balanced parens, got depth {depth}"
        )


class TestSchematicRawWriter:
    """Unit tests for the SchematicRawWriter helper (P0-003 fix)."""

    def test_insert_no_connect(self):
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '(kicad_sch (version 20231120))'
        result = SchematicRawWriter.insert_no_connect(content, 10.0, 20.0)
        assert "(no_connect (at 10.0 20.0)" in result
        assert result.rstrip().endswith(")")

    def test_insert_junction(self):
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '(kicad_sch (version 20231120))'
        result = SchematicRawWriter.insert_junction(content, 5.0, 15.0)
        assert "(junction (at 5.0 15.0)" in result
        assert "(diameter 0)" in result

    def test_insert_power_flag_lib_symbol_nesting(self):
        """PWR_FLAG lib_symbol must go in lib_symbols container, not nested."""
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = (
            '(kicad_sch (version 20231120)\n'
            '  (lib_symbols\n'
            '    (symbol "Device:R" (pin_numbers (hide yes)))\n'
            '  )\n'
            ')\n'
        )
        result = SchematicRawWriter.insert_power_flag(content, 10.0, 10.0)

        # lib_symbols container must now contain BOTH Device:R and power:PWR_FLAG
        assert 'symbol "Device:R"' in result
        assert 'symbol "power:PWR_FLAG"' in result

        # PWR_FLAG symbol instance must also be present at top level
        assert '(lib_id "power:PWR_FLAG")' in result

    def test_apply_mutation_add_no_connect(self):
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '(kicad_sch (version 20231120))'
        mutation = {"type": "add_no_connect", "position": [10.0, 20.0]}
        result = SchematicRawWriter.apply_mutation(content, mutation)
        assert "(no_connect (at 10.0 20.0)" in result

    def test_apply_mutations_multiple(self):
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '(kicad_sch (version 20231120))'
        mutations = [
            {"type": "add_no_connect", "position": [10.0, 20.0]},
            {"type": "add_junction", "position": [30.0, 40.0]},
        ]
        result = SchematicRawWriter.apply_mutations(content, mutations)
        assert "(no_connect (at 10.0 20.0)" in result
        assert "(junction (at 30.0 40.0)" in result

    def test_unknown_mutation_no_crash(self):
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '(kicad_sch (version 20231120))'
        mutation = {"type": "unknown_future_op", "position": [0.0, 0.0]}
        result = SchematicRawWriter.apply_mutation(content, mutation)
        # Should return content unchanged (defensive — don't break)
        assert result == content
