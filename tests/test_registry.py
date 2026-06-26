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
    validate_dependencies,
    validate_conflicts,
    validate_registry_completeness,
    OpMeta,
)


class TestRegistryCompleteness:
    """Verify the registry has the expected number of operations."""

    def test_registry_has_98_operations(self) -> None:
        # Phase 101-06: 141 ops (was 124 -- two new aliases added:
        # delete_copper_zone and add_zone_keepout, plus prior phase additions)
        assert len(OPERATION_REGISTRY) == 142

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
            "pre_pcb_schematic_gate",
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
            "infer_connectivity",
            "classify_violations",
            "diagnose_violations",
            "list_lib_entries",
            "list_net_classes",
            "list_design_rules",
            "review_schematic",
            "analyze_split_plane",
            "detect_net_shorts",
            "analyze_ground_topology",
            "trace_net_from_label",
            "analyze_gaps",
            "gate_status",
            "run_gate_check",
            "get_constraints",
            "export_positions",
            "generate_bom",
        }
        assert readonly_types == expected_readonly
        assert len(readonly) == len(expected_readonly)

    def test_connect_pins_dependencies(self) -> None:
        deps = get_operation_dependencies("connect_pins")
        assert deps == ["resolve_pin_positions"]

    def test_batch_connect_dependencies(self) -> None:
        deps = get_operation_dependencies("batch_connect")
        assert "resolve_pin_positions" in deps
        assert "detect_routing_collisions" in deps

    def test_repair_schematic_dependencies(self) -> None:
        deps = get_operation_dependencies("repair_schematic")
        assert deps == ["parse_erc"]

    def test_regenerate_wiring_dependencies(self) -> None:
        deps = get_operation_dependencies("regenerate_wiring")
        assert deps == ["resolve_pin_positions"]

    def test_diagnose_violations_dependencies(self) -> None:
        deps = get_operation_dependencies("diagnose_violations")
        assert deps == ["classify_violations"]

    def test_erc_auto_fix_dependencies(self) -> None:
        deps = get_operation_dependencies("erc_auto_fix")
        assert deps == ["parse_erc"]

    def test_erc_auto_fix_hierarchical_dependencies(self) -> None:
        deps = get_operation_dependencies("erc_auto_fix_hierarchical")
        assert deps == ["parse_erc"]

    def test_fix_shorted_nets_dependencies(self) -> None:
        deps = get_operation_dependencies("fix_shorted_nets")
        assert deps == ["parse_erc"]

    def test_resolve_shorted_nets_dependencies(self) -> None:
        deps = get_operation_dependencies("resolve_shorted_nets")
        assert deps == ["parse_erc"]

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
            "snap_components_to_grid",
            "swap_symbol",
        ]
        assert op_types == expected
        assert len(ops) == 8

    def test_destructive_operations(self) -> None:
        ops = get_destructive_operations()
        op_types = {m.op_type for m in ops}
        expected = {
            "remove_component",
            "remove_net",
            "remove_wire",
            "remove_label",
            "remove_labels",
            "remove_junction",
            "remove_no_connect",
            "remove_lib_entry",
            "remove_net_class",
            "remove_design_rule",
            "remove_copper_zone",
            "remove_keepout_area",
            "remove_dangling_wires",
            "remove_dangling_tracks",
            "propagate_symbol_change",
        }
        assert op_types == expected


class TestValidateDependencies:
    """Test the validate_dependencies function."""

    def test_empty_list_returns_empty(self) -> None:
        assert validate_dependencies([]) == []

    def test_no_deps_needed(self) -> None:
        assert validate_dependencies(["add_component"]) == []

    def test_missing_single_prerequisite(self) -> None:
        assert validate_dependencies(["connect_pins"]) == ["resolve_pin_positions"]

    def test_satisfied_prerequisite(self) -> None:
        assert validate_dependencies(["resolve_pin_positions", "connect_pins"]) == []

    def test_chain_diagnose_violations(self) -> None:
        assert validate_dependencies(["diagnose_violations"]) == ["classify_violations"]
        assert validate_dependencies(["classify_violations", "diagnose_violations"]) == []

    def test_unknown_op_skipped(self) -> None:
        result = validate_dependencies(["nonexistent_op", "connect_pins"])
        assert result == ["resolve_pin_positions"]

    def test_repair_schematic_dependencies(self) -> None:
        deps = get_operation_dependencies("repair_schematic")
        assert deps == ["parse_erc"]

    def test_repair_schematic_no_deps_fails(self) -> None:
        assert validate_dependencies(["repair_schematic"]) == ["parse_erc"]

    def test_repair_schematic_with_parse_erc_passes(self) -> None:
        assert validate_dependencies(["parse_erc", "repair_schematic"]) == []


class TestValidateConflicts:
    """Test the validate_conflicts function."""

    def test_empty_list_returns_empty(self) -> None:
        assert validate_conflicts([]) == []

    def test_no_conflicts(self) -> None:
        assert validate_conflicts(["add_component", "add_wire"]) == []

    def test_repair_schematic_after_remove_component(self) -> None:
        result = validate_conflicts(["remove_component", "repair_schematic"])
        assert len(result) == 1
        assert "repair_schematic" in result[0]
        assert "remove_component" in result[0]

    def test_repair_schematic_before_remove_component_ok(self) -> None:
        """Conflict only detected when repair runs after remove, not before."""
        result = validate_conflicts(["repair_schematic", "remove_component"])
        assert result == []

    def test_batch_connect_needs_collision_detection(self) -> None:
        """batch_connect requires detect_routing_collisions in sequence."""
        result = validate_dependencies(["batch_connect"])
        assert "resolve_pin_positions" in result
        assert "detect_routing_collisions" in result

    def test_multi_file_ops_have_scope(self) -> None:
        """Verify ops with multi_file scope exist."""
        multi_file = [
            meta for meta in OPERATION_REGISTRY.values()
            if meta.scope == "multi_file"
        ]
        types = {m.op_type for m in multi_file}
        assert "array_replicate" in types
        assert "propagate_symbol_change" in types
