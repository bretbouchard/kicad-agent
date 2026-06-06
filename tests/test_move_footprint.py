"""Tests for move_footprint operation (#39).

Covers:
- MoveFootprintOp schema validation
- Executor registration
- Position update via PcbRawWriter
- Round-trip with fixture
"""

import tempfile
from pathlib import Path

import pytest

from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ops.executor import OperationExecutor
from kicad_agent.ops.schema import Operation
from kicad_agent.parser import parse_pcb
from kicad_agent.parser.uuid_extractor import extract_uuids
from kiutils.board import Board
from kiutils.items.common import Net, Position
from kiutils.items.gritems import GrLine
from kiutils.footprint import Footprint, Pad


@pytest.fixture(autouse=True)
def _clear_ir_registry():
    """Clear IR registry between tests."""
    from kicad_agent.ir.base import _clear_registry
    _clear_registry()


def _create_pcb_with_footprint(
    tmpdir: Path, ref: str = "R1", x: float = 50.0, y: float = 30.0
) -> tuple[Path, PcbIR]:
    """Create a PCB with a single footprint for testing."""
    pcb_path = tmpdir / "test.kicad_pcb"
    board = Board.create_new()
    board.general.thickness = 1.6
    board.nets.append(Net(number=0, name=""))
    board.nets.append(Net(number=1, name="GND"))

    # Add board outline
    corners = [
        (Position(X=0, Y=0), Position(X=100, Y=0)),
        (Position(X=100, Y=0), Position(X=100, Y=80)),
        (Position(X=100, Y=80), Position(X=0, Y=80)),
        (Position(X=0, Y=80), Position(X=0, Y=0)),
    ]
    for start, end in corners:
        board.graphicItems.append(
            GrLine(start=start, end=end, layer="Edge.Cuts", width=0.15)
        )

    # Add a footprint
    fp = Footprint()
    fp.libId = "Resistor_SMD:R_0805"
    fp.position = Position(X=x, Y=y)
    fp.rotation = 90.0
    fp.layer = "F.Cu"
    fp.properties["Reference"] = ref
    fp.properties["Value"] = "10k"
    fp.pads.append(
        Pad(
            number="1",
            type="smd",
            shape="rect",
            position=Position(X=-0.9, Y=0),
            layers=["F.Cu", "F.Paste", "F.Mask"],
            size=Position(X=1.0, Y=1.2),
        )
    )
    fp.pads.append(
        Pad(
            number="2",
            type="smd",
            shape="rect",
            position=Position(X=0.9, Y=0),
            layers=["F.Cu", "F.Paste", "F.Mask"],
            size=Position(X=1.0, Y=1.2),
        )
    )
    board.footprints.append(fp)
    board.to_file(str(pcb_path))

    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
    return pcb_path, ir


class TestMoveFootprintSchema:
    """MoveFootprintOp Pydantic schema validation."""

    def test_schema_validation(self):
        """Schema validates with required fields."""
        from kicad_agent.ops._schema_pcb import MoveFootprintOp
        op = MoveFootprintOp(
            target_file="test.kicad_pcb",
            reference="R1",
            x=75.0,
            y=50.0,
        )
        assert op.op_type == "move_footprint"
        assert op.reference == "R1"
        assert op.angle == 0.0

    def test_schema_with_angle(self):
        """Schema validates with explicit angle."""
        from kicad_agent.ops._schema_pcb import MoveFootprintOp
        op = MoveFootprintOp(
            target_file="test.kicad_pcb",
            reference="R1",
            x=10.0,
            y=20.0,
            angle=180.0,
        )
        assert op.angle == 180.0

    def test_schema_empty_reference_rejected(self):
        """Empty reference is rejected."""
        from kicad_agent.ops._schema_pcb import MoveFootprintOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            MoveFootprintOp(
                target_file="test.kicad_pcb",
                reference="",
                x=10.0,
                y=20.0,
            )


class TestMoveFootprintOperation:
    """Move footprint via executor."""

    def test_move_footprint_updates_position(self):
        """Execute move_footprint via executor, verify position changed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            pcb_path, ir = _create_pcb_with_footprint(tmpdir_path, "R1", 50.0, 30.0)

            op = Operation.model_validate({
                "root": {
                    "op_type": "move_footprint",
                    "target_file": pcb_path.name,
                    "reference": "R1",
                    "x": 75.0,
                    "y": 55.0,
                    "angle": 0.0,
                }
            })

            executor = OperationExecutor(base_dir=tmpdir_path)
            result = executor.execute(op)

            assert result["success"] is True
            assert result["operation"] == "move_footprint"
            assert result["details"]["reference"] == "R1"
            assert result["details"]["x"] == 75.0
            assert result["details"]["y"] == 55.0

            # Verify position on disk
            content = pcb_path.read_text(encoding="utf-8")
            assert "(at 75.000000 55.000000 0.000000)" in content

    def test_move_footprint_unknown_ref_fails(self):
        """Moving unknown reference raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            pcb_path, _ = _create_pcb_with_footprint(tmpdir_path, "R1", 50.0, 30.0)

            op = Operation.model_validate({
                "root": {
                    "op_type": "move_footprint",
                    "target_file": pcb_path.name,
                    "reference": "X99",
                    "x": 10.0,
                    "y": 20.0,
                }
            })

            executor = OperationExecutor(base_dir=tmpdir_path)
            with pytest.raises(ValueError, match="not found"):
                executor.execute(op)

    def test_operation_union_validates_move_footprint(self):
        """MoveFootprintOp validates through Operation discriminated union."""
        op = Operation.model_validate({
            "root": {
                "op_type": "move_footprint",
                "target_file": "test.kicad_pcb",
                "reference": "R1",
                "x": 10.0,
                "y": 20.0,
            }
        })
        assert op.root.op_type == "move_footprint"
