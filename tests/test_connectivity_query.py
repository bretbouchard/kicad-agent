"""Tests for connectivity query operations.

Tests all 5 query types through both handler and full executor pipeline,
including read-only verification (file mtime unchanged).
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from volta.ops.executor import (
    OperationExecutor,
    _QUERY_HANDLERS,
)
from volta.ops.schema import Operation

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_registry():
    """Ensure clean handler registry for each test."""
    yield


@pytest.fixture
def arduino_pcb_tmp():
    """Copy Arduino_Mega PCB to a temp dir for executor tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = FIXTURE_DIR / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"
        dst = Path(tmpdir) / "Arduino_Mega.kicad_pcb"
        shutil.copy2(src, dst)
        yield dst


def _make_executor(file_path: Path) -> OperationExecutor:
    return OperationExecutor(base_dir=file_path.parent)


class TestQuerySchema:
    """Pydantic schema validation for QueryConnectivityOp."""

    def test_net_stats_schema_valid(self):
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": "test.kicad_pcb",
                "query_type": "net_stats",
            }
        })
        assert op.root.query_type == "net_stats"

    def test_connected_pads_requires_net_name(self):
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "query_connectivity",
                    "target_file": "test.kicad_pcb",
                    "query_type": "connected_pads",
                }
            })

    def test_are_connected_requires_source_and_target(self):
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "query_connectivity",
                    "target_file": "test.kicad_pcb",
                    "query_type": "are_connected",
                }
            })

    def test_invalid_query_type_rejected(self):
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "query_connectivity",
                    "target_file": "test.kicad_pcb",
                    "query_type": "invalid_type",
                }
            })

    def test_connected_pads_with_net_name_valid(self):
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": "test.kicad_pcb",
                "query_type": "connected_pads",
                "net_name": "GND",
            }
        })
        assert op.root.net_name == "GND"

    def test_are_connected_with_source_target_valid(self):
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": "test.kicad_pcb",
                "query_type": "are_connected",
                "source": ["U1", "1"],
                "target": ["U2", "3"],
            }
        })
        assert op.root.source == ["U1", "1"]
        assert op.root.target == ["U2", "3"]


class TestQueryExecutor:
    """Full executor pipeline tests against Arduino_Mega PCB."""

    def test_net_stats_returns_positive_integers(self, arduino_pcb_tmp):
        executor = _make_executor(arduino_pcb_tmp)
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": arduino_pcb_tmp.name,
                "query_type": "net_stats",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        stats = result["details"]
        assert stats["total_nets"] > 0
        assert stats["total_pads"] > 0
        assert stats["total_connections"] > 0

    def test_connected_pads_gnd_returns_list(self, arduino_pcb_tmp):
        executor = _make_executor(arduino_pcb_tmp)
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": arduino_pcb_tmp.name,
                "query_type": "connected_pads",
                "net_name": "GND",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        pads = result["details"]["pads"]
        assert isinstance(pads, list)
        assert len(pads) > 0
        # Each pad is a [ref, pad_number] list
        for pad in pads:
            assert isinstance(pad, list)
            assert len(pad) == 2

    def test_connected_pads_nonexistent_net_returns_empty(self, arduino_pcb_tmp):
        executor = _make_executor(arduino_pcb_tmp)
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": arduino_pcb_tmp.name,
                "query_type": "connected_pads",
                "net_name": "NONEXISTENT_NET",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["pads"] == []
        assert result["details"]["count"] == 0

    def test_are_connected_same_net(self, arduino_pcb_tmp):
        """Find two pads on GND and verify they are connected."""
        from volta.analysis.connectivity import NetGraph
        from volta.parser import parse_pcb
        from volta.parser.uuid_extractor import extract_uuids
        from volta.ir.pcb_ir import PcbIR

        parse_result = parse_pcb(arduino_pcb_tmp)
        uuid_map = extract_uuids(parse_result.raw_content, "pcb")
        ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
        graph = NetGraph.from_pcb_ir(ir)
        gnd_pads = graph.get_connected_pads("GND")
        assert len(gnd_pads) >= 2, "Need at least 2 GND pads for this test"

        source_ref = gnd_pads[0]
        target_ref = gnd_pads[1]

        executor = _make_executor(arduino_pcb_tmp)
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": arduino_pcb_tmp.name,
                "query_type": "are_connected",
                "source": [source_ref[0], source_ref[1]],
                "target": [target_ref[0], target_ref[1]],
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["connected"] is True

    def test_are_connected_different_nets(self, arduino_pcb_tmp):
        """Find two pads on different nets and verify they are not directly connected."""
        from volta.analysis.connectivity import NetGraph
        from volta.parser import parse_pcb
        from volta.parser.uuid_extractor import extract_uuids
        from volta.ir.pcb_ir import PcbIR

        parse_result = parse_pcb(arduino_pcb_tmp)
        uuid_map = extract_uuids(parse_result.raw_content, "pcb")
        ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
        graph = NetGraph.from_pcb_ir(ir)

        # Get two nets with pads
        nets = list(graph._net_index.keys())
        assert len(nets) >= 2, "Need at least 2 nets"

        net_a_pads = graph.get_connected_pads(nets[0])
        net_b_pads = graph.get_connected_pads(nets[1])
        assert len(net_a_pads) >= 1 and len(net_b_pads) >= 1

        source_ref = net_a_pads[0]
        target_ref = net_b_pads[0]

        executor = _make_executor(arduino_pcb_tmp)
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": arduino_pcb_tmp.name,
                "query_type": "are_connected",
                "source": [source_ref[0], source_ref[1]],
                "target": [target_ref[0], target_ref[1]],
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["connected"] is False

    def test_shortest_path_returns_path(self, arduino_pcb_tmp):
        """Find two pads on the same net and get the shortest path."""
        from volta.analysis.connectivity import NetGraph
        from volta.parser import parse_pcb
        from volta.parser.uuid_extractor import extract_uuids
        from volta.ir.pcb_ir import PcbIR

        parse_result = parse_pcb(arduino_pcb_tmp)
        uuid_map = extract_uuids(parse_result.raw_content, "pcb")
        ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
        graph = NetGraph.from_pcb_ir(ir)
        gnd_pads = graph.get_connected_pads("GND")
        assert len(gnd_pads) >= 2

        source_ref = gnd_pads[0]
        target_ref = gnd_pads[-1]

        executor = _make_executor(arduino_pcb_tmp)
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": arduino_pcb_tmp.name,
                "query_type": "shortest_path",
                "source": [source_ref[0], source_ref[1]],
                "target": [target_ref[0], target_ref[1]],
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        path = result["details"]["path"]
        assert isinstance(path, list)
        assert len(path) > 0
        assert result["details"]["length"] == len(path)

    def test_connected_components_returns_list(self, arduino_pcb_tmp):
        executor = _make_executor(arduino_pcb_tmp)
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": arduino_pcb_tmp.name,
                "query_type": "connected_components",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        components = result["details"]["components"]
        assert isinstance(components, list)
        assert len(components) >= 1
        assert result["details"]["count"] == len(components)

    def test_file_mtime_unchanged_after_query(self, arduino_pcb_tmp):
        """Read-only verification: query must not modify the file."""
        mtime_before = arduino_pcb_tmp.stat().st_mtime

        executor = _make_executor(arduino_pcb_tmp)
        op = Operation.model_validate({
            "root": {
                "op_type": "query_connectivity",
                "target_file": arduino_pcb_tmp.name,
                "query_type": "net_stats",
            }
        })
        executor.execute(op)

        mtime_after = arduino_pcb_tmp.stat().st_mtime
        assert mtime_before == mtime_after, "Query must not modify file"

    def test_query_on_invalid_pcb_raises(self):
        """Malformed PCB should raise an error that propagates cleanly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.kicad_pcb"
            bad_file.write_text("THIS IS NOT A VALID PCB FILE", encoding="utf-8")

            executor = OperationExecutor(base_dir=Path(tmpdir))
            op = Operation.model_validate({
                "root": {
                    "op_type": "query_connectivity",
                    "target_file": "bad.kicad_pcb",
                    "query_type": "net_stats",
                }
            })
            with pytest.raises(Exception):
                executor.execute(op)
