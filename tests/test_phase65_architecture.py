"""Phase 65: Architecture refactor tests for M-1 through M-12.

Tests the 9 MEDIUM findings implemented in this phase:
  M-1:  DFM cli exit code distinction (already correct, verified)
  M-2:  MCP edit_server preserves $defs/$ref via inlining
  M-3:  CLI uses public extract_board_stats
  M-5:  batch_connect label fallback uses meaningful default
  M-6:  SolderMaskCheck caches to_shapely() results
  M-7:  _interpolate_path has precondition documentation
  M-8:  PlacementGraph has public graph property
  M-10: violation_classifier uses narrow except
  M-11: PcbIR has public raw_written property; BaseIR has mark_dirty()
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# M-1: DFM cli exit code distinction
# ---------------------------------------------------------------------------


class TestM1DfmExitCodes:
    """Verify DFM CLI uses distinct exit codes: 0=pass, 1=violations, 2=error."""

    def test_docstring_documents_exit_codes(self):
        """The dfm_command docstring must document all three exit codes."""
        from volta.dfm.cli import dfm_command

        doc = dfm_command.__doc__
        assert doc is not None
        assert "0" in doc
        assert "1" in doc
        assert "2" in doc

    def test_error_conditions_return_2(self):
        """Board-not-found and profile errors return exit code 2."""
        from volta.dfm.cli import dfm_command

        args = MagicMock()
        args.board = "/nonexistent/board.kicad_pcb"
        result = dfm_command(args)
        assert result == 2


# ---------------------------------------------------------------------------
# M-2: MCP edit_server preserves $defs/$ref via inlining
# ---------------------------------------------------------------------------


class TestM2SchemaInlineRefs:
    """Verify _inline_refs resolves $ref using $defs and removes $defs."""

    def test_inline_refs_resolves_simple_ref(self):
        from volta.mcp.edit_server import _inline_refs

        schema = {
            "$defs": {
                "Point": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                    },
                },
            },
            "properties": {
                "position": {"$ref": "#/$defs/Point"},
            },
        }
        _inline_refs(schema)
        assert "$defs" not in schema
        position = schema["properties"]["position"]
        assert "$ref" not in position
        assert position["type"] == "object"
        assert "x" in position["properties"]

    def test_inline_refs_no_defs_noop(self):
        from volta.mcp.edit_server import _inline_refs

        schema = {"properties": {"name": {"type": "string"}}}
        _inline_refs(schema)
        assert schema == {"properties": {"name": {"type": "string"}}}

    def test_inline_refs_preserves_sibling_keys(self):
        """Sibling keys on a $ref node (like description) are preserved."""
        from volta.mcp.edit_server import _inline_refs

        schema = {
            "$defs": {"Foo": {"type": "string"}},
            "properties": {
                "field": {
                    "$ref": "#/$defs/Foo",
                    "description": "A foo field",
                },
            },
        }
        _inline_refs(schema)
        field = schema["properties"]["field"]
        assert field["type"] == "string"
        assert field["description"] == "A foo field"


# ---------------------------------------------------------------------------
# M-3: CLI uses public extract_board_stats
# ---------------------------------------------------------------------------


class TestM3PublicBoardStats:
    """Verify InferenceWrapper has a public extract_board_stats method."""

    def test_public_method_exists(self):
        from volta.inference.wrapper import InferenceWrapper

        assert hasattr(InferenceWrapper, "extract_board_stats")
        assert callable(InferenceWrapper.extract_board_stats)

    def test_public_method_has_docstring(self):
        from volta.inference.wrapper import InferenceWrapper

        doc = InferenceWrapper.extract_board_stats.__doc__
        assert doc is not None
        assert "Public API" in doc or "board stats" in doc.lower()

    def test_cli_uses_public_method(self):
        """CLI should use extract_board_stats, not _extract_board_stats."""
        import ast

        cli_path = "/Users/bretbouchard/apps/volta/src/volta/cli.py"
        with open(cli_path) as f:
            source = f.read()
        # Should NOT contain _extract_board_stats in the CLI source
        assert "_extract_board_stats" not in source, (
            "cli.py should use the public extract_board_stats method"
        )


# ---------------------------------------------------------------------------
# M-5: batch_connect label fallback uses meaningful default
# ---------------------------------------------------------------------------


class TestM5BatchConnectLabelFallback:
    """Verify batch_connect handler uses a meaningful label name fallback."""

    def test_no_empty_string_fallback_in_executor(self):
        """The batch_connect handler must not fall back to empty string for label names."""
        # After Plan 74 refactor, batch_connect handler moved to handlers/schematic.py
        handler_path = "/Users/bretbouchard/apps/volta/src/volta/ops/handlers/schematic.py"
        with open(handler_path) as f:
            source = f.read()

        # Find the batch_connect handler region
        assert 'net_name", op.nets[0].name if op.nets else ""' not in source, (
            "batch_connect should not fall back to empty string for net_name"
        )
        assert "unnamed_net" in source, (
            "batch_connect should use 'unnamed_net' as meaningful fallback"
        )


# ---------------------------------------------------------------------------
# M-6: SolderMaskCheck caches to_shapely() results
# ---------------------------------------------------------------------------


class TestM6SolderMaskCaching:
    """Verify SolderMaskCheck uses a geometry cache to avoid redundant to_shapely() calls."""

    def test_check_method_uses_geom_cache(self):
        """The check method source must reference geom_cache."""
        import ast

        checks_path = "/Users/bretbouchard/apps/volta/src/volta/dfm/checks.py"
        with open(checks_path) as f:
            source = f.read()
        assert "geom_cache" in source, (
            "SolderMaskCheck.check must use a geom_cache for to_shapely() caching"
        )

    def test_to_shapely_called_once_per_pad(self):
        """to_shapely should be called at most once per pad via the cache."""
        from volta.dfm.checks import SolderMaskCheck

        check = SolderMaskCheck()
        # Create pads with tracked to_shapely calls using real Shapely geometries
        # (STRtree requires real geometries, not MagicMock objects).
        call_count = {"count": 0}

        from shapely.geometry import box

        class TrackedPad:
            """Pad that tracks to_shapely() calls and returns real geometry."""

            def __init__(self, eid, ref, x_offset=0.0):
                self.entity_type = "pad"
                self.layer = "F.Mask"
                self.entity_id = eid
                self.reference = ref
                self._geom = box(x_offset, 0, x_offset + 2.0, 2.0)

            def to_shapely(self):
                call_count["count"] += 1
                return self._geom

        # Place pads close enough to trigger sliver detection proximity
        pads = [TrackedPad(f"pad_{i}", f"R{i}", x_offset=float(i * 2.5)) for i in range(5)]

        model = MagicMock()
        model.all_primitives = pads

        profile = MagicMock()
        profile.min_solder_mask_sliver_mm = 0.1

        check.check(model, profile)

        # With caching, each pad's to_shapely should be called exactly once
        assert call_count["count"] == len(pads), (
            f"Expected {len(pads)} to_shapely calls (one per pad), "
            f"got {call_count['count']}"
        )


# ---------------------------------------------------------------------------
# M-7: _interpolate_path has precondition documentation
# ---------------------------------------------------------------------------


class TestM7InterpolatePathPrecondition:
    """Verify _interpolate_path docstring documents preconditions."""

    def test_docstring_has_precondition_section(self):
        from volta.routing.geometry import _interpolate_path

        doc = _interpolate_path.__doc__
        assert doc is not None
        assert "Precondition" in doc

    def test_docstring_documents_path_length(self):
        from volta.routing.geometry import _interpolate_path

        doc = _interpolate_path.__doc__
        assert "at least 2" in doc or "len(path) >= 2" in doc


# ---------------------------------------------------------------------------
# M-8: PlacementGraph has public graph property
# ---------------------------------------------------------------------------


class TestM8PublicGraphAccessor:
    """Verify PlacementGraph exposes a public graph property."""

    def test_public_graph_property_exists(self):
        import networkx as nx
        from volta.placement.graph import PlacementGraph

        g = nx.Graph()
        pg = PlacementGraph(g)
        assert hasattr(pg, "graph")
        assert pg.graph is g

    def test_public_graph_is_property(self):
        from volta.placement.graph import PlacementGraph

        assert isinstance(
            inspect.getattr_static(PlacementGraph, "graph"), property
        ), "PlacementGraph.graph should be a property"


# ---------------------------------------------------------------------------
# M-10: violation_classifier uses narrow except
# ---------------------------------------------------------------------------


class TestM10NarrowExcept:
    """Verify _extract_ir_data uses narrow exception types."""

    def test_no_bare_except_in_extract_ir_data(self):
        """Source must not use bare 'except Exception' in _extract_ir_data."""
        classifier_path = (
            "/Users/bretbouchard/apps/volta/src/volta/ops/violation_classifier.py"
        )
        with open(classifier_path) as f:
            source = f.read()

        # Find the _extract_ir_data function
        assert "except Exception" not in source.split("def _extract_ir_data")[1].split("def ")[0], (
            "_extract_ir_data must not use broad 'except Exception'"
        )

    def test_uses_narrow_exceptions(self):
        classifier_path = (
            "/Users/bretbouchard/apps/volta/src/volta/ops/violation_classifier.py"
        )
        with open(classifier_path) as f:
            source = f.read()

        func_source = source.split("def _extract_ir_data")[1].split("def ")[0]
        assert "AttributeError" in func_source
        assert "TypeError" in func_source
        assert "ValueError" in func_source


# ---------------------------------------------------------------------------
# M-11: PcbIR has public raw_written property; BaseIR has mark_dirty()
# ---------------------------------------------------------------------------


class TestM11PublicAccessors:
    """Verify public accessors for dirty state and raw_written flag."""

    def test_pcbir_raw_written_property(self):
        from volta.ir.pcb_ir import PcbIR

        assert hasattr(PcbIR, "raw_written")
        assert isinstance(
            inspect.getattr_static(PcbIR, "raw_written"), property
        ), "PcbIR.raw_written should be a property"

    def test_baseir_mark_dirty_method(self):
        from volta.ir.base import BaseIR

        assert hasattr(BaseIR, "mark_dirty")
        assert callable(BaseIR.mark_dirty)

    def test_mark_dirty_sets_dirty_flag(self):
        """mark_dirty should set the dirty property to True."""
        from volta.ir.base import BaseIR
        from volta.parser.types import ParseResult

        # Create a minimal parse result
        pr = ParseResult(
            file_type="schematic",
            file_path="/tmp/test.kicad_sch",
            raw_content="(test)",
            kiutils_obj=MagicMock(),
        )
        ir = BaseIR(_parse_result=pr)
        assert not ir.dirty
        ir.mark_dirty("test")
        assert ir.dirty

    def test_executor_uses_raw_written_not_private(self):
        """Executor must use public raw_written, not _raw_written."""
        executor_path = "/Users/bretbouchard/apps/volta/src/volta/ops/executor.py"
        with open(executor_path) as f:
            source = f.read()

        # Should NOT access _raw_written directly (except in batch/cross-file which we also fixed)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "ir._raw_written" in line:
                pytest.fail(
                    f"Line {i+1} uses private _raw_written: {line.strip()}"
                )

    def test_executor_uses_mark_dirty_not_private(self):
        """Executor must use public mark_dirty(), not _dirty = True."""
        executor_path = "/Users/bretbouchard/apps/volta/src/volta/ops/executor.py"
        with open(executor_path) as f:
            source = f.read()

        assert "ir._dirty = True" not in source, (
            "Executor must use ir.mark_dirty() instead of ir._dirty = True"
        )
