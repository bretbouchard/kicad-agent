"""Tests for net conflict detection -- detect_net_conflicts operation.

TDD RED phase: tests exercise detect_net_conflicts behavior against minimal
S-expression schematics. Tests cover:
  - Schema validation via Operation.model_validate
  - No conflicts: clean schematic returns empty conflicts
  - Shorted nets: two different labels at same position (error)
  - Case variants: VCC vs vcc labels (warning)
  - Mixed label types: same name as global + local (warning)
  - Unlabeled junctions: junction connecting 3+ wires with no label (warning)
  - Conflict stats: total_conflicts, errors, warnings
  - Disable checks: flags suppress corresponding conflicts
"""

from pathlib import Path

import pytest

from volta.ops._schema_schematic_intel import DetectNetConflictsOp
from volta.ops.schema import Operation


# ---------------------------------------------------------------------------
# Helpers: minimal schematic S-expression fixtures
# ---------------------------------------------------------------------------

SCHEMATIC_HEADER = """\
(kicad_sch (version 20250114) (generator "kicad-agent-test")
  (lib_symbols)
"""

SCHEMATIC_FOOTER = ")"


def _write_schematic(tmp_path: Path, content: str) -> Path:
    """Write content to a .kicad_sch file and return the path."""
    p = tmp_path / "test.kicad_sch"
    p.write_text(content)
    return p


def _clean_sch() -> str:
    """Schematic with one wire and one label -- no conflicts."""
    return (
        SCHEMATIC_HEADER
        + """
  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (global_label "SDA" (at 50.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
"""
        + SCHEMATIC_FOOTER
    )


def _shorted_nets_sch() -> str:
    """Schematic with two different labels at the same position (50.0, 50.0)."""
    return (
        SCHEMATIC_HEADER
        + """
  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (global_label "SDA" (at 50.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
  (global_label "SCL" (at 50.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
"""
        + SCHEMATIC_FOOTER
    )


def _case_variant_sch() -> str:
    """Schematic with VCC and vcc labels at different positions, connected by wire."""
    return (
        SCHEMATIC_HEADER
        + """
  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (global_label "VCC" (at 50.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
  (global_label "vcc" (at 100.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
"""
        + SCHEMATIC_FOOTER
    )


def _mixed_labels_sch() -> str:
    """Schematic with same name label as both global and local."""
    return (
        SCHEMATIC_HEADER
        + """
  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (global_label "SDA" (at 50.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
  (label "SDA" (at 100.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
"""
        + SCHEMATIC_FOOTER
    )


def _unlabeled_junction_sch() -> str:
    """Schematic with a junction at (100.0, 50.0) connecting 3 wires, no label."""
    return (
        SCHEMATIC_HEADER
        + """
  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (wire (pts (xy 100.0 50.0) (xy 150.0 50.0)))
  (wire (pts (xy 100.0 50.0) (xy 100.0 100.0)))
  (junction (at 100.0 50.0))
"""
        + SCHEMATIC_FOOTER
    )


# ===========================================================================
# Test: Schema validation
# ===========================================================================


class TestDetectNetConflictsSchema:
    """Validate DetectNetConflictsOp via Operation.model_validate."""

    def test_valid_minimal(self) -> None:
        """Operation.model_validate accepts detect_net_conflicts with just target_file."""
        op = Operation.model_validate({
            "root": {
                "op_type": "detect_net_conflicts",
                "target_file": "test.kicad_sch",
            }
        })
        assert op.root.op_type == "detect_net_conflicts"
        assert op.root.target_file == "test.kicad_sch"
        assert op.root.check_case_variants is True
        assert op.root.check_mixed_labels is True
        assert op.root.check_unlabeled_junctions is True

    def test_valid_with_all_fields(self) -> None:
        """Operation.model_validate accepts detect_net_conflicts with all fields."""
        op = Operation.model_validate({
            "root": {
                "op_type": "detect_net_conflicts",
                "target_file": "test.kicad_sch",
                "check_case_variants": False,
                "check_mixed_labels": False,
                "check_unlabeled_junctions": False,
            }
        })
        assert op.root.check_case_variants is False
        assert op.root.check_mixed_labels is False
        assert op.root.check_unlabeled_junctions is False

    def test_invalid_op_type_rejected(self) -> None:
        """Wrong op_type is rejected."""
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "detect_net_conflicts_WRONG",
                    "target_file": "test.kicad_sch",
                }
            })

    def test_detect_net_conflicts_op_direct(self) -> None:
        """DetectNetConflictsOp can be instantiated directly."""
        op = DetectNetConflictsOp(target_file="test.kicad_sch")
        assert op.op_type == "detect_net_conflicts"
        assert op.target_file == "test.kicad_sch"


# ===========================================================================
# Test: No conflicts
# ===========================================================================


class TestNoConflicts:
    """Clean schematic returns empty conflicts list."""

    def test_clean_schematic_no_conflicts(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _clean_sch())
        result = detect_net_conflicts(sch_path=sch_path)
        assert "conflicts" in result
        assert "stats" in result
        assert result["conflicts"] == []
        assert result["stats"]["total_conflicts"] == 0
        assert result["stats"]["errors"] == 0
        assert result["stats"]["warnings"] == 0


# ===========================================================================
# Test: Shorted nets
# ===========================================================================


class TestShortedNets:
    """Two different labels at same position produces shorted_nets conflict."""

    def test_shorted_nets_detected(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _shorted_nets_sch())
        result = detect_net_conflicts(sch_path=sch_path)
        conflicts = result["conflicts"]
        assert len(conflicts) >= 1, f"Expected at least 1 conflict, got {len(conflicts)}"

        shorted = [c for c in conflicts if c["conflict_type"] == "shorted_nets"]
        assert len(shorted) >= 1, f"Expected shorted_nets conflict, got types: {[c['conflict_type'] for c in conflicts]}"

        c = shorted[0]
        assert c["severity"] == "error"
        assert "SDA" in c["description"]
        assert "SCL" in c["description"]
        # Positions should include (50.0, 50.0)
        assert any(
            abs(p[0] - 50.0) < 0.1 and abs(p[1] - 50.0) < 0.1
            for p in c["positions"]
        ), f"Expected position near (50,50) in {c['positions']}"
        # Items should list both labels
        assert len(c["items"]) == 2
        names = {item["name"] for item in c["items"]}
        assert names == {"SDA", "SCL"}


# ===========================================================================
# Test: Case variants
# ===========================================================================


class TestCaseVariants:
    """Labels VCC and vcc produce case_variant conflict with severity warning."""

    def test_case_variant_detected(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _case_variant_sch())
        result = detect_net_conflicts(sch_path=sch_path)
        conflicts = result["conflicts"]
        case_variants = [c for c in conflicts if c["conflict_type"] == "case_variant"]
        assert len(case_variants) >= 1, f"Expected case_variant conflict, got types: {[c['conflict_type'] for c in conflicts]}"

        c = case_variants[0]
        assert c["severity"] == "warning"
        # Items should include both VCC and vcc
        names = {item["name"] for item in c["items"]}
        assert "VCC" in names or "vcc" in names, f"Expected VCC/vcc in items: {c['items']}"


# ===========================================================================
# Test: Mixed label types
# ===========================================================================


class TestMixedLabelTypes:
    """Same name as both global and local label produces mixed_label_types conflict."""

    def test_mixed_labels_detected(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _mixed_labels_sch())
        result = detect_net_conflicts(sch_path=sch_path)
        conflicts = result["conflicts"]
        mixed = [c for c in conflicts if c["conflict_type"] == "mixed_label_types"]
        assert len(mixed) >= 1, f"Expected mixed_label_types conflict, got types: {[c['conflict_type'] for c in conflicts]}"

        c = mixed[0]
        assert c["severity"] == "warning"
        assert "SDA" in c["description"]
        # Items should show different label_type values
        label_types = {item["label_type"] for item in c["items"]}
        assert len(label_types) >= 2, f"Expected 2+ label types, got: {label_types}"


# ===========================================================================
# Test: Unlabeled junctions
# ===========================================================================


class TestUnlabeledJunction:
    """Junction with 3+ wire endpoints and no label produces unlabeled_junction conflict."""

    def test_unlabeled_junction_detected(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _unlabeled_junction_sch())
        result = detect_net_conflicts(sch_path=sch_path)
        conflicts = result["conflicts"]
        unlabeled = [c for c in conflicts if c["conflict_type"] == "unlabeled_junction"]
        assert len(unlabeled) >= 1, f"Expected unlabeled_junction conflict, got types: {[c['conflict_type'] for c in conflicts]}"

        c = unlabeled[0]
        assert c["severity"] == "warning"
        # Position should be near (100.0, 50.0) -- the junction position
        assert any(
            abs(p[0] - 100.0) < 0.1 and abs(p[1] - 50.0) < 0.1
            for p in c["positions"]
        ), f"Expected position near (100,50) in {c['positions']}"


# ===========================================================================
# Test: Conflict structure
# ===========================================================================


class TestConflictStructure:
    """Each conflict dict contains required keys."""

    def test_conflict_has_required_keys(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _shorted_nets_sch())
        result = detect_net_conflicts(sch_path=sch_path)
        for c in result["conflicts"]:
            assert "conflict_type" in c, f"Missing conflict_type: {c}"
            assert "severity" in c, f"Missing severity: {c}"
            assert "description" in c, f"Missing description: {c}"
            assert "positions" in c, f"Missing positions: {c}"
            assert "items" in c, f"Missing items: {c}"
            assert c["severity"] in ("error", "warning"), f"Invalid severity: {c['severity']}"
            assert isinstance(c["positions"], list), f"positions not a list: {c}"
            assert isinstance(c["items"], list), f"items not a list: {c}"


# ===========================================================================
# Test: Conflict stats
# ===========================================================================


class TestConflictStats:
    """Stats accurately reflect conflict counts."""

    def test_stats_consistency(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _shorted_nets_sch())
        result = detect_net_conflicts(sch_path=sch_path)
        stats = result["stats"]
        errors = stats["errors"]
        warnings = stats["warnings"]
        total = stats["total_conflicts"]
        assert total == errors + warnings, (
            f"total_conflicts ({total}) != errors ({errors}) + warnings ({warnings})"
        )
        assert total == len(result["conflicts"]), (
            f"total_conflicts ({total}) != len(conflicts) ({len(result['conflicts'])})"
        )

    def test_shorted_nets_increments_errors(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _shorted_nets_sch())
        result = detect_net_conflicts(sch_path=sch_path)
        assert result["stats"]["errors"] >= 1


# ===========================================================================
# Test: Disable checks
# ===========================================================================


class TestDisableChecks:
    """Individual checks can be disabled via schema flags."""

    def test_disable_case_variants(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _case_variant_sch())
        result = detect_net_conflicts(
            sch_path=sch_path,
            check_case_variants=False,
        )
        case_variants = [c for c in result["conflicts"] if c["conflict_type"] == "case_variant"]
        assert len(case_variants) == 0, (
            f"case_variant should be suppressed when check_case_variants=False, "
            f"got: {case_variants}"
        )

    def test_disable_mixed_labels(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _mixed_labels_sch())
        result = detect_net_conflicts(
            sch_path=sch_path,
            check_mixed_labels=False,
        )
        mixed = [c for c in result["conflicts"] if c["conflict_type"] == "mixed_label_types"]
        assert len(mixed) == 0, (
            f"mixed_label_types should be suppressed when check_mixed_labels=False, "
            f"got: {mixed}"
        )

    def test_disable_unlabeled_junctions(self, tmp_path: Path) -> None:
        from volta.schematic_routing.conflict_detector import detect_net_conflicts
        sch_path = _write_schematic(tmp_path, _unlabeled_junction_sch())
        result = detect_net_conflicts(
            sch_path=sch_path,
            check_unlabeled_junctions=False,
        )
        unlabeled = [c for c in result["conflicts"] if c["conflict_type"] == "unlabeled_junction"]
        assert len(unlabeled) == 0, (
            f"unlabeled_junction should be suppressed when check_unlabeled_junctions=False, "
            f"got: {unlabeled}"
        )
