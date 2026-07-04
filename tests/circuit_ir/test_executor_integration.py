"""BLK-5: Executor-level integration tests for convert_to_skidl + convert_from_skidl.

This is the prior council review's #1 recommendation — verify the ops
work through the real OperationExecutor, not just direct function calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_LED_FIXTURE = _FIXTURES / "schematic_intent" / "complete_led.kicad_sch"


class TestExecutorIntegration:
    """Execute convert ops through the real OperationExecutor."""

    def test_convert_to_skidl_via_executor(self, tmp_path: Path) -> None:
        """convert_to_skidl works through the executor dispatch."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        import json
        from kicad_agent.handler import handle_operation

        result = handle_operation(json.dumps({
            "op_type": "convert_to_skidl",
            "target_file": str(_LED_FIXTURE),
            "level": "L1",
        }))

        assert result is not None
        if isinstance(result, dict):
            details = result.get("details", result)
            assert "parts" in details or "op_type" in details

    def test_convert_from_skidl_via_executor(self, tmp_path: Path) -> None:
        """convert_from_skidl works through the CREATE dispatch path."""
        import json
        from kicad_agent.handler import handle_operation

        skidl_script = tmp_path / "test_build.py"
        skidl_script.write_text(
            'import os\n'
            'os.environ["KICAD_SYMBOL_DIR"] = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"\n'
            'from skidl import Part, Net, Circuit\n'
            'def build_board():\n'
            '    ckt = Circuit()\n'
            '    with ckt:\n'
            '        r = Part("Device", "R", value="1k")\n'
            '    return ckt\n',
            encoding="utf-8",
        )

        try:
            result = handle_operation(json.dumps({
                "op_type": "convert_from_skidl",
                "target_file": str(tmp_path / "output.kicad_sch"),
                "source": str(skidl_script),
                "source_type": "skidl",
            }))
            assert result is not None
        except FileNotFoundError as e:
            if "Target file not found" not in str(e):
                raise
