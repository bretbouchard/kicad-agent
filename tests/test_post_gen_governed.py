"""Governed verification coverage for post-generation validation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from volta.governance import GovernedExecutionContext
from volta.validation.erc_drc import DrcResult, ErcResult
from volta.validation.post_gen import validate_generated


def test_validate_generated_emits_governed_verification_for_erc(tmp_path: Path) -> None:
    schematic_path = tmp_path / "demo.kicad_sch"
    schematic_path.write_text(
        '(kicad_sch (version 20241229) (generator "test")\n'
        '  (symbol (lib_id "Device:R")\n'
        '    (property "Reference" "R1" (at 0 0))\n'
        '    (property "Value" "10k" (at 0 0))\n'
        '  )\n'
        ')\n',
        encoding="utf-8",
    )

    with patch(
        "volta.validation.post_gen.run_erc",
        return_value=ErcResult(passed=True, file_path=schematic_path),
        create=True,
    ):
        result = validate_generated(
            schematic_path=schematic_path,
            run_erc=True,
            governed_context=GovernedExecutionContext(),
        )

    assert result.governed_verification is not None
    assert result.governed_verification.invocation.capability_name == "verification.batch"
    assert len(result.governed_verification.evidence) >= 1


def test_validate_generated_emits_governed_verification_for_drc(tmp_path: Path) -> None:
    pcb_path = tmp_path / "demo.kicad_pcb"
    pcb_path.write_text("(kicad_pcb)", encoding="utf-8")

    with patch(
        "volta.validation.post_gen.run_drc",
        return_value=DrcResult(passed=True, file_path=pcb_path),
        create=True,
    ):
        result = validate_generated(
            pcb_path=pcb_path,
            run_drc=True,
            governed_context=GovernedExecutionContext(),
        )

    assert result.governed_verification is not None
    assert result.governed_verification.invocation.capability_name == "verification.batch"
    assert len(result.governed_verification.evidence) >= 1
