"""Validation operation schemas -- power nets, schematic, ERC, violation positions, hlabels."""

from typing import Literal

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class ValidatePowerNetsOp(BaseModel):
    """Check all power pins have connected power symbols.

    Validates that every power pin (power_in, power_out) in the schematic
    is connected to a power symbol (power:* library reference).

    Attributes:
        op_type: Discriminator literal ``"validate_power_nets"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        check_hierarchical: Also check power nets span hierarchical sheets (default True).
    """

    op_type: Literal["validate_power_nets"] = "validate_power_nets"
    target_file: TargetFile
    check_hierarchical: bool = Field(
        default=True,
        description="Check power nets span hierarchical sheets",
    )


class ValidateSchematicOp(BaseModel):
    """Comprehensive schematic validation combining multiple checks.

    Runs KiCad 10 format validation, symbol resolution, power net checks,
    and annotation completeness in a single operation. Returns structured
    results for each check category.

    Attributes:
        op_type: Discriminator literal ``"validate_schematic"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        check_symbol_resolution: Verify all lib_ids resolve to symbol definitions (default True).
        check_format: Validate KiCad 10 S-expression format rules (default True).
        check_power_nets: Check power pin connectivity (default True).
        check_annotation: Check for unannotated components (default True).
    """

    op_type: Literal["validate_schematic"] = "validate_schematic"
    target_file: TargetFile
    check_symbol_resolution: bool = Field(default=True, description="Check all lib_ids resolve to symbol definitions")
    check_format: bool = Field(default=True, description="Validate KiCad 10 format rules")
    check_power_nets: bool = Field(default=True, description="Check power pin connectivity")
    check_annotation: bool = Field(default=True, description="Check for unannotated components")
    check_erc: bool = Field(default=False, description="Run kicad-cli ERC and require zero ERC errors")
    check_footprints: bool = Field(default=False, description="Require all board components to have footprints assigned")


class ParseErcOp(BaseModel):
    """Parse ERC results for a schematic file.

    SCHREPAIR-01: Returns structured violation data from kicad-cli ERC JSON output.

    Attributes:
        op_type: Discriminator literal ``"parse_erc"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["parse_erc"] = "parse_erc"
    target_file: TargetFile


class ExtractViolationPositionsOp(BaseModel):
    """Extract positions for a specific ERC violation type.

    SCHREPAIR-02: Filters violations by type and returns (x,y) positions.

    Attributes:
        op_type: Discriminator literal ``"extract_violation_positions"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        violation_type: Violation type to filter for (e.g. "pin_not_connected").
    """

    op_type: Literal["extract_violation_positions"] = "extract_violation_positions"
    target_file: TargetFile
    violation_type: str = Field(
        min_length=1,
        max_length=128,
        description="Violation type to filter for (e.g. 'pin_not_connected')",
    )


class PrePcbSchematicGateOp(BaseModel):
    """Hard gate for schematic readiness before PCB layout.

    Runs ERC, power net validation, and annotation completeness checks.
    This gate fails closed when the schematic is not ready for PCB transfer.

    Attributes:
        op_type: Discriminator literal ``"pre_pcb_schematic_gate"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        require_erc_clean: Require ERC to pass with zero errors (default True).
        require_footprints: Require all components to have footprint assignments (default True).
        check_hierarchical: Check hierarchical sheet connectivity (default True).
    """

    op_type: Literal["pre_pcb_schematic_gate"] = "pre_pcb_schematic_gate"
    target_file: TargetFile
    require_erc_clean: bool = Field(
        default=True,
        description="Require ERC clean with zero errors",
    )
    require_footprints: bool = Field(
        default=True,
        description="Require all board components to have footprint assignments",
    )
    check_hierarchical: bool = Field(
        default=True,
        description="Check hierarchical sheet connectivity",
    )


class ValidateHlabelsOp(BaseModel):
    """Validate hierarchical labels in a schematic.

    SCHREPAIR-03: Compares actual hlabels against expected set.

    Attributes:
        op_type: Discriminator literal ``"validate_hlabels"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        expected_labels: List of expected hierarchical label names. Empty means count only.
    """

    op_type: Literal["validate_hlabels"] = "validate_hlabels"
    target_file: TargetFile
    expected_labels: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="Expected hierarchical label names. Empty = count only.",
    )
