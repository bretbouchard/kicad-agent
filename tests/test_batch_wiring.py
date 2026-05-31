"""Tests for BatchWiring -- batch connect and regenerate wiring operations.

TDD RED phase: tests written before implementation.
Tests cover:
  1. BatchConnectOp validates with target_file, nets, global_labels, strategy, collision_zones
  2. RegenerateWiringOp validates with target_file, nets, global_labels, no_connect_positions, strategy
  3. BatchWiring.batch_connect() processes 3 nets and returns aggregate stats
  4. BatchWiring.batch_connect() auto-detects collision zones when none provided
  5. BatchWiring.batch_connect() generates global labels at specified positions
  6. BatchWiring.regenerate_wiring() strips existing wires/labels/no_connects from schematic
  7. BatchWiring.regenerate_wiring() then connects all nets and adds global labels and no_connects
  8. BatchWiring.regenerate_wiring() returns removed counts and generated counts
  9. Both schemas reject invalid target_file
  10. BatchConnectOp rejects empty nets list
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.ops._schema_schematic_routing import (
    BatchConnectOp,
    GlobalLabelSpec,
    NetDef,
    RegenerateWiringOp,
)
from kicad_agent.ops.schema import PositionSpec


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_mock_connector(net_results: dict) -> MagicMock:
    """Create a mock NetConnector whose connect_pins returns pre-defined results.

    Args:
        net_results: Dict mapping net_name -> connect_pins return dict.
    """
    connector = MagicMock()
    connector.connect_pins.side_effect = lambda net_name, pins, **kwargs: net_results.get(
        net_name,
        {
            "net_name": net_name,
            "wires_generated": 0,
            "labels_generated": 0,
            "collisions_avoided": 0,
            "wires": [],
            "labels": [],
            "notes": [],
        },
    )
    return connector


def _mock_net_result(net_name, wires=0, labels=2, collisions=0):
    """Create a mock connect_pins result for a single net."""
    return {
        "net_name": net_name,
        "wires_generated": wires,
        "labels_generated": labels,
        "collisions_avoided": collisions,
        "wires": [{"start": (0, 0), "end": (10, 10), "sexpr": "wire"}] * wires,
        "labels": [{"position": (0, 0), "sexpr": "label", "ref": "R1", "pin": "1"}] * labels,
        "notes": [],
    }


def _mock_schematic_content():
    """Create a minimal .kicad_sch file content with wires, labels, and no_connects."""
    return """(kicad_sch
  (version 20250114)
  (generator "kicad")
  (uuid "test-uuid")
  (paper "A4")
  (lib_symbols)
  (wire (pts (xy 10 10) (xy 20 20)))
  (wire (pts (xy 30 30) (xy 40 40)))
  (label "NET_A" (at 50 50 0) (effects (font (size 0.75 0.75))))
  (global_label "VCC" (shape bidirectional) (at 60 60 0) (effects (font (size 1 1))))
  (no_connect (at 70 70))
  (symbol (lib_id "Device:R") (at 80 80 0))
)
"""


# ---------------------------------------------------------------------------
# Test 1: BatchConnectOp schema validation
# ---------------------------------------------------------------------------


class TestBatchConnectOpSchema:
    """Validate BatchConnectOp accepts valid and rejects invalid input."""

    def test_valid_op_with_all_fields(self):
        op = BatchConnectOp(
            target_file="schematic.kicad_sch",
            nets=[
                {"name": "VCC", "pins": [{"ref": "R55", "pin": "1"}, {"ref": "R56", "pin": "1"}]},
                {"name": "GND", "pins": [{"ref": "R55", "pin": "2"}]},
            ],
            global_labels=[
                {"name": "VCC", "position": {"x": 50.0, "y": 50.0}, "shape": "bidirectional"},
            ],
            strategy="hybrid",
            collision_zones=[{"direction": "vertical", "coordinate": 59.69}],
        )
        assert op.op_type == "batch_connect"
        assert len(op.nets) == 2
        assert op.nets[0].name == "VCC"
        assert len(op.nets[0].pins) == 2
        assert op.strategy == "hybrid"
        assert len(op.global_labels) == 1
        assert op.global_labels[0].name == "VCC"
        assert len(op.collision_zones) == 1

    def test_default_strategy_is_hybrid(self):
        op = BatchConnectOp(
            target_file="schematic.kicad_sch",
            nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
        )
        assert op.strategy == "hybrid"

    def test_auto_detect_collisions_default_true(self):
        op = BatchConnectOp(
            target_file="schematic.kicad_sch",
            nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
        )
        assert op.auto_detect_collisions is True

    def test_rejects_path_traversal(self):
        with pytest.raises(Exception):
            BatchConnectOp(
                target_file="../../../etc/passwd",
                nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
            )

    def test_rejects_unsafe_net_name(self):
        """T-38-04-01: net name rejects S-expression injection."""
        with pytest.raises(Exception):
            BatchConnectOp(
                target_file="schematic.kicad_sch",
                nets=[{"name": 'VCC") (hack', "pins": [{"ref": "R1", "pin": "1"}]}],
            )

    def test_rejects_unsafe_global_label_name(self):
        """T-38-04-01: global label name rejects S-expression injection."""
        with pytest.raises(Exception):
            BatchConnectOp(
                target_file="schematic.kicad_sch",
                nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
                global_labels=[{"name": 'GLBL") (hack', "position": {"x": 50, "y": 50}}],
            )

    def test_nets_max_200(self):
        """T-38-04-03: nets list limited to max 200 entries."""
        nets = [{"name": f"N{i}", "pins": [{"ref": "R1", "pin": "1"}]} for i in range(201)]
        with pytest.raises(Exception):
            BatchConnectOp(
                target_file="schematic.kicad_sch",
                nets=nets,
            )

    def test_collision_zones_max_50(self):
        """collision_zones limited to max 50 entries."""
        zones = [{"direction": "vertical", "coordinate": float(i)} for i in range(51)]
        with pytest.raises(Exception):
            BatchConnectOp(
                target_file="schematic.kicad_sch",
                nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
                collision_zones=zones,
            )


# ---------------------------------------------------------------------------
# Test 2: RegenerateWiringOp schema validation
# ---------------------------------------------------------------------------


class TestRegenerateWiringOpSchema:
    """Validate RegenerateWiringOp accepts valid and rejects invalid input."""

    def test_valid_op_with_all_fields(self):
        op = RegenerateWiringOp(
            target_file="schematic.kicad_sch",
            nets=[
                {"name": "VCC", "pins": [{"ref": "R55", "pin": "1"}]},
            ],
            global_labels=[
                {"name": "VCC", "position": {"x": 50.0, "y": 50.0}, "shape": "bidirectional"},
            ],
            no_connect_positions=[{"x": 70.0, "y": 70.0}],
            strategy="wire_first",
            collision_zones=[{"direction": "vertical", "coordinate": 59.69}],
        )
        assert op.op_type == "regenerate_wiring"
        assert len(op.nets) == 1
        assert len(op.no_connect_positions) == 1
        assert op.strategy == "wire_first"

    def test_default_no_connect_positions_empty(self):
        op = RegenerateWiringOp(
            target_file="schematic.kicad_sch",
            nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
        )
        assert op.no_connect_positions == []

    def test_rejects_path_traversal(self):
        with pytest.raises(Exception):
            RegenerateWiringOp(
                target_file="../../etc/shadow",
                nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
            )


# ---------------------------------------------------------------------------
# Test 9: Both schemas reject invalid target_file
# ---------------------------------------------------------------------------


class TestSchemaTargetFileValidation:
    """Both schemas must reject invalid target_file."""

    def test_batch_connect_rejects_non_kicad_file(self):
        with pytest.raises(Exception):
            BatchConnectOp(
                target_file="not_a_kicad_file.txt",
                nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
            )

    def test_regenerate_wiring_rejects_non_kicad_file(self):
        with pytest.raises(Exception):
            RegenerateWiringOp(
                target_file="not_a_kicad_file.txt",
                nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
            )

    def test_batch_connect_rejects_absolute_path(self):
        with pytest.raises(Exception):
            BatchConnectOp(
                target_file="/absolute/path.kicad_sch",
                nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
            )

    def test_regenerate_wiring_rejects_absolute_path(self):
        with pytest.raises(Exception):
            RegenerateWiringOp(
                target_file="/absolute/path.kicad_sch",
                nets=[{"name": "NET", "pins": [{"ref": "R1", "pin": "1"}]}],
            )


# ---------------------------------------------------------------------------
# Test 10: BatchConnectOp rejects empty nets list
# ---------------------------------------------------------------------------


class TestBatchConnectOpEmptyNets:
    """BatchConnectOp must reject empty nets list."""

    def test_rejects_empty_nets_list(self):
        with pytest.raises(Exception):
            BatchConnectOp(
                target_file="schematic.kicad_sch",
                nets=[],
            )


# ---------------------------------------------------------------------------
# Tests 3-8: BatchWiring functionality
# ---------------------------------------------------------------------------


class TestBatchWiring:
    """Test BatchWiring batch_connect and regenerate_wiring."""

    def _make_batch_wiring(self, mock_connector=None, mock_detector=None):
        """Create a BatchWiring instance with mocked dependencies.

        Patches NetConnector and CollisionDetector so that the actual
        schematic file is not needed.
        """
        from kicad_agent.schematic_routing.batch_wiring import BatchWiring

        tmpdir = tempfile.mkdtemp()
        tmpfile = Path(tmpdir) / "test.kicad_sch"
        tmpfile.write_text("(kicad_sch)", encoding="utf-8")

        patches = []

        connector_ctx = patch(
            "kicad_agent.schematic_routing.batch_wiring.NetConnector",
            return_value=mock_connector or _make_mock_connector({}),
        )
        detector_ctx = patch(
            "kicad_agent.schematic_routing.batch_wiring.CollisionDetector",
            return_value=mock_detector or MagicMock(),
        )

        connector_mock = connector_ctx.start()
        detector_mock = detector_ctx.start()
        patches.extend([connector_ctx, detector_ctx])

        wiring = BatchWiring(tmpfile)

        for p in patches:
            p.stop()

        # Re-patch for method calls
        with patch(
            "kicad_agent.schematic_routing.batch_wiring.NetConnector",
            return_value=mock_connector or _make_mock_connector({}),
        ), patch(
            "kicad_agent.schematic_routing.batch_wiring.CollisionDetector",
            return_value=mock_detector or MagicMock(),
        ):
            wiring2 = BatchWiring(tmpfile)

        return wiring2

    def test_batch_connect_processes_3_nets(self):
        """Test 3: batch_connect processes 3 nets and returns aggregate stats."""
        net_results = {
            "NET_A": _mock_net_result("NET_A", wires=1, labels=2),
            "NET_B": _mock_net_result("NET_B", wires=2, labels=3),
            "NET_C": _mock_net_result("NET_C", wires=0, labels=1),
        }
        mock_connector = _make_mock_connector(net_results)
        wiring = self._make_batch_wiring(mock_connector=mock_connector)

        result = wiring.batch_connect(
            nets=[
                {"name": "NET_A", "pins": [{"ref": "R1", "pin": "1"}, {"ref": "R2", "pin": "1"}]},
                {"name": "NET_B", "pins": [{"ref": "R3", "pin": "1"}, {"ref": "R4", "pin": "1"}]},
                {"name": "NET_C", "pins": [{"ref": "R5", "pin": "1"}]},
            ],
        )
        assert result["nets_processed"] == 3
        assert result["wires_generated"] == 3  # 1 + 2 + 0
        assert result["labels_generated"] == 6  # 2 + 3 + 1
        assert "notes" in result

    def test_batch_connect_auto_detects_collision_zones(self):
        """Test 4: auto-detects collision zones when none provided."""
        net_results = {
            "NET_A": _mock_net_result("NET_A", wires=0, labels=1),
        }
        mock_connector = _make_mock_connector(net_results)
        mock_detector = MagicMock()
        mock_detector.detect_routing_collisions.return_value = [
            {"direction": "vertical", "coordinate": 95.25, "range": (60, 80),
             "pins": [], "description": "test zone"},
        ]

        wiring = self._make_batch_wiring(
            mock_connector=mock_connector,
            mock_detector=mock_detector,
        )

        result = wiring.batch_connect(
            nets=[{"name": "NET_A", "pins": [{"ref": "R1", "pin": "1"}]}],
            collision_zones=None,
            auto_detect_collisions=True,
        )
        # Should have called detect_routing_collisions
        assert result["collisions_detected"] >= 1
        # The collision zones should be passed to connect_pins
        call_args = mock_connector.connect_pins.call_args
        zones_passed = call_args[1].get("collision_zones") if call_args[1] else call_args[0][3] if len(call_args[0]) > 3 else None
        # Either positional or keyword, zones should have been passed
        assert zones_passed is not None and len(zones_passed) > 0

    def test_batch_connect_generates_global_labels(self):
        """Test 5: generates global labels at specified positions."""
        mock_connector = _make_mock_connector({
            "NET_A": _mock_net_result("NET_A", wires=0, labels=1),
        })
        wiring = self._make_batch_wiring(mock_connector=mock_connector)

        result = wiring.batch_connect(
            nets=[{"name": "NET_A", "pins": [{"ref": "R1", "pin": "1"}]}],
            global_labels=[
                {"name": "VCC", "position": (50.0, 60.0), "shape": "bidirectional"},
                {"name": "GND", "position": (70.0, 80.0), "shape": "input"},
            ],
        )
        assert result["global_labels_generated"] == 2
        gl_list = result.get("global_labels", [])
        assert len(gl_list) == 2
        # Verify position data is present
        assert gl_list[0]["name"] == "VCC"
        assert gl_list[0]["position"] == (50.0, 60.0)

    def test_regenerate_wiring_strips_existing_content(self):
        """Test 6: strips existing wires/labels/no_connects from schematic body."""
        from kicad_agent.schematic_routing.batch_wiring import BatchWiring

        tmpdir = tempfile.mkdtemp()
        tmpfile = Path(tmpdir) / "test.kicad_sch"
        tmpfile.write_text(_mock_schematic_content(), encoding="utf-8")

        mock_connector = _make_mock_connector({
            "NET_A": _mock_net_result("NET_A", wires=0, labels=1),
        })

        with patch(
            "kicad_agent.schematic_routing.batch_wiring.NetConnector",
            return_value=mock_connector,
        ), patch(
            "kicad_agent.schematic_routing.batch_wiring.CollisionDetector",
            return_value=MagicMock(),
        ):
            wiring = BatchWiring(tmpfile)
            result = wiring.regenerate_wiring(
                nets=[{"name": "NET_A", "pins": [{"ref": "R1", "pin": "1"}]}],
            )

        # Should report removed counts
        assert "removed" in result
        assert result["removed"]["wires"] == 2
        assert result["removed"]["labels"] == 2  # 1 local + 1 global
        assert result["removed"]["no_connects"] == 1

    def test_regenerate_wiring_connects_nets_and_adds_labels(self):
        """Test 7: connects all nets and adds global labels and no_connects."""
        from kicad_agent.schematic_routing.batch_wiring import BatchWiring

        tmpdir = tempfile.mkdtemp()
        tmpfile = Path(tmpdir) / "test.kicad_sch"
        tmpfile.write_text(_mock_schematic_content(), encoding="utf-8")

        mock_connector = _make_mock_connector({
            "NET_A": _mock_net_result("NET_A", wires=1, labels=2),
            "NET_B": _mock_net_result("NET_B", wires=0, labels=3),
        })

        with patch(
            "kicad_agent.schematic_routing.batch_wiring.NetConnector",
            return_value=mock_connector,
        ), patch(
            "kicad_agent.schematic_routing.batch_wiring.CollisionDetector",
            return_value=MagicMock(),
        ):
            wiring = BatchWiring(tmpfile)
            result = wiring.regenerate_wiring(
                nets=[
                    {"name": "NET_A", "pins": [{"ref": "R1", "pin": "1"}]},
                    {"name": "NET_B", "pins": [{"ref": "R2", "pin": "1"}]},
                ],
                global_labels=[
                    {"name": "VCC", "position": (50.0, 50.0), "shape": "bidirectional"},
                ],
                no_connect_positions=[{"x": 100.0, "y": 100.0}],
            )

        assert "generated" in result
        assert result["generated"]["wires"] == 1
        assert result["generated"]["net_labels"] == 5  # 2 + 3
        assert result["generated"]["global_labels"] == 1
        assert result["generated"]["no_connects"] == 1

    def test_regenerate_wiring_returns_removed_and_generated_counts(self):
        """Test 8: returns removed counts and generated counts."""
        from kicad_agent.schematic_routing.batch_wiring import BatchWiring

        tmpdir = tempfile.mkdtemp()
        tmpfile = Path(tmpdir) / "test.kicad_sch"
        tmpfile.write_text(_mock_schematic_content(), encoding="utf-8")

        mock_connector = _make_mock_connector({
            "NET_A": _mock_net_result("NET_A", wires=0, labels=1),
        })

        with patch(
            "kicad_agent.schematic_routing.batch_wiring.NetConnector",
            return_value=mock_connector,
        ), patch(
            "kicad_agent.schematic_routing.batch_wiring.CollisionDetector",
            return_value=MagicMock(),
        ):
            wiring = BatchWiring(tmpfile)
            result = wiring.regenerate_wiring(
                nets=[{"name": "NET_A", "pins": [{"ref": "R1", "pin": "1"}]}],
            )

        # Verify return structure has both removed and generated
        assert "removed" in result
        assert "generated" in result
        assert isinstance(result["removed"]["wires"], int)
        assert isinstance(result["removed"]["labels"], int)
        assert isinstance(result["removed"]["no_connects"], int)
        assert isinstance(result["generated"]["wires"], int)
        assert isinstance(result["generated"]["net_labels"], int)
        assert isinstance(result["generated"]["global_labels"], int)
        assert isinstance(result["generated"]["no_connects"], int)
        assert "notes" in result


# ---------------------------------------------------------------------------
# NetDef and GlobalLabelSpec validation
# ---------------------------------------------------------------------------


class TestNetDefSchema:
    """Validate NetDef helper schema."""

    def test_valid_net_def(self):
        nd = NetDef(
            name="VCC",
            pins=[{"ref": "R55", "pin": "1"}, {"ref": "R56", "pin": "2"}],
        )
        assert nd.name == "VCC"
        assert len(nd.pins) == 2

    def test_rejects_empty_name(self):
        with pytest.raises(Exception):
            NetDef(name="", pins=[{"ref": "R1", "pin": "1"}])

    def test_rejects_unsafe_name(self):
        """T-38-04-01: rejects S-expression injection in net name."""
        with pytest.raises(Exception):
            NetDef(name='VCC") (hack', pins=[{"ref": "R1", "pin": "1"}])

    def test_rejects_empty_pins(self):
        with pytest.raises(Exception):
            NetDef(name="VCC", pins=[])

    def test_pins_max_100(self):
        pins = [{"ref": f"R{i}", "pin": "1"} for i in range(101)]
        with pytest.raises(Exception):
            NetDef(name="VCC", pins=pins)


class TestGlobalLabelSpecSchema:
    """Validate GlobalLabelSpec helper schema."""

    def test_valid_global_label_spec(self):
        gls = GlobalLabelSpec(
            name="VCC",
            position={"x": 50.0, "y": 60.0, "angle": 0},
            shape="bidirectional",
        )
        assert gls.name == "VCC"
        assert gls.shape == "bidirectional"

    def test_default_shape_is_bidirectional(self):
        gls = GlobalLabelSpec(
            name="NET",
            position={"x": 0.0, "y": 0.0},
        )
        assert gls.shape == "bidirectional"

    def test_rejects_unsafe_name(self):
        """T-38-04-01: rejects S-expression injection in global label name."""
        with pytest.raises(Exception):
            GlobalLabelSpec(
                name='GLBL") (hack',
                position={"x": 0.0, "y": 0.0},
            )
