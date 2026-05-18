"""Tests for array_replicate operation -- TDD RED phase.

Verifies:
- ArrayReplicateOp validates with pattern type and required fields
- Linear array creates N components spaced by (dx, dy) from source
- Linear array with diagonal spacing increments both x and y
- Circular array creates N components distributed around a center point
- Circular array positions calculated using trigonometry (cos/sin)
- Matrix array creates rows*cols components in a grid pattern
- Matrix array positions calculated using row/col indices * spacing
- All replicated components have unique UUIDs and unique references
- ArrayReplicateError raised for invalid pattern parameters
- ArrayReplicateError raised when source not found
- OperationExecutor dispatches array_replicate correctly
- Full pipeline: validate -> executor -> array_replicate -> serialize -> file on disk
"""

import math
import shutil
import uuid
from pathlib import Path

import pytest

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.schema import ArrayReplicateOp, Operation, PositionSpec
from kicad_agent.parser import parse_schematic

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_ir_registry():
    """Clear the IR registry before and after each test."""
    _clear_registry()
    yield
    _clear_registry()


class TestArrayReplicateSchema:
    """Tests for ArrayReplicateOp schema validation."""

    def test_valid_linear_schema(self) -> None:
        """ArrayReplicateOp accepts valid linear pattern."""
        op = ArrayReplicateOp(
            target_file="test.kicad_sch",
            source_reference="R1",
            pattern="linear",
            count=5,
            spacing=PositionSpec(x=10.0, y=0.0),
        )
        assert op.pattern == "linear"
        assert op.count == 5

    def test_valid_circular_schema(self) -> None:
        """ArrayReplicateOp accepts valid circular pattern."""
        op = ArrayReplicateOp(
            target_file="test.kicad_sch",
            source_reference="R1",
            pattern="circular",
            count=4,
            spacing=PositionSpec(x=0.0, y=0.0),
            angle_step=90.0,
            center=PositionSpec(x=50.0, y=50.0),
        )
        assert op.pattern == "circular"
        assert op.angle_step == 90.0

    def test_valid_matrix_schema(self) -> None:
        """ArrayReplicateOp accepts valid matrix pattern."""
        op = ArrayReplicateOp(
            target_file="test.kicad_sch",
            source_reference="R1",
            pattern="matrix",
            count=6,
            spacing=PositionSpec(x=10.0, y=10.0),
            rows=2,
            cols=3,
        )
        assert op.pattern == "matrix"
        assert op.rows == 2
        assert op.cols == 3

    def test_operation_union_accepts_array_replicate(self) -> None:
        """Operation discriminated union accepts array_replicate op_type."""
        op = Operation.model_validate({
            "root": {
                "op_type": "array_replicate",
                "target_file": "test.kicad_sch",
                "source_reference": "R1",
                "pattern": "linear",
                "count": 3,
                "spacing": {"x": 10.0, "y": 0.0},
            }
        })
        assert op.root.op_type == "array_replicate"


class TestLinearArray:
    """Tests for linear array replication."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)
        return {"ir": ir, "file_path": dst, "parse_result": result}

    def test_linear_array_creates_n_components(self, setup_schematic: dict) -> None:
        """Linear array creates N components spaced by (dx, dy)."""
        from kicad_agent.ops.array_replicate import array_replicate

        source = setup_schematic["ir"].get_component_by_ref("J1")
        assert source is not None
        source_x = source.position.X

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="linear",
            count=5,
            spacing=PositionSpec(x=10.0, y=0.0),
        )
        result = array_replicate(op, setup_schematic["ir"])

        assert len(result["created"]) == 5

        # Verify x positions increment by 10 from source
        for i, comp_info in enumerate(result["created"]):
            comp = setup_schematic["ir"].get_component_by_ref(comp_info["reference"])
            assert comp is not None
            expected_x = source_x + 10.0 * (i + 1)
            assert comp.position.X == pytest.approx(expected_x)

    def test_linear_array_diagonal(self, setup_schematic: dict) -> None:
        """Linear array with diagonal spacing increments both x and y."""
        from kicad_agent.ops.array_replicate import array_replicate

        source = setup_schematic["ir"].get_component_by_ref("J1")
        assert source is not None
        source_x = source.position.X
        source_y = source.position.Y

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="linear",
            count=3,
            spacing=PositionSpec(x=5.0, y=5.0),
        )
        result = array_replicate(op, setup_schematic["ir"])

        assert len(result["created"]) == 3

        for i, comp_info in enumerate(result["created"]):
            comp = setup_schematic["ir"].get_component_by_ref(comp_info["reference"])
            assert comp is not None
            assert comp.position.X == pytest.approx(source_x + 5.0 * (i + 1))
            assert comp.position.Y == pytest.approx(source_y + 5.0 * (i + 1))


class TestCircularArray:
    """Tests for circular array replication."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)
        return {"ir": ir, "file_path": dst, "parse_result": result}

    def test_circular_array_creates_n_components(self, setup_schematic: dict) -> None:
        """Circular array creates N components distributed around center."""
        from kicad_agent.ops.array_replicate import array_replicate

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="circular",
            count=4,
            spacing=PositionSpec(x=0.0, y=0.0),
            angle_step=90.0,
            center=PositionSpec(x=50.0, y=50.0),
        )
        result = array_replicate(op, setup_schematic["ir"])

        assert len(result["created"]) == 4

    def test_circular_array_positions(self, setup_schematic: dict) -> None:
        """Circular array positions calculated using trigonometry (cos/sin)."""
        from kicad_agent.ops.array_replicate import array_replicate

        source = setup_schematic["ir"].get_component_by_ref("J1")
        assert source is not None

        center_x, center_y = 50.0, 50.0
        dx = source.position.X - center_x
        dy = source.position.Y - center_y
        angle_step_rad = math.radians(90.0)

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="circular",
            count=1,
            spacing=PositionSpec(x=0.0, y=0.0),
            angle_step=90.0,
            center=PositionSpec(x=center_x, y=center_y),
        )
        result = array_replicate(op, setup_schematic["ir"])

        comp = setup_schematic["ir"].get_component_by_ref(result["created"][0]["reference"])
        assert comp is not None

        # First replica: rotate (dx, dy) by angle_step
        cos_a = math.cos(angle_step_rad)
        sin_a = math.sin(angle_step_rad)
        expected_x = center_x + dx * cos_a - dy * sin_a
        expected_y = center_y + dx * sin_a + dy * cos_a

        assert comp.position.X == pytest.approx(expected_x, abs=0.01)
        assert comp.position.Y == pytest.approx(expected_y, abs=0.01)


class TestMatrixArray:
    """Tests for matrix array replication."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)
        return {"ir": ir, "file_path": dst, "parse_result": result}

    def test_matrix_array_creates_correct_count(self, setup_schematic: dict) -> None:
        """Matrix array creates (rows * cols - 1) components (excluding source)."""
        from kicad_agent.ops.array_replicate import array_replicate

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="matrix",
            count=6,
            spacing=PositionSpec(x=10.0, y=15.0),
            rows=2,
            cols=3,
        )
        result = array_replicate(op, setup_schematic["ir"])

        # 2 rows * 3 cols = 6 total, minus source at (0,0) = 5 created
        assert len(result["created"]) == 5

    def test_matrix_positions(self, setup_schematic: dict) -> None:
        """Matrix array positions calculated using row/col indices * spacing."""
        from kicad_agent.ops.array_replicate import array_replicate

        source = setup_schematic["ir"].get_component_by_ref("J1")
        assert source is not None
        source_x = source.position.X
        source_y = source.position.Y

        col_spacing = 10.0
        row_spacing = 15.0

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="matrix",
            count=4,
            spacing=PositionSpec(x=col_spacing, y=row_spacing),
            rows=2,
            cols=2,
        )
        result = array_replicate(op, setup_schematic["ir"])

        # 2x2 grid: source at (0,0), created at (0,1), (1,0), (1,1)
        assert len(result["created"]) == 3

        # Collect all positions (including source)
        positions = [(source_x, source_y)]
        for comp_info in result["created"]:
            comp = setup_schematic["ir"].get_component_by_ref(comp_info["reference"])
            assert comp is not None
            positions.append((comp.position.X, comp.position.Y))

        # Verify each position matches grid layout
        # Expected positions: (0,0), (col_spacing, 0), (0, row_spacing), (col_spacing, row_spacing)
        expected = [
            (source_x, source_y),
            (source_x + col_spacing, source_y),
            (source_x, source_y + row_spacing),
            (source_x + col_spacing, source_y + row_spacing),
        ]
        for exp_x, exp_y in expected:
            assert any(
                abs(px - exp_x) < 0.01 and abs(py - exp_y) < 0.01
                for px, py in positions
            ), f"Expected position ({exp_x}, {exp_y}) not found in {positions}"


class TestArrayReplicateErrors:
    """Tests for array_replicate error handling."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)
        return {"ir": ir, "file_path": dst, "parse_result": result}

    def test_circular_without_center_raises(self, setup_schematic: dict) -> None:
        """Circular array without center raises ArrayReplicateError."""
        from kicad_agent.ops.array_replicate import ArrayReplicateError, array_replicate

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="circular",
            count=4,
            spacing=PositionSpec(x=0.0, y=0.0),
            angle_step=90.0,
            # center is None -- should fail
        )
        with pytest.raises(ArrayReplicateError, match="center"):
            array_replicate(op, setup_schematic["ir"])

    def test_source_not_found_raises(self, setup_schematic: dict) -> None:
        """Array replicate raises ArrayReplicateError when source not found."""
        from kicad_agent.ops.array_replicate import ArrayReplicateError, array_replicate

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="X999",
            pattern="linear",
            count=3,
            spacing=PositionSpec(x=10.0, y=0.0),
        )
        with pytest.raises(ArrayReplicateError, match="not found"):
            array_replicate(op, setup_schematic["ir"])

    def test_circular_without_angle_step_raises(self, setup_schematic: dict) -> None:
        """Circular array without angle_step raises ArrayReplicateError."""
        from kicad_agent.ops.array_replicate import ArrayReplicateError, array_replicate

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="circular",
            count=4,
            spacing=PositionSpec(x=0.0, y=0.0),
            center=PositionSpec(x=50.0, y=50.0),
            # angle_step is None -- should fail
        )
        with pytest.raises(ArrayReplicateError, match="angle_step"):
            array_replicate(op, setup_schematic["ir"])

    def test_matrix_without_rows_raises(self, setup_schematic: dict) -> None:
        """Matrix array without rows raises ArrayReplicateError."""
        from kicad_agent.ops.array_replicate import ArrayReplicateError, array_replicate

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="matrix",
            count=6,
            spacing=PositionSpec(x=10.0, y=10.0),
            cols=3,
            # rows is None -- should fail
        )
        with pytest.raises(ArrayReplicateError, match="rows"):
            array_replicate(op, setup_schematic["ir"])


class TestArrayReplicateUniqueness:
    """Tests for unique references and UUIDs in array replication."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)
        return {"ir": ir, "file_path": dst, "parse_result": result}

    def test_unique_references(self, setup_schematic: dict) -> None:
        """All replicated components have unique references."""
        from kicad_agent.ops.array_replicate import array_replicate

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="linear",
            count=5,
            spacing=PositionSpec(x=10.0, y=0.0),
        )
        result = array_replicate(op, setup_schematic["ir"])

        refs = [c["reference"] for c in result["created"]]
        assert len(refs) == len(set(refs))

    def test_unique_uuids(self, setup_schematic: dict) -> None:
        """All replicated components have unique UUIDs."""
        from kicad_agent.ops.array_replicate import array_replicate

        op = ArrayReplicateOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            pattern="linear",
            count=5,
            spacing=PositionSpec(x=10.0, y=0.0),
        )
        result = array_replicate(op, setup_schematic["ir"])

        uuids = [c["uuid"] for c in result["created"]]
        assert len(uuids) == len(set(uuids))

        # All should be valid v4 UUIDs
        for u in uuids:
            assert uuid.UUID(u).version == 4


class TestArrayReplicateExecutor:
    """Tests for OperationExecutor dispatching array_replicate."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path for executor tests."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        return {"file_path": dst, "base_dir": tmp_path}

    def test_executor_dispatches_array_replicate(self, setup_schematic: dict) -> None:
        """OperationExecutor dispatches array_replicate correctly."""
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=setup_schematic["base_dir"])

        op = Operation.model_validate({
            "root": {
                "op_type": "array_replicate",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "source_reference": "J1",
                "pattern": "linear",
                "count": 3,
                "spacing": {"x": 10.0, "y": 0.0},
            }
        })

        result = executor.execute(op)
        assert result["success"] is True
        assert result["operation"] == "array_replicate"
        assert "created" in result["details"]

    def test_full_pipeline_array_replicate(self, setup_schematic: dict) -> None:
        """Full pipeline: validate -> executor -> array_replicate -> serialize -> file on disk."""
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=setup_schematic["base_dir"])

        op = Operation.model_validate({
            "root": {
                "op_type": "array_replicate",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "source_reference": "J1",
                "pattern": "linear",
                "count": 2,
                "spacing": {"x": 20.0, "y": 5.0},
            }
        })

        result = executor.execute(op)
        assert result["success"] is True

        # Re-parse the file and verify the replicated components exist
        re_parsed = parse_schematic(setup_schematic["file_path"])
        re_ir = SchematicIR(_parse_result=re_parsed)

        for comp_info in result["details"]["created"]:
            comp = re_ir.get_component_by_ref(comp_info["reference"])
            assert comp is not None
            parsed_uuid = uuid.UUID(comp.uuid)
            assert parsed_uuid.version == 4
