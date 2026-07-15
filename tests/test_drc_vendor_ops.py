"""Operation-level tests for drc_vendor and list_vendor_drc_profiles (DRC-01, DRC-04, DRC-08).

Exercises the handler registry + schema validation + read-only verification,
mirroring the test_connectivity_query.py pattern. The handler-direct tests use
the inline-PCB _build_ir helper from test_board_metadata_ops.py.
"""
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from volta.ops._schema_pcb import DrcVendorOp, ListVendorDrcProfilesOp
from volta.ops.schema import Operation


@pytest.fixture(autouse=True)
def _clear_ir_registry():
    """Avoid cross-test IR registration leaks (mirrors test_board_metadata_ops.py)."""
    from volta.ir.base import _clear_registry
    _clear_registry()
    yield
    _clear_registry()


def _build_ir(pcb_path: Path):
    """Parse PCB and build PcbIR (mimics executor setup)."""
    from volta.parser.pcb_parser import parse_pcb
    from volta.ir.pcb_ir import PcbIR
    from volta.parser.uuid_extractor import extract_uuids
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)


def _write_violating_pcb(tmp_path: Path) -> Path:
    """Inline PCB with a 0.1mm track (below generic 0.2mm min)."""
    pcb_path = tmp_path / "violating.kicad_pcb"
    pcb_path.write_text(
        '(kicad_pcb (version 20241229) (generator "test")\n'
        '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
        '  (segment (start 10 10) (end 20 10) (width 0.1) (layer "F.Cu") (net 0))\n'
        ')\n',
        encoding="utf-8",
    )
    return pcb_path


def _write_clean_pcb(tmp_path: Path) -> Path:
    """Inline PCB with all geometry at-or-above generic limits."""
    pcb_path = tmp_path / "clean.kicad_pcb"
    pcb_path.write_text(
        '(kicad_pcb (version 20241229) (generator "test")\n'
        '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
        '  (segment (start 10 10) (end 50 10) (width 0.2) (layer "F.Cu") (net 0))\n'
        '  (via (at 50 50) (size 0.7) (drill 0.4) (layers "F.Cu" "B.Cu") (net 0))\n'
        ')\n',
        encoding="utf-8",
    )
    return pcb_path


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestDrcVendorSchema:
    def test_drc_vendor_schema_valid(self):
        op = Operation.model_validate({
            "root": {
                "op_type": "drc_vendor",
                "target_file": "x.kicad_pcb",
                "vendor": "generic",
            }
        })
        assert op.root.op_type == "drc_vendor"
        assert op.root.vendor == "generic"

    def test_drc_vendor_default_run_kicad_drc(self):
        op = Operation.model_validate({
            "root": {
                "op_type": "drc_vendor",
                "target_file": "x.kicad_pcb",
                "vendor": "generic",
            }
        })
        assert op.root.run_kicad_drc is True

    def test_drc_vendor_path_traversal_rejected(self):
        """Threat model scenario 1: schema pattern rejects path traversal."""
        with pytest.raises(ValidationError):
            Operation.model_validate({
                "root": {
                    "op_type": "drc_vendor",
                    "target_file": "x.kicad_pcb",
                    "vendor": "../../etc/passwd",
                }
            })

    def test_drc_vendor_rejects_uppercase(self):
        with pytest.raises(ValidationError):
            Operation.model_validate({
                "root": {
                    "op_type": "drc_vendor",
                    "target_file": "x.kicad_pcb",
                    "vendor": "PCBWay",
                }
            })

    def test_drc_vendor_all_vendor_keys_valid(self):
        """Every vendor key in list_drc_profiles validates against the schema."""
        from volta.manufacturing.drc_profiles import list_drc_profiles
        for info in list_drc_profiles():
            op = Operation.model_validate({
                "root": {
                    "op_type": "drc_vendor",
                    "target_file": "x.kicad_pcb",
                    "vendor": info.vendor,
                }
            })
            assert op.root.vendor == info.vendor


class TestListVendorDrcProfilesSchema:
    def test_list_vendor_drc_profiles_schema_valid(self):
        op = Operation.model_validate({
            "root": {
                "op_type": "list_vendor_drc_profiles",
                "target_file": "x.kicad_pcb",
            }
        })
        assert op.root.op_type == "list_vendor_drc_profiles"


# ---------------------------------------------------------------------------
# Handler-direct tests
# ---------------------------------------------------------------------------


class TestDrcVendorHandler:
    def test_drc_vendor_unknown_vendor_raises(self, tmp_path):
        """Handler raises ValueError listing available vendors for unknown vendor."""
        from volta.ops.handlers.query import _QUERY_HANDLERS
        pcb_path = _write_clean_pcb(tmp_path)
        ir = _build_ir(pcb_path)
        op = DrcVendorOp(target_file="clean.kicad_pcb", vendor="nonexistent", run_kicad_drc=False)
        handler = _QUERY_HANDLERS["drc_vendor"]
        with pytest.raises(ValueError, match="Unknown profile"):
            handler(op, ir, pcb_path)

    def test_drc_vendor_detects_violation_via_handler(self, tmp_path):
        """SILENT-PASS GUARD: violating board -> passed=False, non-empty violations."""
        from volta.ops.handlers.query import _QUERY_HANDLERS
        pcb_path = _write_violating_pcb(tmp_path)
        ir = _build_ir(pcb_path)
        op = DrcVendorOp(target_file="violating.kicad_pcb", vendor="generic", run_kicad_drc=False)
        handler = _QUERY_HANDLERS["drc_vendor"]
        result = handler(op, ir, pcb_path)
        assert result["passed"] is False
        assert len(result["violations"]) >= 1
        assert result["profile_name"] == "Generic Conservative 2-Layer"
        assert result["vendor"] == "Generic Conservative 2-Layer"
        assert result["kicad_drc"] is None  # run_kicad_drc=False

    def test_drc_vendor_clean_board_passes_via_handler(self, tmp_path):
        """Clean board -> passed=True."""
        from volta.ops.handlers.query import _QUERY_HANDLERS
        pcb_path = _write_clean_pcb(tmp_path)
        ir = _build_ir(pcb_path)
        op = DrcVendorOp(target_file="clean.kicad_pcb", vendor="generic", run_kicad_drc=False)
        handler = _QUERY_HANDLERS["drc_vendor"]
        result = handler(op, ir, pcb_path)
        assert result["passed"] is True
        assert len(result["violations"]) == 0

    def test_drc_vendor_run_kicad_drc_graceful_degradation(self, tmp_path):
        """run_kicad_drc=True degrades gracefully if kicad-cli absent (error dict, not crash)."""
        from volta.ops.handlers.query import _QUERY_HANDLERS
        pcb_path = _write_clean_pcb(tmp_path)
        ir = _build_ir(pcb_path)
        op = DrcVendorOp(target_file="clean.kicad_pcb", vendor="generic", run_kicad_drc=True)
        handler = _QUERY_HANDLERS["drc_vendor"]
        result = handler(op, ir, pcb_path)
        # kicad_drc is either a result dict (kicad-cli present) or an error dict (absent).
        assert result["kicad_drc"] is not None
        assert isinstance(result["kicad_drc"], dict)

    def test_drc_vendor_pcbway_via_handler(self, tmp_path):
        """drc_vendor(vendor='pcbway') runs against PCBWay limits."""
        from volta.ops.handlers.query import _QUERY_HANDLERS
        pcb_path = _write_clean_pcb(tmp_path)
        ir = _build_ir(pcb_path)
        op = DrcVendorOp(target_file="clean.kicad_pcb", vendor="pcbway", run_kicad_drc=False)
        handler = _QUERY_HANDLERS["drc_vendor"]
        result = handler(op, ir, pcb_path)
        assert result["vendor"] == "PCBWay Standard 2-Layer"


class TestListVendorDrcProfilesHandler:
    def test_list_vendor_drc_profiles_returns_9(self, tmp_path):
        """Handler returns 9 profiles with all required fields."""
        from volta.ops.handlers.query import _QUERY_HANDLERS
        pcb_path = _write_clean_pcb(tmp_path)
        ir = _build_ir(pcb_path)
        op = ListVendorDrcProfilesOp(target_file="clean.kicad_pcb")
        handler = _QUERY_HANDLERS["list_vendor_drc_profiles"]
        result = handler(op, ir, pcb_path)
        assert result["count"] == 9
        assert len(result["profiles"]) == 9
        required_fields = {
            "vendor", "display_name", "drc_rules_path",
            "min_trace_width_mm", "min_clearance_mm", "min_drill_mm",
            "min_annular_ring_mm", "min_via_diameter_mm",
            "supports_blind_vias", "supports_castellated",
            "source", "last_verified",
        }
        for entry in result["profiles"]:
            assert required_fields.issubset(entry.keys()), (
                f"profile {entry.get('vendor')} missing fields: "
                f"{required_fields - entry.keys()}"
            )

    def test_list_profiles_ignores_ir(self, tmp_path):
        """Handler returns profiles even when ir is from a minimal board (handler ignores ir)."""
        from volta.ops.handlers.query import _QUERY_HANDLERS
        # Minimal/empty board — handler should still return 9 profiles.
        pcb_path = tmp_path / "empty.kicad_pcb"
        pcb_path.write_text(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal))\n'
            ')\n',
            encoding="utf-8",
        )
        ir = _build_ir(pcb_path)
        op = ListVendorDrcProfilesOp(target_file="empty.kicad_pcb")
        handler = _QUERY_HANDLERS["list_vendor_drc_profiles"]
        result = handler(op, ir, pcb_path)
        assert result["count"] == 9


# ---------------------------------------------------------------------------
# Read-only verification (file mtime unchanged)
# ---------------------------------------------------------------------------


class TestReadOnlyVerification:
    def test_drc_vendor_file_mtime_unchanged(self, tmp_path):
        """drc_vendor is read-only — file mtime unchanged after the op (mirrors
        test_connectivity_query.py:283-298)."""
        from volta.ops.handlers.query import _QUERY_HANDLERS

        # Copy a real fixture board to tmpdir.
        src = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb")
        if not src.is_file():
            pytest.skip("Arduino_Mega fixture not available")
        pcb_path = tmp_path / "Arduino_Mega.kicad_pcb"
        shutil.copy(src, pcb_path)

        ir = _build_ir(pcb_path)
        mtime_before = pcb_path.stat().st_mtime

        op = DrcVendorOp(target_file="Arduino_Mega.kicad_pcb", vendor="generic", run_kicad_drc=False)
        handler = _QUERY_HANDLERS["drc_vendor"]
        handler(op, ir, pcb_path)

        mtime_after = pcb_path.stat().st_mtime
        assert mtime_before == mtime_after, "drc_vendor must not modify the PCB file"
