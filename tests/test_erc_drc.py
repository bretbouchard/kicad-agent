"""Tests for ERC and DRC wrappers invoking kicad-cli -- VAL-01, VAL-02.

Covers:
- ErcResult and DrcResult frozen dataclass construction and properties
- Violation dataclass with severity filtering
- Severity enum value mapping
- run_erc() integration against real Arduino_Mega fixture (requires kicad-cli)
- run_drc() integration against real Arduino_Mega fixture (requires kicad-cli)
- Error handling: missing file, missing kicad-cli, wrong file extension
"""

import dataclasses
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_agent.validation.erc_drc import (
    DrcResult,
    ErcResult,
    Severity,
    Violation,
    _find_kicad_cli,
    run_drc,
    run_erc,
)


# ---------------------------------------------------------------------------
# Unit tests for result types
# ---------------------------------------------------------------------------


class TestErcResultTypes:
    """Unit tests for ErcResult frozen dataclass."""

    def test_erc_result_passed(self) -> None:
        """Empty ErcResult with passed=True has zero counts."""
        r = ErcResult(passed=True, file_path=Path("test.kicad_sch"))
        assert r.passed is True
        assert r.error_count == 0
        assert r.warning_count == 0
        assert r.violations == ()

    def test_erc_result_with_violations(self) -> None:
        """ErcResult correctly counts errors and warnings."""
        violations = (
            Violation(
                description="err1",
                severity=Severity.ERROR,
                type="type_a",
            ),
            Violation(
                description="err2",
                severity=Severity.ERROR,
                type="type_b",
            ),
            Violation(
                description="warn1",
                severity=Severity.WARNING,
                type="type_c",
            ),
        )
        r = ErcResult(
            passed=False,
            file_path=Path("test.kicad_sch"),
            violations=violations,
        )
        assert r.error_count == 2
        assert r.warning_count == 1
        assert r.passed is False
        assert len(r.errors) == 2
        assert len(r.warnings) == 1

    def test_erc_result_frozen(self) -> None:
        """ErcResult is frozen (immutable)."""
        r = ErcResult(passed=True, file_path=Path("test.kicad_sch"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.passed = False  # type: ignore[misc]

    def test_violation_frozen(self) -> None:
        """Violation is frozen (immutable)."""
        v = Violation(description="test", severity=Severity.ERROR, type="test_type")
        with pytest.raises(dataclasses.FrozenInstanceError):
            v.description = "changed"  # type: ignore[misc]

    def test_severity_enum_values(self) -> None:
        """Severity enum maps to kicad-cli JSON string values."""
        assert Severity.ERROR == "error"
        assert Severity.WARNING == "warning"
        assert Severity.EXCLUSION == "exclusion"

    def test_erc_result_with_error_message(self) -> None:
        """ErcResult with error_message set indicates invocation failure."""
        r = ErcResult(
            passed=False,
            file_path=Path("missing.kicad_sch"),
            error_message="File not found",
        )
        assert r.error_message == "File not found"
        assert r.passed is False

    def test_erc_result_kicad_version(self) -> None:
        """ErcResult captures kicad_version from the JSON report."""
        r = ErcResult(
            passed=True,
            file_path=Path("test.kicad_sch"),
            kicad_version="10.0.1",
        )
        assert r.kicad_version == "10.0.1"


class TestDrcResultTypes:
    """Unit tests for DrcResult frozen dataclass."""

    def test_drc_result_passed(self) -> None:
        """Empty DrcResult with passed=True has zero counts."""
        d = DrcResult(passed=True, file_path=Path("test.kicad_pcb"))
        assert d.passed is True
        assert d.error_count == 0
        assert d.warning_count == 0

    def test_drc_result_with_unconnected(self) -> None:
        """DrcResult captures unconnected_items tuple."""
        unconnected = (
            Violation(
                description="Unconnected pad",
                severity=Severity.ERROR,
                type="unconnected_items",
            ),
            Violation(
                description="Another unconnected pad",
                severity=Severity.ERROR,
                type="unconnected_items",
            ),
        )
        d = DrcResult(
            passed=False,
            file_path=Path("test.kicad_pcb"),
            unconnected_items=unconnected,
        )
        assert len(d.unconnected_items) == 2

    def test_drc_result_with_schematic_parity(self) -> None:
        """DrcResult captures schematic_parity data."""
        parity = (
            {"description": "Missing footprint", "type": "schematic_parity"},
        )
        d = DrcResult(
            passed=False,
            file_path=Path("test.kicad_pcb"),
            schematic_parity=parity,
        )
        assert len(d.schematic_parity) == 1
        assert d.schematic_parity[0]["type"] == "schematic_parity"

    def test_drc_result_frozen(self) -> None:
        """DrcResult is frozen (immutable)."""
        d = DrcResult(passed=True, file_path=Path("test.kicad_pcb"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            d.passed = False  # type: ignore[misc]

    def test_drc_result_passed_with_warnings_only(self) -> None:
        """DRC passes if only warnings exist (no errors, no unconnected)."""
        warnings = (
            Violation(
                description="Minor issue",
                severity=Severity.WARNING,
                type="courtyards_overlap",
            ),
        )
        d = DrcResult(
            passed=True,
            file_path=Path("test.kicad_pcb"),
            violations=warnings,
        )
        assert d.passed is True
        assert d.warning_count == 1
        assert d.error_count == 0


# ---------------------------------------------------------------------------
# Integration tests (require kicad-cli)
# ---------------------------------------------------------------------------

_SKIP_REASON = "kicad-cli not available on PATH"


@pytest.mark.skipif(not shutil.which("kicad-cli"), reason=_SKIP_REASON)
class TestRunErc:
    """Integration tests for run_erc() against real kicad-cli."""

    def test_erc_on_raspberry_pi(self, raspberry_pi_sch: Path) -> None:
        """run_erc on RaspberryPi-uHAT returns structured result with violations."""
        result = run_erc(raspberry_pi_sch)

        assert isinstance(result, ErcResult)
        assert result.file_path == raspberry_pi_sch
        assert result.error_message is None
        # RaspberryPi-uHAT has ERC errors (power pins not driven, etc.)
        assert result.passed is False
        assert result.error_count > 0
        # kicad_version should be present
        assert result.kicad_version
        assert result.kicad_version[0].isdigit()

    def test_erc_violations_have_details(self, raspberry_pi_sch: Path) -> None:
        """Each ERC error violation has non-empty description, type, severity."""
        result = run_erc(raspberry_pi_sch)
        assert len(result.errors) > 0

        for violation in result.errors:
            assert violation.description, "Violation description is empty"
            assert violation.type, "Violation type is empty"
            assert violation.severity == Severity.ERROR

    def test_erc_file_not_found(self) -> None:
        """run_erc on nonexistent file returns error result."""
        result = run_erc(Path("/nonexistent.kicad_sch"))
        assert result.passed is False
        assert result.error_message is not None
        assert "File not found" in result.error_message

    def test_erc_wrong_extension(self, tmp_path: Path) -> None:
        """run_erc on non-.kicad_sch file returns error result."""
        wrong_file = tmp_path / "test.txt"
        wrong_file.write_text("not a schematic", encoding="utf-8")
        result = run_erc(wrong_file)
        assert result.passed is False
        assert result.error_message is not None
        assert ".kicad_sch" in result.error_message

    def test_erc_has_ignored_checks(self, raspberry_pi_sch: Path) -> None:
        """ERC result includes ignored_checks from the report."""
        result = run_erc(raspberry_pi_sch)
        # ignored_checks is a tuple (may be empty, but should exist)
        assert isinstance(result.ignored_checks, tuple)


@pytest.mark.skipif(not shutil.which("kicad-cli"), reason=_SKIP_REASON)
class TestRunDrc:
    """Integration tests for run_drc() against real kicad-cli."""

    def test_drc_on_arduino_mega(self, arduino_mega_pcb: Path) -> None:
        """run_drc on Arduino_Mega returns structured result with violations."""
        result = run_drc(arduino_mega_pcb)

        assert isinstance(result, DrcResult)
        assert result.file_path == arduino_mega_pcb
        assert result.error_message is None
        # Arduino_Mega PCB has violations (warnings and/or unconnected items)
        assert result.passed is False
        assert result.warning_count > 0 or len(result.unconnected_items) > 0

    def test_drc_unconnected_items(self, arduino_mega_pcb: Path) -> None:
        """Arduino_Mega PCB has unconnected items captured in result."""
        result = run_drc(arduino_mega_pcb)
        assert len(result.unconnected_items) > 0
        for item in result.unconnected_items:
            assert item.type == "unconnected_items"

    def test_drc_with_schematic_parity(self, raspberry_pi_pcb: Path) -> None:
        """run_drc with check_schematic_parity=True captures parity data."""
        result = run_drc(raspberry_pi_pcb, check_schematic_parity=True)
        assert result.error_message is None
        # schematic_parity should be a tuple (may be empty or have items)
        assert isinstance(result.schematic_parity, tuple)

    def test_drc_file_not_found(self) -> None:
        """run_drc on nonexistent file returns error result."""
        result = run_drc(Path("/nonexistent.kicad_pcb"))
        assert result.passed is False
        assert result.error_message is not None
        assert "File not found" in result.error_message

    def test_drc_wrong_extension(self, tmp_path: Path) -> None:
        """run_drc on non-.kicad_pcb file returns error result."""
        wrong_file = tmp_path / "test.txt"
        wrong_file.write_text("not a pcb", encoding="utf-8")
        result = run_drc(wrong_file)
        assert result.passed is False
        assert result.error_message is not None
        assert ".kicad_pcb" in result.error_message


# ---------------------------------------------------------------------------
# Unit tests for _find_kicad_cli
# ---------------------------------------------------------------------------


class TestFindKicadCli:
    """Tests for kicad-cli discovery function."""

    def test_find_kicad_cli_succeeds(self) -> None:
        """_find_kicad_cli returns a non-empty string when kicad-cli exists."""
        if shutil.which("kicad-cli"):
            cli = _find_kicad_cli()
            assert cli
            assert "kicad-cli" in cli

    def test_find_kicad_cli_not_found(self) -> None:
        """_find_kicad_cli raises FileNotFoundError when kicad-cli is missing."""
        with patch("kicad_agent.validation.erc_drc.shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="kicad-cli not found"):
                _find_kicad_cli()
