"""Tests for KiCad output normalizer -- FND-08.

Covers:
- D-12: Whitespace normalization (tabs to spaces)
- D-13: Post-process normalizer for token formatting
- D-14: Deterministic, SCM-friendly serialization
- Council M-01: String-aware scientific notation parsing
- Pitfall 3: Normalizer must preserve round-trip stability
"""

from pathlib import Path

import pytest
from kiutils.schematic import Schematic

from volta.parser import parse_schematic
from volta.serializer.normalizer import (
    _fix_scientific_notation,
    _normalize_whitespace,
    normalize_kicad_output,
)


class TestScientificNotation:
    """D-14, Pitfall 13: Scientific notation fixed-point conversion."""

    def test_replaces_positive_exponent(self) -> None:
        """Positive exponent scientific notation is converted to fixed-point."""
        result = normalize_kicad_output("(at 1.5e+02 2.0e+01)")
        assert "150.000000" in result
        assert "20.000000" in result

    def test_replaces_negative_exponent(self) -> None:
        """Negative exponent scientific notation is converted to fixed-point."""
        result = normalize_kicad_output("(at 1.5e-07 0.0)")
        assert "0.000000" in result

    def test_regular_floats_get_angle(self) -> None:
        """Bug #29: Regular floats in (at X Y) get angle 0 appended."""
        input_str = "(at 10.5 20.3)"
        result = normalize_kicad_output(input_str)
        assert "(at 10.5 20.3 0)" in result

    def test_preserves_integers(self) -> None:
        """Integers are left unchanged."""
        input_str = "(size 5 3)"
        result = normalize_kicad_output(input_str)
        assert result == input_str

    def test_mixed_content(self) -> None:
        """Only scientific notation is changed in mixed content."""
        result = normalize_kicad_output("(at 10.5 1.5e-07 20.3 2.0e+01)")
        assert "10.5" in result
        assert "0.000000" in result
        assert "20.3" in result
        assert "200.000000" in result or "20.000000" in result

    def test_sci_notation_inside_quoted_string_preserved(self) -> None:
        """Council M-01: Scientific notation inside quoted strings is NOT replaced."""
        result = normalize_kicad_output('(property "value" "1.5e-07")')
        assert "1.5e-07" in result

    def test_sci_notation_after_quoted_string_fixed(self) -> None:
        """Council M-01: Sci-notation outside quoted strings IS replaced."""
        result = normalize_kicad_output('(property "val" "text") (at 1.5e-07 0)')
        assert "1.5e-07" not in result.split('"text")')[1]
        assert "0.000000" in result

    def test_escaped_quotes_in_string_handled(self) -> None:
        """Council M-01: Escaped quotes inside strings don't break parsing."""
        input_str = r'(property "val" "he said \"1.5e-07\"") (at 2.0e+01)'
        result = normalize_kicad_output(input_str)
        # The 1.5e-07 inside escaped quotes should be preserved
        assert "1.5e-07" in result
        # The 2.0e+01 outside quotes should be replaced
        assert "20.000000" in result


class TestAtAngleFix:
    """Bug #29: Missing rotation angle in (at X Y) position elements."""

    def test_property_at_gets_angle(self) -> None:
        """(at X Y) in property context gets angle 0 appended."""
        result = normalize_kicad_output(
            '(property "Reference" "R1" (at 10.5 20.3))'
        )
        assert "(at 10.5 20.3 0)" in result

    def test_label_at_gets_angle(self) -> None:
        """(at X Y) in label context gets angle 0 appended."""
        result = normalize_kicad_output(
            '(label "NET1" (at 50.0 75.0))'
        )
        assert "(at 50.0 75.0 0)" in result

    def test_global_label_at_gets_angle(self) -> None:
        """(at X Y) in global_label context gets angle 0 appended."""
        result = normalize_kicad_output(
            '(global_label "VCC" (at 30.0 20.0))'
        )
        assert "(at 30.0 20.0 0)" in result

    def test_hierarchical_label_at_gets_angle(self) -> None:
        """(at X Y) in hierarchical_label context gets angle 0 appended."""
        result = normalize_kicad_output(
            '(hierarchical_label "CLK" (at 15.0 40.0))'
        )
        assert "(at 15.0 40.0 0)" in result

    def test_junction_at_not_modified(self) -> None:
        """(junction (at X Y)) must NOT get angle added — native KiCad format."""
        result = normalize_kicad_output(
            '(junction (at 21.59 132.08) (diameter 0) (color 0 0 0 0) (uuid abc))'
        )
        assert "(at 21.59 132.08)" in result
        assert "(at 21.59 132.08 0)" not in result

    def test_no_connect_at_not_modified(self) -> None:
        """(no_connect (at X Y)) must NOT get angle added — native KiCad format."""
        result = normalize_kicad_output(
            '(no_connect (at 34.29 31.75) (uuid abc))'
        )
        assert "(at 34.29 31.75)" in result

    def test_at_with_existing_angle_not_doubled(self) -> None:
        """(at X Y 0) already with angle must not be doubled to (at X Y 0 0)."""
        result = normalize_kicad_output(
            '(property "Reference" "R1" (at 10.5 20.3 0))'
        )
        assert "(at 10.5 20.3 0)" in result
        assert "(at 10.5 20.3 0 0)" not in result

    def test_at_with_nonzero_angle_not_modified(self) -> None:
        """(at X Y 180) with nonzero angle must not be changed."""
        result = normalize_kicad_output(
            '(label "NET1" (at 50.0 75.0 180))'
        )
        assert "(at 50.0 75.0 180)" in result
        assert "(at 50.0 75.0 180 0)" not in result

    def test_symbol_at_without_angle_not_modified(self) -> None:
        """Symbol (at X Y) without angle must not be modified (KiCad omits for 0-deg non-power)."""
        result = normalize_kicad_output(
            '(symbol (lib_id "Device:R") (at 100.0 200.0) (unit 1) (uuid abc))'
        )
        assert "(at 100.0 200.0)" in result
        assert "(at 100.0 200.0 0)" not in result

    def test_symbol_at_with_mirror_not_modified(self) -> None:
        """Symbol (at X Y) followed by (mirror must not get angle."""
        result = normalize_kicad_output(
            '(symbol (lib_id "Device:R") (at 100.0 200.0) (mirror y) (unit 1) (uuid abc))'
        )
        assert "(at 100.0 200.0)" in result

    def test_power_symbol_at_with_angle_preserved(self) -> None:
        """Power symbol (at X Y 0) already has angle — do not double."""
        result = normalize_kicad_output(
            '(symbol (lib_id "power:+3V3") (at 31.75 26.67 0) (unit 1) (uuid abc))'
        )
        assert "(at 31.75 26.67 0)" in result
        assert "(at 31.75 26.67 0 0)" not in result

    def test_at_in_quoted_string_not_modified(self) -> None:
        """(at X Y) inside quoted strings must not be modified."""
        result = normalize_kicad_output(
            '(property "note" "connect at 10 20") (at 30 40))'
        )
        assert "(at 30 40 0)" in result
        assert "at 10 20" in result  # Inside quoted string, unchanged

    def test_negative_y_values_get_angle(self) -> None:
        """Negative Y coordinates (common in KiCad) get angle appended."""
        result = normalize_kicad_output(
            '(property "Ref" "R1" (at 10.5 -20.3))'
        )
        assert "(at 10.5 -20.3 0)" in result

    def test_idempotent_angle_fix(self) -> None:
        """Normalizing twice produces same result."""
        input_str = '(property "Ref" "R1" (at 10 20))'
        first = normalize_kicad_output(input_str)
        second = normalize_kicad_output(first)
        assert first == second

    def test_multiple_at_in_same_line(self) -> None:
        """Multiple (at X Y) in one line all get angle."""
        result = normalize_kicad_output(
            '(property "Ref" "R1" (at 10 20)) (property "Val" "1k" (at 30 40))'
        )
        assert "(at 10 20 0)" in result
        assert "(at 30 40 0)" in result

    def test_real_schematic_junctions_preserved(self, arduino_mega_sch: Path) -> None:
        """Junctions in real KiCad schematic are not modified by angle fix."""
        parse_result = parse_schematic(arduino_mega_sch)
        raw_output = parse_result.kiutils_obj.to_sexpr()
        normalized = normalize_kicad_output(raw_output)

        import re
        # Match junction (at X Y) — no angle expected in native format
        junction_re = re.compile(r'junction \(at ([\d.-]+) ([\d.-]+)\)')
        junctions_orig = junction_re.findall(raw_output)
        junctions_norm = junction_re.findall(normalized)
        assert junctions_orig == junctions_norm, (
            f"Junctions modified: {len(junctions_orig)} → {len(junctions_norm)}"
        )


class TestWhitespaceNormalization:
    """D-12: Whitespace normalization."""

    def test_tabs_replaced_with_spaces(self) -> None:
        """Tabs are replaced with 4 spaces and angle is added (Bug #29)."""
        result = normalize_kicad_output("(at\t10 20)")
        assert result == "(at 10 20 0)"



class TestDeterminism:
    """FND-08: Normalizer is deterministic and idempotent."""

    def test_same_input_same_output(self) -> None:
        """Same input always produces same output."""
        input_str = "(at 1.5e-07 2.0e+01)"
        result1 = normalize_kicad_output(input_str)
        result2 = normalize_kicad_output(input_str)
        assert result1 == result2

    def test_idempotent(self) -> None:
        """Normalizing already-normalized output produces identical output."""
        input_str = "(at 1.5e-07 2.0e+01)"
        first = normalize_kicad_output(input_str)
        second = normalize_kicad_output(first)
        assert first == second


class TestUUIDPreservation:
    """Verifier gap: UUIDs must not be corrupted by sci-notation fix."""

    def test_uuid_not_corrupted(self) -> None:
        """UUIDs containing hex digits like e/E are not matched as sci-notation."""
        uuid_str = "(uuid 0000d847-f0b2-a28f-0500-000000e95976)"
        result = normalize_kicad_output(uuid_str)
        assert "000000e95976" in result
        assert result == uuid_str

    def test_multiple_uuids_preserved(self) -> None:
        """Multiple UUIDs in a file are all preserved."""
        content = (
            "(uuid 123e4567-e89b-12d3-a456-426614174000)\n"
            "(uuid 00000000-0000-0000-0000-00000000e959)\n"
            "(at 1.5e-07 2.0e+01)\n"
        )
        result = normalize_kicad_output(content)
        assert "123e4567-e89b-12d3-a456-426614174000" in result
        assert "00000000-0000-0000-0000-00000000e959" in result
        assert "0.000000" in result  # 1.5e-07 was fixed
        assert "20.000000" in result  # 2.0e+01 was fixed

    def test_real_schematic_uuids_preserved(self, arduino_mega_sch: Path) -> None:
        """UUIDs in real KiCad schematic files are not corrupted."""
        parse_result = parse_schematic(arduino_mega_sch)
        raw_output = parse_result.kiutils_obj.to_sexpr()

        normalized = normalize_kicad_output(raw_output)

        # Count UUID tokens in original and normalized
        import re
        uuid_pattern = re.compile(r"\(uuid ([0-9a-f-]+)\)")
        original_uuids = uuid_pattern.findall(raw_output)
        normalized_uuids = uuid_pattern.findall(normalized)

        assert original_uuids == normalized_uuids, (
            f"UUID mismatch: {len(original_uuids)} original vs {len(normalized_uuids)} normalized"
        )


class TestRoundTripStability:
    """Pitfall 3: Normalizer must not break round-trip stability."""

    def test_normalizer_preserves_round_trip(
        self, arduino_mega_sch: Path, tmp_output_dir: Path
    ) -> None:
        """Normalized serialized schematic parses back successfully."""
        # Parse the original schematic
        parse_result = parse_schematic(arduino_mega_sch)

        # Serialize via kiutils to_sexpr()
        raw_output = parse_result.kiutils_obj.to_sexpr()

        # Apply normalizer
        normalized = normalize_kicad_output(raw_output)

        # Write normalized content to a temp file
        output_path = tmp_output_dir / "normalized.kicad_sch"
        output_path.write_text(normalized, encoding="utf-8")

        # Parse the normalized output back
        reparsed = Schematic.from_file(str(output_path))

        # Verify it parses without error and has components
        assert reparsed is not None
        assert hasattr(reparsed, "schematicSymbols")


class TestIntegrationTransactionNormalizer:
    """Council Finding 7+10: End-to-end pipeline test."""

    def test_transaction_with_ir_and_normalizer(
        self, arduino_mega_sch: Path, tmp_output_dir: Path
    ) -> None:
        """Full pipeline: parse -> IR -> Transaction -> modify -> serialize -> normalize -> commit."""
        from volta.ir.schematic_ir import SchematicIR
        from volta.ir.transaction import Transaction

        # Copy the schematic to a temp file so we can modify it
        work_file = tmp_output_dir / "work.kicad_sch"
        work_file.write_text(
            arduino_mega_sch.read_text(encoding="utf-8"), encoding="utf-8"
        )

        # Parse and create IR
        parse_result = parse_schematic(work_file)
        ir = SchematicIR(_parse_result=parse_result)

        # Enter transaction
        with Transaction(work_file) as txn:
            # Get a component and modify a property through IR
            comp = ir.get_component_by_ref("U1")
            if comp is not None:
                for prop in comp.properties:
                    if prop.key == "Value":
                        original_value = prop.value
                        prop.value = "MODIFIED_VALUE"
                        ir._record_mutation(
                            "modify_property",
                            {"ref": "U1", "property": "Value", "old": original_value, "new": "MODIFIED_VALUE"},
                        )
                        break

            # Serialize via kiutils
            raw_output = ir.kiutils_obj.to_sexpr()

            # Normalize the output
            normalized = normalize_kicad_output(raw_output)

            # Verify normalizer is deterministic
            normalized2 = normalize_kicad_output(raw_output)
            assert normalized == normalized2

            # Write normalized content to file
            work_file.write_text(normalized, encoding="utf-8")

            # Commit the transaction
            result = txn.commit()

        assert result.success is True

        # Verify the committed file parses back successfully
        reparsed = Schematic.from_file(str(work_file))
        assert reparsed is not None
        assert hasattr(reparsed, "schematicSymbols")
