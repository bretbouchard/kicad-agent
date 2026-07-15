"""Tests for remove operation handlers -- remove_wire, remove_label, remove_junction, remove_no_connect.

Verifies:
- Basic removal of wire, label, junction, no_connect by UUID
- Wire removal refused when endpoint would be dangling
- Wire removal allowed when endpoint has remaining wire connections or pin
- Label removal dispatches to correct list based on label_type
- Error on UUID not found for each type
- Junction and no-connect removal edge cases
- Executor dispatch (validate JSON -> handler -> result)
"""

import shutil
from pathlib import Path

import pytest

from volta.ir.base import _clear_registry
from volta.ir.schematic_ir import SchematicIR
from volta.ops.schema import Operation
from volta.parser import parse_schematic
from volta.serializer import serialize_schematic


@pytest.fixture(autouse=True)
def _reset_ir_registry():
    """Clear the IR registry before and after each test."""
    _clear_registry()
    yield
    _clear_registry()


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestRemoveWire:
    """Tests for the remove_wire operation handler."""

    @pytest.fixture
    def schematic_with_wire(self, tmp_path: Path) -> dict:
        """Create a schematic with a wire, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)

        # Add three wires forming a connected path:
        # (0,0)->(10,0) -> (10,0)->(10,10)
        # (0,0)->(0,10)  (connects to start of first wire)
        ir.add_wire(start_x=0.0, start_y=0.0, end_x=10.0, end_y=0.0)
        ir.add_wire(start_x=10.0, start_y=0.0, end_x=10.0, end_y=10.0)
        ir.add_wire(start_x=0.0, start_y=0.0, end_x=0.0, end_y=10.0)

        return {"ir": ir, "file_path": dst}

    def _get_wire_uuid_at(self, ir, sx, sy, ex, ey):
        """Find a wire UUID matching given coordinates."""
        for w in ir.get_wire_endpoints():
            if (
                abs(w["start_x"] - sx) < 0.001
                and abs(w["start_y"] - sy) < 0.001
                and abs(w["end_x"] - ex) < 0.001
                and abs(w["end_y"] - ey) < 0.001
            ):
                return w["uuid"]
        return None

    def test_removes_wire_by_uuid(self, schematic_with_wire: dict) -> None:
        """remove_wire removes a wire from graphicalItems by UUID."""
        from volta.ops._schema_remove import RemoveWireOp
        from volta.ops.remove_ops import remove_wire

        ir = schematic_with_wire["ir"]
        wire_uuid = self._get_wire_uuid_at(ir, 0.0, 0.0, 10.0, 0.0)
        assert wire_uuid is not None, "Test wire not found"

        initial_count = len(ir.get_wire_endpoints())
        op = RemoveWireOp(target_file="test.kicad_sch", uuid=wire_uuid)
        result = remove_wire(op, ir, schematic_with_wire["file_path"], schematic_with_wire["file_path"].parent)

        assert result["success"] is True
        assert result["uuid"] == wire_uuid
        assert result["op_type"] == "remove_wire"
        assert len(ir.get_wire_endpoints()) == initial_count - 1

    def test_wire_removal_refused_dangling_endpoint(self, schematic_with_wire: dict) -> None:
        """remove_wire raises error when removal would leave endpoint dangling."""
        from volta.ops._schema_remove import RemoveWireOp
        from volta.ops.remove_ops import RemoveOpError, remove_wire

        ir = schematic_with_wire["ir"]

        # Add a standalone wire with no connections at (100,0)->(200,0)
        ir.add_wire(start_x=100.0, start_y=0.0, end_x=200.0, end_y=0.0)
        _clear_registry()
        ir2 = SchematicIR(_parse_result=ir._parse_result)

        wire_uuid = self._get_wire_uuid_at(ir2, 100.0, 0.0, 200.0, 0.0)
        assert wire_uuid is not None, "Standalone wire not found"

        op = RemoveWireOp(target_file="test.kicad_sch", uuid=wire_uuid)
        with pytest.raises(RemoveOpError, match="dangling"):
            remove_wire(op, ir2, schematic_with_wire["file_path"], schematic_with_wire["file_path"].parent)

    def test_wire_removal_allowed_with_remaining_wire(self, schematic_with_wire: dict) -> None:
        """remove_wire succeeds when endpoint has remaining wire connections."""
        from volta.ops._schema_remove import RemoveWireOp
        from volta.ops.remove_ops import remove_wire

        ir = schematic_with_wire["ir"]

        # The wire (0,0)->(10,0) shares endpoint (10,0) with (10,0)->(10,10)
        # But (0,0) has no connection -- so this should still be refused
        # Let's add a third wire at (0,0) to make both endpoints connected
        ir.add_wire(start_x=0.0, start_y=0.0, end_x=0.0, end_y=10.0)
        _clear_registry()
        ir2 = SchematicIR(_parse_result=ir._parse_result)

        wire_uuid = self._get_wire_uuid_at(ir2, 0.0, 0.0, 10.0, 0.0)
        assert wire_uuid is not None

        op = RemoveWireOp(target_file="test.kicad_sch", uuid=wire_uuid)
        result = remove_wire(op, ir2, schematic_with_wire["file_path"], schematic_with_wire["file_path"].parent)
        assert result["success"] is True

    def test_wire_removal_allowed_with_pin_at_endpoint(self, tmp_path: Path) -> None:
        """remove_wire succeeds when endpoint has a component pin."""
        from volta.ops._schema_remove import RemoveWireOp
        from volta.ops.remove_ops import remove_wire

        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)

        # Find a pin position
        pins = ir.get_pin_positions()
        assert len(pins) > 0, "No pins found in fixture"
        pin = pins[0]

        # Add a wire that starts at the pin position
        ir.add_wire(start_x=pin["x"], start_y=pin["y"], end_x=pin["x"] + 10.0, end_y=pin["y"])

        # Add another wire at the end to make that endpoint connected
        ir.add_wire(
            start_x=pin["x"] + 10.0, start_y=pin["y"],
            end_x=pin["x"] + 20.0, end_y=pin["y"],
        )

        _clear_registry()
        ir2 = SchematicIR(_parse_result=ir._parse_result)

        wire_uuid = self._get_wire_uuid_at(ir2, pin["x"], pin["y"], pin["x"] + 10.0, pin["y"])
        assert wire_uuid is not None

        op = RemoveWireOp(target_file="test.kicad_sch", uuid=wire_uuid)
        # Start endpoint has pin, end endpoint has remaining wire
        result = remove_wire(op, ir2, dst, dst.parent)
        assert result["success"] is True

    def test_error_on_wire_uuid_not_found(self, schematic_with_wire: dict) -> None:
        """remove_wire raises RemoveOpError when UUID not found."""
        from volta.ops._schema_remove import RemoveWireOp
        from volta.ops.remove_ops import RemoveOpError, remove_wire

        op = RemoveWireOp(target_file="test.kicad_sch", uuid="nonexistent-uuid-1234")
        with pytest.raises(RemoveOpError, match="not found"):
            remove_wire(op, schematic_with_wire["ir"], schematic_with_wire["file_path"], schematic_with_wire["file_path"].parent)

    def test_wire_removal_records_mutation(self, schematic_with_wire: dict) -> None:
        """remove_wire records mutation in IR mutation log."""
        from volta.ops._schema_remove import RemoveWireOp
        from volta.ops.remove_ops import remove_wire

        ir = schematic_with_wire["ir"]
        ir.add_wire(start_x=0.0, start_y=0.0, end_x=0.0, end_y=10.0)
        _clear_registry()
        ir2 = SchematicIR(_parse_result=ir._parse_result)

        wire_uuid = self._get_wire_uuid_at(ir2, 0.0, 0.0, 10.0, 0.0)
        assert wire_uuid is not None

        initial_mutations = len(ir2.mutation_log)
        op = RemoveWireOp(target_file="test.kicad_sch", uuid=wire_uuid)
        remove_wire(op, ir2, schematic_with_wire["file_path"], schematic_with_wire["file_path"].parent)

        assert len(ir2.mutation_log) == initial_mutations + 1
        last = ir2.mutation_log[-1]
        assert last["type"] == "remove_wire"
        assert last["uuid"] == wire_uuid


class TestRemoveLabel:
    """Tests for the remove_label operation handler."""

    @pytest.fixture
    def schematic_with_labels(self, tmp_path: Path) -> dict:
        """Create a schematic with labels of all three types."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)

        ir.add_label(name="TEST_LOCAL", label_type="local", x=10.0, y=10.0)
        ir.add_label(name="TEST_GLOBAL", label_type="global", x=20.0, y=20.0)
        ir.add_label(name="TEST_HIER", label_type="hierarchical", x=30.0, y=30.0)

        return {"ir": ir, "file_path": dst}

    def _find_label_uuid(self, ir, name, label_type):
        """Find a label UUID by name and type."""
        for lp in ir.get_label_positions():
            if lp["name"] == name and lp["label_type"] == label_type:
                # Use get_label_by_uuid after searching by position
                sch = ir._parse_result.kiutils_obj
                if label_type == "local":
                    for l in sch.labels:
                        if l.text == name:
                            return l.uuid
                elif label_type == "global":
                    for l in sch.globalLabels:
                        if l.text == name:
                            return l.uuid
                elif label_type == "hierarchical":
                    for l in sch.hierarchicalLabels:
                        if l.text == name:
                            return l.uuid
        return None

    def test_removes_local_label(self, schematic_with_labels: dict) -> None:
        """remove_label removes a local label by UUID."""
        from volta.ops._schema_remove import RemoveLabelOp
        from volta.ops.remove_ops import remove_label

        ir = schematic_with_labels["ir"]
        uuid = self._find_label_uuid(ir, "TEST_LOCAL", "local")
        assert uuid is not None

        op = RemoveLabelOp(target_file="test.kicad_sch", uuid=uuid, label_type="local")
        result = remove_label(op, ir, schematic_with_labels["file_path"], schematic_with_labels["file_path"].parent)

        assert result["success"] is True
        assert result["uuid"] == uuid
        assert ir.get_label_by_uuid(uuid) is None

    def test_removes_global_label(self, schematic_with_labels: dict) -> None:
        """remove_label removes a global label by UUID."""
        from volta.ops._schema_remove import RemoveLabelOp
        from volta.ops.remove_ops import remove_label

        ir = schematic_with_labels["ir"]
        uuid = self._find_label_uuid(ir, "TEST_GLOBAL", "global")
        assert uuid is not None

        op = RemoveLabelOp(target_file="test.kicad_sch", uuid=uuid, label_type="global")
        result = remove_label(op, ir, schematic_with_labels["file_path"], schematic_with_labels["file_path"].parent)
        assert result["success"] is True
        assert ir.get_label_by_uuid(uuid) is None

    def test_removes_hierarchical_label(self, schematic_with_labels: dict) -> None:
        """remove_label removes a hierarchical label by UUID."""
        from volta.ops._schema_remove import RemoveLabelOp
        from volta.ops.remove_ops import remove_label

        ir = schematic_with_labels["ir"]
        uuid = self._find_label_uuid(ir, "TEST_HIER", "hierarchical")
        assert uuid is not None

        op = RemoveLabelOp(target_file="test.kicad_sch", uuid=uuid, label_type="hierarchical")
        result = remove_label(op, ir, schematic_with_labels["file_path"], schematic_with_labels["file_path"].parent)
        assert result["success"] is True
        assert ir.get_label_by_uuid(uuid) is None

    def test_error_on_label_uuid_not_found(self, schematic_with_labels: dict) -> None:
        """remove_label raises RemoveOpError when UUID not found."""
        from volta.ops._schema_remove import RemoveLabelOp
        from volta.ops.remove_ops import RemoveOpError, remove_label

        op = RemoveLabelOp(target_file="test.kicad_sch", uuid="nonexistent-uuid", label_type="local")
        with pytest.raises(RemoveOpError, match="not found"):
            remove_label(op, schematic_with_labels["ir"], schematic_with_labels["file_path"], schematic_with_labels["file_path"].parent)

    def test_label_removal_records_mutation(self, schematic_with_labels: dict) -> None:
        """remove_label records mutation in IR mutation log."""
        from volta.ops._schema_remove import RemoveLabelOp
        from volta.ops.remove_ops import remove_label

        ir = schematic_with_labels["ir"]
        uuid = self._find_label_uuid(ir, "TEST_LOCAL", "local")
        assert uuid is not None

        initial_mutations = len(ir.mutation_log)
        op = RemoveLabelOp(target_file="test.kicad_sch", uuid=uuid, label_type="local")
        remove_label(op, ir, schematic_with_labels["file_path"], schematic_with_labels["file_path"].parent)

        assert len(ir.mutation_log) == initial_mutations + 1
        last = ir.mutation_log[-1]
        assert last["type"] == "remove_label"
        assert last["uuid"] == uuid
        assert last["label_type"] == "local"


class TestRemoveJunction:
    """Tests for the remove_junction operation handler."""

    @pytest.fixture
    def schematic_with_junction(self, tmp_path: Path) -> dict:
        """Create a schematic with junction dots."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)

        ir.add_junction(x=50.0, y=50.0)
        ir.add_junction(x=100.0, y=100.0)

        return {"ir": ir, "file_path": dst}

    def test_removes_junction_by_uuid(self, schematic_with_junction: dict) -> None:
        """remove_junction removes a junction by UUID."""
        from volta.ops._schema_remove import RemoveJunctionOp
        from volta.ops.remove_ops import remove_junction

        ir = schematic_with_junction["ir"]
        jct = ir.get_junction_by_uuid(
            ir._parse_result.kiutils_obj.junctions[-2].uuid
        )
        assert jct is not None

        initial_count = len(ir._parse_result.kiutils_obj.junctions)
        op = RemoveJunctionOp(target_file="test.kicad_sch", uuid=jct.uuid)
        result = remove_junction(op, ir, schematic_with_junction["file_path"], schematic_with_junction["file_path"].parent)

        assert result["success"] is True
        assert result["uuid"] == jct.uuid
        assert len(ir._parse_result.kiutils_obj.junctions) == initial_count - 1

    def test_error_on_junction_uuid_not_found(self, schematic_with_junction: dict) -> None:
        """remove_junction raises RemoveOpError when UUID not found."""
        from volta.ops._schema_remove import RemoveJunctionOp
        from volta.ops.remove_ops import RemoveOpError, remove_junction

        op = RemoveJunctionOp(target_file="test.kicad_sch", uuid="nonexistent-uuid")
        with pytest.raises(RemoveOpError, match="not found"):
            remove_junction(op, schematic_with_junction["ir"], schematic_with_junction["file_path"], schematic_with_junction["file_path"].parent)

    def test_junction_count_decreases(self, schematic_with_junction: dict) -> None:
        """After removal, junction count decreased by exactly 1."""
        from volta.ops._schema_remove import RemoveJunctionOp
        from volta.ops.remove_ops import remove_junction

        ir = schematic_with_junction["ir"]
        junctions = ir._parse_result.kiutils_obj.junctions
        jct_uuid = junctions[-1].uuid

        initial_count = len(junctions)
        op = RemoveJunctionOp(target_file="test.kicad_sch", uuid=jct_uuid)
        remove_junction(op, ir, schematic_with_junction["file_path"], schematic_with_junction["file_path"].parent)

        assert len(ir._parse_result.kiutils_obj.junctions) == initial_count - 1

    def test_other_junctions_unchanged(self, schematic_with_junction: dict) -> None:
        """Removing one junction does not affect other junctions."""
        from volta.ops._schema_remove import RemoveJunctionOp
        from volta.ops.remove_ops import remove_junction

        ir = schematic_with_junction["ir"]
        junctions = ir._parse_result.kiutils_obj.junctions
        remove_uuid = junctions[-1].uuid
        keep_uuid = junctions[-2].uuid

        op = RemoveJunctionOp(target_file="test.kicad_sch", uuid=remove_uuid)
        remove_junction(op, ir, schematic_with_junction["file_path"], schematic_with_junction["file_path"].parent)

        assert ir.get_junction_by_uuid(keep_uuid) is not None
        assert ir.get_junction_by_uuid(remove_uuid) is None

    def test_junction_removal_records_mutation(self, schematic_with_junction: dict) -> None:
        """remove_junction records mutation in IR mutation log."""
        from volta.ops._schema_remove import RemoveJunctionOp
        from volta.ops.remove_ops import remove_junction

        ir = schematic_with_junction["ir"]
        jct_uuid = ir._parse_result.kiutils_obj.junctions[-1].uuid

        initial_mutations = len(ir.mutation_log)
        op = RemoveJunctionOp(target_file="test.kicad_sch", uuid=jct_uuid)
        remove_junction(op, ir, schematic_with_junction["file_path"], schematic_with_junction["file_path"].parent)

        assert len(ir.mutation_log) == initial_mutations + 1
        last = ir.mutation_log[-1]
        assert last["type"] == "remove_junction"
        assert last["uuid"] == jct_uuid


class TestRemoveNoConnect:
    """Tests for the remove_no_connect operation handler."""

    @pytest.fixture
    def schematic_with_no_connect(self, tmp_path: Path) -> dict:
        """Create a schematic with no-connect flags."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "test.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)

        ir.add_no_connect(x=50.0, y=50.0)
        ir.add_no_connect(x=100.0, y=100.0)

        return {"ir": ir, "file_path": dst}

    def test_removes_no_connect_by_uuid(self, schematic_with_no_connect: dict) -> None:
        """remove_no_connect removes a no-connect flag by UUID."""
        from volta.ops._schema_remove import RemoveNoConnectOp
        from volta.ops.remove_ops import remove_no_connect

        ir = schematic_with_no_connect["ir"]
        nc = ir.get_no_connect_by_uuid(
            ir._parse_result.kiutils_obj.noConnects[-2].uuid
        )
        assert nc is not None

        initial_count = len(ir._parse_result.kiutils_obj.noConnects)
        op = RemoveNoConnectOp(target_file="test.kicad_sch", uuid=nc.uuid)
        result = remove_no_connect(op, ir, schematic_with_no_connect["file_path"], schematic_with_no_connect["file_path"].parent)

        assert result["success"] is True
        assert result["uuid"] == nc.uuid
        assert len(ir._parse_result.kiutils_obj.noConnects) == initial_count - 1

    def test_error_on_no_connect_uuid_not_found(self, schematic_with_no_connect: dict) -> None:
        """remove_no_connect raises RemoveOpError when UUID not found."""
        from volta.ops._schema_remove import RemoveNoConnectOp
        from volta.ops.remove_ops import RemoveOpError, remove_no_connect

        op = RemoveNoConnectOp(target_file="test.kicad_sch", uuid="nonexistent-uuid")
        with pytest.raises(RemoveOpError, match="not found"):
            remove_no_connect(op, schematic_with_no_connect["ir"], schematic_with_no_connect["file_path"], schematic_with_no_connect["file_path"].parent)

    def test_no_connect_count_decreases(self, schematic_with_no_connect: dict) -> None:
        """After removal, no-connect count decreased by exactly 1."""
        from volta.ops._schema_remove import RemoveNoConnectOp
        from volta.ops.remove_ops import remove_no_connect

        ir = schematic_with_no_connect["ir"]
        nc_uuid = ir._parse_result.kiutils_obj.noConnects[-1].uuid
        initial_count = len(ir._parse_result.kiutils_obj.noConnects)

        op = RemoveNoConnectOp(target_file="test.kicad_sch", uuid=nc_uuid)
        remove_no_connect(op, ir, schematic_with_no_connect["file_path"], schematic_with_no_connect["file_path"].parent)

        assert len(ir._parse_result.kiutils_obj.noConnects) == initial_count - 1

    def test_other_no_connects_unchanged(self, schematic_with_no_connect: dict) -> None:
        """Removing one no-connect does not affect other no-connects."""
        from volta.ops._schema_remove import RemoveNoConnectOp
        from volta.ops.remove_ops import remove_no_connect

        ir = schematic_with_no_connect["ir"]
        ncs = ir._parse_result.kiutils_obj.noConnects
        remove_uuid = ncs[-1].uuid
        keep_uuid = ncs[-2].uuid

        op = RemoveNoConnectOp(target_file="test.kicad_sch", uuid=remove_uuid)
        remove_no_connect(op, ir, schematic_with_no_connect["file_path"], schematic_with_no_connect["file_path"].parent)

        assert ir.get_no_connect_by_uuid(keep_uuid) is not None
        assert ir.get_no_connect_by_uuid(remove_uuid) is None

    def test_no_connect_removal_records_mutation(self, schematic_with_no_connect: dict) -> None:
        """remove_no_connect records mutation in IR mutation log."""
        from volta.ops._schema_remove import RemoveNoConnectOp
        from volta.ops.remove_ops import remove_no_connect

        ir = schematic_with_no_connect["ir"]
        nc_uuid = ir._parse_result.kiutils_obj.noConnects[-1].uuid

        initial_mutations = len(ir.mutation_log)
        op = RemoveNoConnectOp(target_file="test.kicad_sch", uuid=nc_uuid)
        remove_no_connect(op, ir, schematic_with_no_connect["file_path"], schematic_with_no_connect["file_path"].parent)

        assert len(ir.mutation_log) == initial_mutations + 1
        last = ir.mutation_log[-1]
        assert last["type"] == "remove_no_connect"
        assert last["uuid"] == nc_uuid


class TestExecutorDispatchRemoveOps:
    """Tests for OperationExecutor dispatching remove operations."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture, add elements for removal."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        return {"file_path": dst, "base_dir": tmp_path}

    def test_executor_dispatches_remove_junction(self, setup_schematic: dict) -> None:
        """OperationExecutor dispatches remove_junction op_type correctly."""
        from volta.ops.executor import OperationExecutor

        base_dir = setup_schematic["base_dir"]
        file_path = setup_schematic["file_path"]

        # First add a junction via executor
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_junction",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "position": {"x": 50.0, "y": 50.0},
            }
        })
        executor = OperationExecutor(base_dir=base_dir)
        executor.execute(add_op)

        # Now find its UUID and remove it
        _clear_registry()
        result = parse_schematic(file_path)
        ir = SchematicIR(_parse_result=result)
        junctions = ir._parse_result.kiutils_obj.junctions
        assert len(junctions) > 0
        jct_uuid = junctions[-1].uuid
        _clear_registry()

        remove_op = Operation.model_validate({
            "root": {
                "op_type": "remove_junction",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "uuid": jct_uuid,
            }
        })
        result = executor.execute(remove_op)
        assert result["success"] is True
        assert result["operation"] == "remove_junction"

    def test_executor_dispatches_remove_no_connect(self, setup_schematic: dict) -> None:
        """OperationExecutor dispatches remove_no_connect op_type correctly."""
        from volta.ops.executor import OperationExecutor

        base_dir = setup_schematic["base_dir"]
        file_path = setup_schematic["file_path"]

        # First add a no_connect via executor
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_no_connect",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "position": {"x": 50.0, "y": 50.0},
            }
        })
        executor = OperationExecutor(base_dir=base_dir)
        executor.execute(add_op)

        # Find UUID and remove
        _clear_registry()
        result = parse_schematic(file_path)
        ir = SchematicIR(_parse_result=result)
        ncs = ir._parse_result.kiutils_obj.noConnects
        assert len(ncs) > 0
        nc_uuid = ncs[-1].uuid
        _clear_registry()

        remove_op = Operation.model_validate({
            "root": {
                "op_type": "remove_no_connect",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "uuid": nc_uuid,
            }
        })
        result = executor.execute(remove_op)
        assert result["success"] is True
        assert result["operation"] == "remove_no_connect"

    def test_executor_dispatches_remove_label(self, setup_schematic: dict) -> None:
        """OperationExecutor dispatches remove_label op_type correctly."""
        from volta.ops.executor import OperationExecutor

        base_dir = setup_schematic["base_dir"]
        file_path = setup_schematic["file_path"]

        # Add a local label
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_label",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "name": "TEST_NET",
                "label_type": "local",
                "position": {"x": 10.0, "y": 10.0},
            }
        })
        executor = OperationExecutor(base_dir=base_dir)
        executor.execute(add_op)

        # Find UUID and remove
        _clear_registry()
        result = parse_schematic(file_path)
        ir = SchematicIR(_parse_result=result)
        labels = ir._parse_result.kiutils_obj.labels
        target = None
        for l in labels:
            if l.text == "TEST_NET":
                target = l
                break
        assert target is not None
        label_uuid = target.uuid
        _clear_registry()

        remove_op = Operation.model_validate({
            "root": {
                "op_type": "remove_label",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "uuid": label_uuid,
                "label_type": "local",
            }
        })
        result = executor.execute(remove_op)
        assert result["success"] is True
        assert result["operation"] == "remove_label"

    def test_executor_dispatches_remove_wire(self, setup_schematic: dict) -> None:
        """OperationExecutor dispatches remove_wire op_type correctly."""
        from volta.ops.executor import OperationExecutor

        base_dir = setup_schematic["base_dir"]
        file_path = setup_schematic["file_path"]

        # Add three wires via executor so they are serialized to disk:
        # (0,0)->(10,0), (10,0)->(10,10), (0,0)->(0,10)
        # This gives both endpoints of the first wire a remaining connection.
        executor = OperationExecutor(base_dir=base_dir)

        executor.execute(Operation.model_validate({
            "root": {
                "op_type": "add_wire",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "start_x": 0.0, "start_y": 0.0,
                "end_x": 10.0, "end_y": 0.0,
            }
        }))
        executor.execute(Operation.model_validate({
            "root": {
                "op_type": "add_wire",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "start_x": 10.0, "start_y": 0.0,
                "end_x": 10.0, "end_y": 10.0,
            }
        }))
        executor.execute(Operation.model_validate({
            "root": {
                "op_type": "add_wire",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "start_x": 0.0, "start_y": 0.0,
                "end_x": 0.0, "end_y": 10.0,
            }
        }))

        # Find first wire UUID from disk
        _clear_registry()
        result = parse_schematic(file_path)
        ir = SchematicIR(_parse_result=result)

        wire_uuid = None
        for w in ir.get_wire_endpoints():
            if (
                abs(w["start_x"] - 0.0) < 0.001
                and abs(w["start_y"] - 0.0) < 0.001
                and abs(w["end_x"] - 10.0) < 0.001
                and abs(w["end_y"] - 0.0) < 0.001
            ):
                wire_uuid = w["uuid"]
                break
        assert wire_uuid is not None, "Wire not found"
        _clear_registry()

        remove_op = Operation.model_validate({
            "root": {
                "op_type": "remove_wire",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "uuid": wire_uuid,
            }
        })
        result = executor.execute(remove_op)
        assert result["success"] is True
        assert result["operation"] == "remove_wire"

    def test_full_pipeline_remove_junction(self, setup_schematic: dict) -> None:
        """Full pipeline: validate -> add junction -> remove -> verify on disk."""
        from volta.ops.executor import OperationExecutor

        base_dir = setup_schematic["base_dir"]
        file_path = setup_schematic["file_path"]
        executor = OperationExecutor(base_dir=base_dir)

        # Add junction
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_junction",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "position": {"x": 77.0, "y": 88.0},
            }
        })
        executor.execute(add_op)

        # Find UUID
        _clear_registry()
        parsed = parse_schematic(file_path)
        ir = SchematicIR(_parse_result=parsed)
        jct_uuid = ir._parse_result.kiutils_obj.junctions[-1].uuid
        initial_count = len(ir._parse_result.kiutils_obj.junctions)
        _clear_registry()

        # Remove
        remove_op = Operation.model_validate({
            "root": {
                "op_type": "remove_junction",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "uuid": jct_uuid,
            }
        })
        result = executor.execute(remove_op)
        assert result["success"] is True

        # Verify on disk
        _clear_registry()
        re_parsed = parse_schematic(file_path)
        re_ir = SchematicIR(_parse_result=re_parsed)
        assert len(re_ir._parse_result.kiutils_obj.junctions) == initial_count - 1
        assert re_ir.get_junction_by_uuid(jct_uuid) is None

    def test_executor_returns_error_details_on_missing_uuid(self, setup_schematic: dict) -> None:
        """Executor returns failure when UUID not found."""
        from volta.ops.executor import OperationExecutor

        base_dir = setup_schematic["base_dir"]
        executor = OperationExecutor(base_dir=base_dir)

        remove_op = Operation.model_validate({
            "root": {
                "op_type": "remove_junction",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "uuid": "nonexistent-uuid-xyz",
            }
        })

        with pytest.raises(Exception):
            executor.execute(remove_op)
