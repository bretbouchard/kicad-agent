"""add_design_note — annotate schematics with reason, intention, math (volta-29).

Bart-style inline annotations ("10uA/oct", "2.5/55k = 45.5uA") as KiCad
text elements, with note_type prefixes for grep-ability and optional
anchor-relative placement so notes stay beside their subject.
"""

from __future__ import annotations

from pathlib import Path

import pytest

MINI_SCH = """(kicad_sch (version 20231120) (generator "test")
  (symbol (lib_id "Device:R") (reference "R1") (value "10k") (at 100 100 0)
    (property "Reference" "R1" (at 100 100 0)))
)
"""


def _executor(tmp_path: Path):
    (tmp_path / "board.kicad_sch").write_text(MINI_SCH)
    from volta.ops.executor import OperationExecutor

    return OperationExecutor(base_dir=tmp_path), tmp_path / "board.kicad_sch"


class TestAbsolutePlacement:
    def test_note_written_with_type_prefix(self, tmp_path: Path):
        from volta.ops.schema import Operation

        executor, sch = _executor(tmp_path)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_design_note",
                "target_file": sch.name,
                "text": "10uA/oct",
                "position": {"x": 45.97, "y": 69.85},
                "note_type": "MATH",
            }
        })
        result = executor.execute(op)
        details = result["details"]
        assert details["status"] == "ok"
        content = sch.read_text()
        assert "[MATH] 10uA/oct" in content
        assert details["position"] == [45.97, 69.85]

    def test_target_ref_embedded_for_tooling(self, tmp_path: Path):
        from volta.ops.schema import Operation

        executor, sch = _executor(tmp_path)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_design_note",
                "target_file": sch.name,
                "text": "scale trim target 47.17uA",
                "position": {"x": 10, "y": 10},
                "note_type": "REASON",
                "target_ref": "R7",
            }
        })
        result = executor.execute(op)
        assert result["details"]["status"] == "ok"
        assert "[REASON] @R7 scale trim target" in sch.read_text()

    def test_multiline_note(self, tmp_path: Path):
        from volta.ops.schema import Operation

        executor, sch = _executor(tmp_path)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_design_note",
                "target_file": sch.name,
                "text": "2.5/55k = 45.5uA\\n5/1M = 5uA\\ntotal: 50.5uA",
                "position": {"x": 10, "y": 10},
                "note_type": "MATH",
            }
        })
        result = executor.execute(op)
        assert result["details"]["status"] == "ok"
        assert "45.5uA" in sch.read_text()


class TestAnchorPlacement:
    def test_anchored_above_left_resolves_from_component(self, tmp_path: Path):
        from volta.ops.schema import Operation

        executor, sch = _executor(tmp_path)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_design_note",
                "target_file": sch.name,
                "text": "block: EXPONENTIAL CONVERTER",
                "anchor": {"ref": "R1", "side": "above-left", "offset": [5.0, 5.0]},
                "note_type": "BLOCK_HEADER",
            }
        })
        result = executor.execute(op)
        details = result["details"]
        assert details["status"] == "ok"
        # R1 at (100,100); above-left side offset (-5,-5); extra (5,5)
        # → net (0,0) → note at (100, 100).
        assert details["anchor"]["resolved_to"] == [100.0, 100.0]
        assert "EXPONENTIAL CONVERTER" in sch.read_text()

    def test_anchored_below_defaults(self, tmp_path: Path):
        from volta.ops.schema import Operation

        executor, sch = _executor(tmp_path)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_design_note",
                "target_file": sch.name,
                "text": "note under the part",
                "anchor": {"ref": "R1", "side": "below"},
            }
        })
        result = executor.execute(op)
        details = result["details"]
        # below = (0, +5); default extra offset (5,5) → (105, 110).
        assert details["anchor"]["resolved_to"] == [105.0, 110.0]

    def test_unknown_anchor_ref_fails_actionably(self, tmp_path: Path):
        from volta.ops.schema import Operation

        executor, sch = _executor(tmp_path)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_design_note",
                "target_file": sch.name,
                "text": "orphan",
                "anchor": {"ref": "ZZZ9", "side": "above"},
            }
        })
        result = executor.execute(op)
        details = result["details"]
        assert details["status"] == "error"
        assert "ZZZ9" in details["error"]


class TestSchemaValidation:
    def test_position_and_anchor_mutually_exclusive(self):
        from pydantic import ValidationError
        from volta.ops.schema import Operation

        with pytest.raises(ValidationError):
            Operation.model_validate({
                "root": {
                    "op_type": "add_design_note",
                    "target_file": "x.kicad_sch",
                    "text": "t",
                    "position": {"x": 1, "y": 2},
                    "anchor": {"ref": "R1"},
                }
            })

    def test_neither_position_nor_anchor_rejected(self):
        from pydantic import ValidationError
        from volta.ops.schema import Operation

        with pytest.raises(ValidationError):
            Operation.model_validate({
                "root": {
                    "op_type": "add_design_note",
                    "target_file": "x.kicad_sch",
                    "text": "t",
                }
            })
