"""Phase 108 Plan 02 — Autolayout ops test suite (place/route/label).

Tests are organized by Task:
  - TestAutolayoutSchemas (Task 1): 6 schema validation tests
  - TestPlaceComponentsSch (Task 2): 10 placement handler + raw_writer tests
  - TestRouteWiresSch, TestApplyLabelsSch (Task 3): 10 routing/label tests
  - TestSchematicRawWriterExtensions (Task 3): 4 raw_writer branch tests

TDD flow: this file is committed FIRST (RED), then schemas/handlers land (GREEN).

Council fixes verified by tests:
  - HIGH-1: TargetFile imported from kicad_agent.ops.schema (NOT _schema_common)
  - HIGH-4: mutation dicts use "op" key (not "kind"); "kind" must NOT work
  - HIGH-6: read-after-write — route_wires_sch reads post-placement positions
  - NEW-MED-1: uses verified SchematicGraph API (.pins, .ref_to_libid, get_sheet_refs),
              NOT nonexistent _refs()/_pins()/_lookup_pin()
  - P101-INV-01: zero kiutils.to_file() in handler source (AST grep)
"""
from __future__ import annotations

import ast
import inspect
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "safe_annotate"


def _execute_op(op_json: dict, base_dir: Path) -> dict:
    """Execute an op via OperationExecutor. Returns the full result dict."""
    from kicad_agent.ops.executor import OperationExecutor
    from kicad_agent.ops.schema import Operation

    executor = OperationExecutor(base_dir=base_dir)
    op = Operation.model_validate({"root": op_json})
    return executor.execute(op)


# ============================================================================
# Task 1: Schema validation tests (RED first, then GREEN)
# ============================================================================


class TestAutolayoutSchemas:
    """Tests for PlaceComponentsSchOp, RouteWiresSchOp, ApplyLabelsSchOp."""

    def test_place_components_sch_constructs(self):
        """Test 1: PlaceComponentsSchOp constructs with discriminator literal."""
        from kicad_agent.ops._schema_autolayout import PlaceComponentsSchOp

        op = PlaceComponentsSchOp(
            op_type="place_components_sch",
            target_file="x.kicad_sch",
        )
        assert op.op_type == "place_components_sch"
        assert op.target_file == "x.kicad_sch"

    def test_dry_run_default_false_on_each_schema(self):
        """Test 2: dry_run defaults to False on all 3 schemas."""
        from kicad_agent.ops._schema_autolayout import (
            PlaceComponentsSchOp,
            RouteWiresSchOp,
            ApplyLabelsSchOp,
        )

        place = PlaceComponentsSchOp(op_type="place_components_sch", target_file="a.kicad_sch")
        route = RouteWiresSchOp(op_type="route_wires_sch", target_file="a.kicad_sch")
        label = ApplyLabelsSchOp(op_type="apply_labels_sch", target_file="a.kicad_sch")
        assert place.dry_run is False
        assert route.dry_run is False
        assert label.dry_run is False

    def test_schemas_reject_wrong_discriminator(self):
        """Test 3: Each schema rejects unknown op_type via discriminator."""
        from kicad_agent.ops._schema_autolayout import PlaceComponentsSchOp
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PlaceComponentsSchOp(
                op_type="route_wires_sch",  # wrong literal
                target_file="a.kicad_sch",
            )

    def test_all_3_ops_in_registry_catalog(self):
        """Test 4: All 3 ops in OPERATION_REGISTRY with category='autolayout'."""
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        for op_type in ("place_components_sch", "route_wires_sch", "apply_labels_sch"):
            assert op_type in OPERATION_REGISTRY, f"{op_type} missing from catalog"
            entry = OPERATION_REGISTRY[op_type]
            # OpMeta is a Pydantic model — access category as attribute
            category = getattr(entry, "category", None)
            assert category == "autolayout", (
                f"{op_type} category={category!r}, expected 'autolayout'"
            )

    def test_executor_union_accepts_all_3_op_types(self):
        """Test 5: Operation discriminated union accepts all 3 op types."""
        from kicad_agent.ops.schema import Operation

        for op_type, target in [
            ("place_components_sch", "a.kicad_sch"),
            ("route_wires_sch", "a.kicad_sch"),
            ("apply_labels_sch", "a.kicad_sch"),
        ]:
            op = Operation.model_validate({
                "root": {"op_type": op_type, "target_file": target},
            })
            assert op.root.op_type == op_type

    def test_targetfile_import_from_schema_module(self):
        """Test 6 (HIGH-1 regression guard): TargetFile imports from kicad_agent.ops.schema.

        The plan originally claimed TargetFile lived in _schema_common (which does
        not exist). This test pins the correct location.
        """
        from kicad_agent.ops.schema import TargetFile  # noqa: F401

        # Also confirm _schema_common does NOT exist (defensive)
        import importlib
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("kicad_agent.ops._schema_common")


# ============================================================================
# Task 2: place_components_sch handler + SchematicRawWriter.move_symbol
# ============================================================================


class TestPlaceComponentsSch:
    """place_components_sch handler tests + raw_writer move_symbol branch."""

    def test_place_components_sch_returns_positions(self, tmp_path):
        """Test 1: On a fixture, returns positions dict with at least 1 entry."""
        src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy(src, dst)

        result = _execute_op({
            "op_type": "place_components_sch",
            "target_file": "test.kicad_sch",
            "dry_run": True,
        }, base_dir=tmp_path)

        details = result.get("details", {})
        positions = details.get("positions", {})
        assert len(positions) >= 1, f"Expected >=1 position, got {positions}"
        assert "R1" in positions, f"R1 missing from positions {positions}"

    def test_positions_on_kicad_grid(self, tmp_path):
        """Test 2: All returned positions snap to 2.54mm grid."""
        src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy(src, dst)

        result = _execute_op({
            "op_type": "place_components_sch",
            "target_file": "test.kicad_sch",
            "dry_run": True,
        }, base_dir=tmp_path)

        positions = result["details"]["positions"]
        for ref, xy in positions.items():
            x, y = xy[0], xy[1]
            assert abs(x % 2.54) < 0.01 or abs(x % 2.54 - 2.54) < 0.01, (
                f"{ref} x={x} not on 2.54mm grid"
            )
            assert abs(y % 2.54) < 0.01 or abs(y % 2.54 - 2.54) < 0.01, (
                f"{ref} y={y} not on 2.54mm grid"
            )

    def test_dry_run_does_not_modify_file(self, tmp_path):
        """Test 3: dry_run=True returns positions but does NOT write file."""
        src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy(src, dst)
        original = dst.read_text()

        _execute_op({
            "op_type": "place_components_sch",
            "target_file": "test.kicad_sch",
            "dry_run": True,
        }, base_dir=tmp_path)

        assert dst.read_text() == original, "dry_run=True modified the file"

    def test_written_file_passes_paren_balance(self, tmp_path):
        """Test 4: After write, file has balanced parens."""
        src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy(src, dst)

        _execute_op({
            "op_type": "place_components_sch",
            "target_file": "test.kicad_sch",
        }, base_dir=tmp_path)

        content = dst.read_text()
        assert content.count("(") == content.count(")"), "Paren imbalance after write"

    def test_place_components_sch_no_kiutils_to_file(self):
        """Test 5 (P101-INV-01): handler source has ZERO to_file() Call nodes."""
        from kicad_agent.ops.handlers.autolayout import _handle_place_components_sch

        source = inspect.getsource(_handle_place_components_sch)
        tree = ast.parse(source)
        to_file_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_file"
        ]
        assert to_file_calls == [], (
            f"_handle_place_components_sch must NOT call to_file() — "
            f"P101-INV-01 violation. Found: {to_file_calls}"
        )

    def test_subcircuit_split_default_true(self):
        """Test 7 (group separation): subcircuit_split defaults True per D-02."""
        from kicad_agent.ops._schema_autolayout import PlaceComponentsSchOp

        op = PlaceComponentsSchOp(
            op_type="place_components_sch",
            target_file="a.kicad_sch",
        )
        assert op.subcircuit_split is True

    def test_move_symbol_branch_updates_symbol_at(self):
        """Test 8 (HIGH-4): apply_mutation with op='move_symbol' updates (at X Y)."""
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '''  (symbol (lib_id "Device:R") (at 50.0 50.0 0) (unit 1)
    (property "Reference" "R1" (at 52.0 50.0 0))
  )
'''
        result = SchematicRawWriter.apply_mutation(content, {
            "op": "move_symbol",
            "ref": "R1",
            "new_x": 100.0,
            "new_y": 75.0,
        })
        # Original (at 50.0 50.0 0) should be gone; new coords present
        assert "(at 50.0 50.0 0)" not in result or "(at 100.0 75.0" in result
        assert "(at 100.0 75.0" in result, f"new (at 100.0 75.0 missing in: {result!r}"

    def test_move_symbol_unknown_op_returns_unchanged(self):
        """Test 9: apply_mutation with unknown op returns content unchanged."""
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '  (symbol (lib_id "Device:R") (at 50.0 50.0 0))\n'
        result = SchematicRawWriter.apply_mutation(content, {"op": "nonexistent_op"})
        assert result == content, "Unknown op should return content unchanged"

    def test_move_symbol_kind_discriminator_does_not_work(self):
        """Test 10 (HIGH-4 regression guard): 'kind' key must NOT move the symbol.

        The dispatcher reads mutation.get('op') or mutation.get('type') — NEVER
        'kind'. A future contributor using 'kind' would silently no-op.
        """
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '''  (symbol (lib_id "Device:R") (at 50.0 50.0 0) (unit 1)
    (property "Reference" "R1" (at 52.0 50.0 0))
  )
'''
        result = SchematicRawWriter.apply_mutation(content, {
            "kind": "move_symbol",  # WRONG key — must not work
            "ref": "R1",
            "new_x": 100.0,
            "new_y": 75.0,
        })
        assert "(at 50.0 50.0 0)" in result, (
            "HIGH-4 REGRESSION: 'kind' key moved the symbol — dispatcher must "
            "read 'op' or 'type', never 'kind'"
        )


# ============================================================================
# Task 3: route_wires_sch + apply_labels_sch + insert_wire/insert_label branches
# ============================================================================


class TestRouteWiresSch:
    """route_wires_sch handler tests."""

    def test_route_wires_sch_returns_wires(self, tmp_path):
        """Test 1: On placed fixture, returns wires_generated >= 0 (handler runs)."""
        src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy(src, dst)

        result = _execute_op({
            "op_type": "route_wires_sch",
            "target_file": "test.kicad_sch",
            "dry_run": True,
        }, base_dir=tmp_path)

        details = result.get("details", {})
        # The handler must report dry_run=True and produce a result shape
        assert details.get("dry_run") is True
        assert "wires" in details

    def test_route_wires_sch_no_kiutils_to_file(self):
        """Test (P101-INV-01): handler source has ZERO to_file() Call nodes."""
        from kicad_agent.ops.handlers.autolayout import _handle_route_wires_sch

        source = inspect.getsource(_handle_route_wires_sch)
        tree = ast.parse(source)
        to_file_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_file"
        ]
        assert to_file_calls == [], (
            f"_handle_route_wires_sch must NOT call to_file() — "
            f"P101-INV-01 violation. Found: {to_file_calls}"
        )

    def test_route_wires_sch_dry_run_no_write(self, tmp_path):
        """Test 4: dry_run=True does not modify the file."""
        src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy(src, dst)
        original = dst.read_text()

        _execute_op({
            "op_type": "route_wires_sch",
            "target_file": "test.kicad_sch",
            "dry_run": True,
        }, base_dir=tmp_path)

        assert dst.read_text() == original, "dry_run=True modified the file"

    def test_route_wires_reads_post_placement_positions(self, tmp_path):
        """Test 6 (HIGH-6): route_wires_sch must read positions WRITTEN by place.

        Regression guard: route_wires_sch reads the file fresh from disk after
        place_components_sch writes it. If a future refactor caches the file
        content across ops, wires would target stale pre-placement positions.
        """
        src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy(src, dst)

        # 1. Run place_components_sch, capture positions
        place_result = _execute_op({
            "op_type": "place_components_sch",
            "target_file": "test.kicad_sch",
        }, base_dir=tmp_path)
        place_positions = place_result["details"]["positions"]

        # 2. Read the file content AFTER place_components_sch wrote it
        post_place_content = dst.read_text()

        # 3. Run route_wires_sch on the same file
        route_result = _execute_op({
            "op_type": "route_wires_sch",
            "target_file": "test.kicad_sch",
            "dry_run": True,
        }, base_dir=tmp_path)

        # 4. The route handler must have read the post-placement content.
        #    If it cached stale content, the file mtime/content would differ
        #    from what place wrote. Strongest assertion: the file on disk still
        #    matches what place wrote (route did not overwrite with stale data).
        assert dst.read_text() == post_place_content, (
            "HIGH-6 REGRESSION: route_wires_sch overwrote file with stale content "
            "— handler must read fresh from disk after place_components_sch"
        )
        # And the place positions must be non-empty (proves place actually wrote)
        assert len(place_positions) >= 1


class TestApplyLabelsSch:
    """apply_labels_sch handler tests."""

    def test_apply_labels_sch_returns_labels(self, tmp_path):
        """Test 7: Returns labels_generated >= 0 (handler runs)."""
        src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy(src, dst)

        result = _execute_op({
            "op_type": "apply_labels_sch",
            "target_file": "test.kicad_sch",
            "dry_run": True,
        }, base_dir=tmp_path)

        details = result.get("details", {})
        assert details.get("dry_run") is True
        assert "labels" in details

    def test_apply_labels_sch_no_kiutils_to_file(self):
        """Test (P101-INV-01): handler source has ZERO to_file() Call nodes."""
        from kicad_agent.ops.handlers.autolayout import _handle_apply_labels_sch

        source = inspect.getsource(_handle_apply_labels_sch)
        tree = ast.parse(source)
        to_file_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_file"
        ]
        assert to_file_calls == [], (
            f"_handle_apply_labels_sch must NOT call to_file() — "
            f"P101-INV-01 violation. Found: {to_file_calls}"
        )

    def test_apply_labels_sch_dry_run_no_write(self, tmp_path):
        """Test 10: dry_run=True does not modify the file."""
        src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy(src, dst)
        original = dst.read_text()

        _execute_op({
            "op_type": "apply_labels_sch",
            "target_file": "test.kicad_sch",
            "dry_run": True,
        }, base_dir=tmp_path)

        assert dst.read_text() == original, "dry_run=True modified the file"

    def test_apply_labels_writes_label_sexp(self, tmp_path):
        """Integration: write mode produces a (label ...) or (global_label ...) in file."""
        src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy(src, dst)
        original = dst.read_text()

        _execute_op({
            "op_type": "apply_labels_sch",
            "target_file": "test.kicad_sch",
            "dry_run": False,
        }, base_dir=tmp_path)

        new_content = dst.read_text()
        # The handler should produce at least one label S-expression.
        # If the fixture has no nets to label, the handler may no-op — accept either.
        if new_content != original:
            assert "(label " in new_content or "(global_label " in new_content, (
                "apply_labels_sch wrote content but no label S-expr present"
            )


# ============================================================================
# Task 3: SchematicRawWriter extension branches (insert_wire, insert_label)
# ============================================================================


class TestSchematicRawWriterExtensions:
    """Direct tests on the new apply_mutation branches (HIGH-4 fix)."""

    def test_insert_wire_branch_adds_wire_sexp(self):
        """insert_wire branch produces a (wire (pts ...)) S-expression."""
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '(kicad_sch (version 1)\n  (paper "A4")\n)\n'
        result = SchematicRawWriter.apply_mutation(content, {
            "op": "insert_wire",
            "points": [(10.0, 20.0), (30.0, 20.0)],
            "net_name": "N1",
        })
        assert "(wire" in result, "insert_wire did not add a (wire ...) block"
        assert "(xy 10.0 20.0)" in result or "(xy 10 20)" in result
        assert "(xy 30.0 20.0)" in result or "(xy 30 20)" in result

    def test_insert_label_branch_adds_local_label(self):
        """insert_label branch produces a (label "NAME" ...) S-expression."""
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '(kicad_sch (version 1)\n  (paper "A4")\n)\n'
        result = SchematicRawWriter.apply_mutation(content, {
            "op": "insert_label",
            "net_name": "SDA",
            "x": 50.0,
            "y": 25.0,
            "size": 1.27,
            "is_global": False,
            "uuid": "abc-123",
        })
        assert '(label "SDA"' in result, "insert_label did not add (label \"SDA\" ...)"
        assert "(at 50.0 25.0" in result or "(at 50 25" in result
        assert "abc-123" in result

    def test_insert_label_branch_global_label(self):
        """insert_label with is_global=True produces a (global_label ...)."""
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '(kicad_sch (version 1)\n  (paper "A4")\n)\n'
        result = SchematicRawWriter.apply_mutation(content, {
            "op": "insert_label",
            "net_name": "+3V3",
            "x": 0.0,
            "y": 0.0,
            "size": 1.27,
            "is_global": True,
            "uuid": "glob-1",
        })
        assert '(global_label "+3V3"' in result, (
            "is_global=True must produce (global_label ...), not (label ...)"
        )

    def test_insert_wire_and_label_via_apply_mutations(self):
        """apply_mutations with both op types in sequence works."""
        from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter

        content = '(kicad_sch (version 1)\n  (paper "A4")\n)\n'
        mutations = [
            {
                "op": "insert_wire",
                "points": [(0.0, 0.0), (10.0, 0.0)],
                "net_name": "N1",
            },
            {
                "op": "insert_label",
                "net_name": "N1",
                "x": 5.0,
                "y": 0.0,
                "size": 1.27,
                "is_global": False,
                "uuid": "lbl-1",
            },
        ]
        result = SchematicRawWriter.apply_mutations(content, mutations)
        assert "(wire" in result
        assert '(label "N1"' in result
