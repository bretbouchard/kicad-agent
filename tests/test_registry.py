"""Tests for the unified operation registry."""

import pytest

from kicad_agent.ops.registry import (
    OPERATION_REGISTRY,
    VALID_CATEGORIES,
    get_destructive_operations,
    get_operation_dependencies,
    get_operations_by_category,
    get_operations_for_file_type,
    get_readonly_operations,
    validate_registry_completeness,
    OpMeta,
)


class TestRegistryCompleteness:
    """Verify the registry has the expected number of operations."""

    def test_registry_has_89_operations(self) -> None:
        # 88 from catalog + review_schematic added for schema completeness
        assert len(OPERATION_REGISTRY) == 89

    def test_validate_registry_completeness_passes(self) -> None:
        result = validate_registry_completeness()
        assert result["missing_from_registry"] == [], (
            f"Missing from registry: {result['missing_from_registry']}"
        )
        assert result["extra_in_registry"] == [], (
            f"Extra in registry: {result['extra_in_registry']}"
        )

    def test_every_op_has_nonempty_description_and_category(self) -> None:
        for op_type, meta in OPERATION_REGISTRY.items():
            assert meta.description, f"{op_type} has empty description"
            assert meta.category, f"{op_type} has empty category"

    def test_all_categories_are_valid(self) -> None:
        for op_type, meta in OPERATION_REGISTRY.items():
            assert meta.category in VALID_CATEGORIES, (
                f"{op_type} has unknown category: {meta.category!r}"
            )


class TestOpMetaModel:
    """Verify OpMeta model structure."""

    def test_all_entries_are_opmeta(self) -> None:
        for op_type, meta in OPERATION_REGISTRY.items():
            assert isinstance(meta, OpMeta), f"{op_type} is not an OpMeta instance"

    def test_file_types_nonempty(self) -> None:
        for op_type, meta in OPERATION_REGISTRY.items():
            assert meta.file_types, f"{op_type} has empty file_types"

    def test_scope_is_valid(self) -> None:
        valid_scopes = {"single_point", "single_file", "multi_file"}
        for op_type, meta in OPERATION_REGISTRY.items():
            assert meta.scope in valid_scopes, (
                f"{op_type} has invalid scope: {meta.scope!r}"
            )

    def test_op_type_matches_key(self) -> None:
        for key, meta in OPERATION_REGISTRY.items():
            assert meta.op_type == key, (
                f"Key {key!r} does not match op_type {meta.op_type!r}"
            )


class TestQueryFunctions:
    """Test the registry query functions."""

    def test_schematic_ops(self) -> None:
        ops = get_operations_for_file_type(".kicad_sch")
        op_types = {m.op_type for m in ops}
        # Spot-check a few operations that must be schematic-only
        assert "add_component" in op_types
        assert "add_wire" in op_types
        assert "repair_schematic" in op_types
        assert "review_schematic" in op_types
        # PCB-only ops should NOT be present
        assert "auto_route" not in op_types
        assert "set_board_outline" not in op_types

    def test_pcb_ops(self) -> None:
        ops = get_operations_for_file_type(".kicad_pcb")
        op_types = {m.op_type for m in ops}
        assert "auto_route" in op_types
        assert "add_copper_zone" in op_types
        assert "query_connectivity" in op_types

    def test_readonly_operations_count(self) -> None:
        readonly = get_readonly_operations()
        # The catalog READ_ONLY_OPS frozenset has 11, plus the additional
        # read-only ops from routing, schematic_intel, erc_smart, and readability
        # categories. Verify count matches is_readonly=True in registry.
        readonly_types = {m.op_type for m in readonly}
        # All declared readonly ops must have is_readonly=True
        expected_readonly = {
            "query_connectivity",
            "navigate_hierarchy",
            "validate_power_nets",
            "validate_schematic",
            "parse_erc",
            "extract_violation_positions",
            "validate_hlabels",
            "cross_ref_check",
            "validate_refs",
            "validate_footprint",
            "verify_pin_map",
            "resolve_pin_positions",
            "detect_routing_collisions",
            "detect_pin_overlaps",
            "extract_nets",
            "detect_net_conflicts",
            "suggest_net_names",
            "classify_violations",
            "diagnose_violations",
            "list_lib_entries",
            "list_net_classes",
            "list_design_rules",
            "review_schematic",
        }
        assert readonly_types == expected_readonly
        assert len(readonly) == len(expected_readonly)

    def test_connect_pins_dependencies(self) -> None:
        deps = get_operation_dependencies("connect_pins")
        assert deps == ["resolve_pin_positions"]

    def test_batch_connect_dependencies(self) -> None:
        deps = get_operation_dependencies("batch_connect")
        assert deps == ["resolve_pin_positions"]

    def test_regenerate_wiring_dependencies(self) -> None:
        deps = get_operation_dependencies("regenerate_wiring")
        assert deps == ["resolve_pin_positions"]

    def test_unknown_op_raises_keyerror(self) -> None:
        with pytest.raises(KeyError, match="nonexistent_op"):
            get_operation_dependencies("nonexistent_op")

    def test_component_category(self) -> None:
        ops = get_operations_by_category("component")
        op_types = [m.op_type for m in ops]
        expected = [
            "add_component",
            "remove_component",
            "move_component",
            "modify_property",
            "duplicate_component",
            "array_replicate",
        ]
        assert op_types == expected
        assert len(ops) == 6

    def test_destructive_operations(self) -> None:
        ops = get_destructive_operations()
        op_types = {m.op_type for m in ops}
        expected = {
            "remove_component",
            "remove_net",
            "remove_wire",
            "remove_label",
            "remove_junction",
            "remove_no_connect",
            "remove_lib_entry",
            "remove_net_class",
            "remove_design_rule",
            "remove_copper_zone",
            "remove_dangling_wires",
            "propagate_symbol_change",
        }
        assert op_types == expected
