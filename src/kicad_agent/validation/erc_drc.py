"""ERC and DRC wrappers invoking kicad-cli with structured result parsing.

VAL-01: ERC gate via kicad-cli with structured pass/fail/warning results.
VAL-02: DRC gate via kicad-cli with structured pass/fail/warning results.

kicad-cli writes JSON report files via --output flag. This module handles:
  1. kicad-cli discovery and invocation
  2. JSON report file capture and parsing
  3. Structured result dataclass construction
  4. Error handling for missing CLI, failed runs, malformed output

Usage:
    from kicad_agent.validation.erc_drc import run_erc, run_drc

    result = run_erc(Path("my_schematic.kicad_sch"))
    if result.passed:
        print("ERC clean")
    else:
        for v in result.errors:
            print(f"ERROR: {v.description} at {v.type}")
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Violation severity levels from kicad-cli reports."""

    ERROR = "error"
    WARNING = "warning"
    EXCLUSION = "exclusion"


@dataclass(frozen=True)
class Violation:
    """A single ERC/DRC violation with description, severity, type, and affected items."""

    description: str
    severity: Severity
    type: str
    items: tuple[dict[str, Any], ...] = ()
    sheet_path: str = "/"  # ERC only -- which sheet the violation is on


@dataclass(frozen=True)
class ErcResult:
    """Structured result from an ERC check.

    VAL-01: Structured pass/fail/warning result for schematic validation.
    """

    passed: bool
    file_path: Path
    violations: tuple[Violation, ...] = ()
    ignored_checks: tuple[dict[str, str], ...] = ()
    kicad_version: str = ""
    error_message: Optional[str] = None  # Set if kicad-cli invocation failed

    @property
    def errors(self) -> tuple[Violation, ...]:
        """Violations with severity=error."""
        return tuple(v for v in self.violations if v.severity == Severity.ERROR)

    @property
    def warnings(self) -> tuple[Violation, ...]:
        """Violations with severity=warning."""
        return tuple(v for v in self.violations if v.severity == Severity.WARNING)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


@dataclass(frozen=True)
class DrcResult:
    """Structured result from a DRC check.

    VAL-02: Structured pass/fail/warning result for PCB validation.
    Also captures unconnected_items and schematic_parity for VAL-03.
    """

    passed: bool
    file_path: Path
    violations: tuple[Violation, ...] = ()
    unconnected_items: tuple[Violation, ...] = ()
    schematic_parity: tuple[dict[str, Any], ...] = ()
    ignored_checks: tuple[dict[str, str], ...] = ()
    kicad_version: str = ""
    error_message: Optional[str] = None

    @property
    def errors(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity == Severity.ERROR)

    @property
    def warnings(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity == Severity.WARNING)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


def _find_kicad_cli() -> str:
    """Find kicad-cli on PATH.

    Returns:
        Absolute path to kicad-cli.

    Raises:
        FileNotFoundError: If kicad-cli is not found on PATH.
    """
    cli_path = shutil.which("kicad-cli")
    if cli_path is None:
        raise FileNotFoundError(
            "kicad-cli not found on PATH. "
            "Install KiCad 10+ to get kicad-cli. "
            "On macOS: brew install --cask kicad"
        )
    return cli_path


def _parse_violations(
    violations_json: list[dict[str, Any]], sheet_path: str = "/"
) -> tuple[Violation, ...]:
    """Parse a list of violation dicts from the JSON report into Violation tuples.

    Args:
        violations_json: List of violation dicts from kicad-cli JSON report.
        sheet_path: The sheet path these violations belong to (ERC only).

    Returns:
        Tuple of Violation frozen dataclass instances.
    """
    result = []
    for v in violations_json:
        try:
            severity = Severity(v.get("severity", "error"))
        except ValueError:
            logger.warning("Unknown severity %s, defaulting to ERROR", v.get("severity"))
            severity = Severity.ERROR

        items_raw = v.get("items", [])
        items = tuple(items_raw) if isinstance(items_raw, list) else ()
        result.append(
            Violation(
                description=v.get("description", ""),
                severity=severity,
                type=v.get("type", ""),
                items=items,
                sheet_path=sheet_path,
            )
        )
    return tuple(result)


def run_erc(schematic_path: Path, *, timeout: int = 120) -> ErcResult:
    """Run ERC on a schematic file using kicad-cli.

    Invokes ``kicad-cli sch erc --format json --severity-all`` and parses
    the JSON report into a structured ErcResult.

    Args:
        schematic_path: Path to a .kicad_sch file.
        timeout: Maximum seconds to wait for kicad-cli (default 120).

    Returns:
        ErcResult with pass/fail status, violations, and metadata.
        If kicad-cli invocation fails, returns ErcResult with error_message set.
    """
    # Validate input file
    if not schematic_path.exists():
        return ErcResult(
            passed=False,
            file_path=schematic_path,
            error_message=f"File not found: {schematic_path}",
        )

    if schematic_path.suffix != ".kicad_sch":
        return ErcResult(
            passed=False,
            file_path=schematic_path,
            error_message=f"Expected .kicad_sch file, got: {schematic_path.suffix}",
        )

    # Find kicad-cli
    try:
        cli_path = _find_kicad_cli()
    except FileNotFoundError as e:
        return ErcResult(
            passed=False,
            file_path=schematic_path,
            error_message=str(e),
        )

    tempdir = None
    try:
        tempdir = tempfile.mkdtemp(prefix="kicad-agent-erc-")
        output_file = Path(tempdir) / "erc_report.json"

        cmd = [
            cli_path,
            "sch",
            "erc",
            "--format",
            "json",
            "--severity-all",
            "--output",
            str(output_file),
            str(schematic_path),
        ]
        logger.debug("Running ERC: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # Check if output file was created
        if not output_file.exists():
            stderr_info = result.stderr.strip() if result.stderr else ""
            return ErcResult(
                passed=False,
                file_path=schematic_path,
                error_message=(
                    f"kicad-cli did not produce output file. "
                    f"stderr: {stderr_info}"
                ),
            )

        # Council H-01: Restrict permissions on temp report file
        os.chmod(output_file, 0o600)

        # Parse JSON report
        report_text = output_file.read_text(encoding="utf-8")
        try:
            report = json.loads(report_text)
        except json.JSONDecodeError as e:
            return ErcResult(
                passed=False,
                file_path=schematic_path,
                error_message=f"Malformed JSON report: {e}",
            )

        # Extract violations from all sheets
        all_violations: list[Violation] = []
        sheets = report.get("sheets", [])
        for sheet in sheets:
            sheet_path = sheet.get("path", "/")
            violations = sheet.get("violations", [])
            all_violations.extend(_parse_violations(violations, sheet_path))

        # Extract metadata
        ignored_checks = tuple(report.get("ignored_checks", []))
        kicad_version = report.get("kicad_version", "")

        # passed = True if zero errors (warnings are non-fatal)
        errors = [v for v in all_violations if v.severity == Severity.ERROR]
        passed = len(errors) == 0

        return ErcResult(
            passed=passed,
            file_path=schematic_path,
            violations=tuple(all_violations),
            ignored_checks=ignored_checks,
            kicad_version=kicad_version,
        )

    except subprocess.TimeoutExpired:
        return ErcResult(
            passed=False,
            file_path=schematic_path,
            error_message=f"kicad-cli ERC timed out after {timeout}s",
        )

    except Exception as e:
        return ErcResult(
            passed=False,
            file_path=schematic_path,
            error_message=f"Unexpected error running ERC: {e}",
        )

    finally:
        if tempdir is not None:
            try:
                shutil.rmtree(tempdir, ignore_errors=True)
            except Exception:
                logger.warning("Failed to clean up tempdir: %s", tempdir)


def run_drc(
    pcb_path: Path,
    *,
    check_schematic_parity: bool = False,
    timeout: int = 300,
) -> DrcResult:
    """Run DRC on a PCB file using kicad-cli.

    Invokes ``kicad-cli pcb drc --format json --severity-all`` and parses
    the JSON report into a structured DrcResult.

    Args:
        pcb_path: Path to a .kicad_pcb file.
        check_schematic_parity: If True, add --schematic-parity flag (VAL-03).
        timeout: Maximum seconds to wait for kicad-cli (default 300).

    Returns:
        DrcResult with pass/fail status, violations, unconnected items,
        and schematic parity data. If kicad-cli invocation fails, returns
        DrcResult with error_message set.
    """
    # Validate input file
    if not pcb_path.exists():
        return DrcResult(
            passed=False,
            file_path=pcb_path,
            error_message=f"File not found: {pcb_path}",
        )

    if pcb_path.suffix != ".kicad_pcb":
        return DrcResult(
            passed=False,
            file_path=pcb_path,
            error_message=f"Expected .kicad_pcb file, got: {pcb_path.suffix}",
        )

    # Find kicad-cli
    try:
        cli_path = _find_kicad_cli()
    except FileNotFoundError as e:
        return DrcResult(
            passed=False,
            file_path=pcb_path,
            error_message=str(e),
        )

    tempdir = None
    try:
        tempdir = tempfile.mkdtemp(prefix="kicad-agent-drc-")
        output_file = Path(tempdir) / "drc_report.json"

        cmd = [
            cli_path,
            "pcb",
            "drc",
            "--format",
            "json",
            "--severity-all",
            "--output",
            str(output_file),
        ]
        if check_schematic_parity:
            cmd.append("--schematic-parity")
        cmd.append(str(pcb_path))

        logger.debug("Running DRC: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # Check if output file was created
        if not output_file.exists():
            stderr_info = result.stderr.strip() if result.stderr else ""
            return DrcResult(
                passed=False,
                file_path=pcb_path,
                error_message=(
                    f"kicad-cli did not produce output file. "
                    f"stderr: {stderr_info}"
                ),
            )

        # Council H-01: Restrict permissions on temp report file
        os.chmod(output_file, 0o600)

        # Parse JSON report
        report_text = output_file.read_text(encoding="utf-8")
        try:
            report = json.loads(report_text)
        except json.JSONDecodeError as e:
            return DrcResult(
                passed=False,
                file_path=pcb_path,
                error_message=f"Malformed JSON report: {e}",
            )

        # Extract violations
        violations_json = report.get("violations", [])
        violations = _parse_violations(violations_json)

        # Extract unconnected items
        unconnected_json = report.get("unconnected_items", [])
        unconnected_items = _parse_violations(unconnected_json)

        # Extract schematic parity
        schematic_parity = tuple(report.get("schematic_parity", []))

        # Extract metadata
        ignored_checks = tuple(report.get("ignored_checks", []))
        kicad_version = report.get("kicad_version", "")

        # passed = True if zero errors AND zero unconnected items
        errors = [v for v in violations if v.severity == Severity.ERROR]
        passed = len(errors) == 0 and len(unconnected_items) == 0

        return DrcResult(
            passed=passed,
            file_path=pcb_path,
            violations=violations,
            unconnected_items=unconnected_items,
            schematic_parity=schematic_parity,
            ignored_checks=ignored_checks,
            kicad_version=kicad_version,
        )

    except subprocess.TimeoutExpired:
        return DrcResult(
            passed=False,
            file_path=pcb_path,
            error_message=f"kicad-cli DRC timed out after {timeout}s",
        )

    except Exception as e:
        return DrcResult(
            passed=False,
            file_path=pcb_path,
            error_message=f"Unexpected error running DRC: {e}",
        )

    finally:
        if tempdir is not None:
            try:
                shutil.rmtree(tempdir, ignore_errors=True)
            except Exception:
                logger.warning("Failed to clean up tempdir: %s", tempdir)
