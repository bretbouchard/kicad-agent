"""Schematic intelligence operation schemas -- net extraction, conflict detection, name suggestion."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class ExtractNetsOp(BaseModel):
    """Extract complete net topology from a schematic file.

    SCH-INTEL-01: Returns a mapping of net names to connected pin lists.

    Attributes:
        op_type: Discriminator literal "extract_nets".
        target_file: Relative path to the target .kicad_sch file.
        include_positions: Include pin positions in output (default True).
        netlist_path: Optional path to .net file for net name resolution.
    """

    op_type: Literal["extract_nets"] = "extract_nets"
    target_file: TargetFile
    include_positions: bool = Field(default=True, description="Include pin positions in output")
    netlist_path: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Optional path to .net file for net name resolution",
    )


class DetectNetConflictsOp(BaseModel):
    """Detect net naming conflicts in a schematic file.

    SCH-INTEL-02: Returns structured conflict list without running ERC.

    Attributes:
        op_type: Discriminator literal "detect_net_conflicts".
        target_file: Relative path to the target .kicad_sch file.
        check_case_variants: Detect case-variant net names (default True).
        check_mixed_labels: Detect mixed label types on same net (default True).
        check_unlabeled_junctions: Detect junctions merging unnamed nets (default True).
    """

    op_type: Literal["detect_net_conflicts"] = "detect_net_conflicts"
    target_file: TargetFile
    check_case_variants: bool = Field(default=True, description="Detect case-variant net names")
    check_mixed_labels: bool = Field(default=True, description="Detect mixed label types on same net")
    check_unlabeled_junctions: bool = Field(default=True, description="Detect junctions merging unnamed nets")


class SuggestNetNamesOp(BaseModel):
    """Suggest canonical net names based on labels and topology.

    SCH-INTEL-03: Returns name suggestions for unnamed or poorly named nets.

    Attributes:
        op_type: Discriminator literal "suggest_net_names".
        target_file: Relative path to the target .kicad_sch file.
        netlist_path: Optional path to .net file for better net name resolution.
        naming_convention: Naming convention for component-ref-based suggestions.
            "ref_pin" produces "U1_SDA", "ref_pin_number" produces "U1_Pin5".
    """

    op_type: Literal["suggest_net_names"] = "suggest_net_names"
    target_file: TargetFile
    netlist_path: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Optional path to .net file for net name resolution",
    )
    naming_convention: Literal["ref_pin", "ref_pin_number"] = Field(
        default="ref_pin",
        description="Naming convention for component-ref-based suggestions",
    )


class DetectNetShortsOp(BaseModel):
    """Detect shorted nets with pin-level tracing and severity classification.

    Combines ERC multiple_net_names violations with netlist pin membership
    to identify shared pins between shorted nets. Classifies severity:
    critical (power-to-power or power-to-ground), high (power-to-signal or
    signal-to-signal), medium (ground variant to ground variant).

    Attributes:
        op_type: Discriminator literal ``"detect_net_shorts"``.
        target_file: Relative path to the target .kicad_sch file.
        include: Only check these specific net names. None = all.
        severity: Filter results by severity level.
    """

    op_type: Literal["detect_net_shorts"] = "detect_net_shorts"
    target_file: TargetFile
    include: Optional[list[str]] = Field(
        default=None,
        max_length=10,
        description="Only check these net names. None = all.",
    )
    severity: Literal["all", "critical", "high", "medium"] = Field(
        default="all",
        description="Filter by severity: all, critical, high, or medium.",
    )


class InferConnectivityOp(BaseModel):
    """Infer net connectivity from partial wiring with confidence scoring.

    SCH-INTEL-04: Returns scored net list and unconnected pin analysis.

    Attributes:
        op_type: Discriminator literal "infer_connectivity".
        target_file: Relative path to the target .kicad_sch file.
        pin_map: Built-in profile name ("auto", "backplane", "channel-strip", "none").
        confidence_threshold: Minimum confidence to include ("low", "medium", "high").
    """

    op_type: Literal["infer_connectivity"] = "infer_connectivity"
    target_file: TargetFile
    pin_map: Literal["auto", "backplane", "channel-strip", "none"] = Field(
        default="auto",
        description="Pin mapping profile: auto, backplane, channel-strip, or none",
    )
    confidence_threshold: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Minimum confidence level to include in results",
    )


class AnalyzeGroundTopologyOp(BaseModel):
    """Analyze ground net topology for mixed-signal designs.

    Identifies ground net variants (GND, AGND, GNDA, DGND, etc.), classifies
    their domains (digital/analog/passive), finds interconnections via ERC
    violations, and recommends merge/split/star_point for each connection.

    Attributes:
        op_type: Discriminator literal ``"analyze_ground_topology"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        ground_nets: Specific ground nets to analyze. None = auto-detect all.
    """

    op_type: Literal["analyze_ground_topology"] = "analyze_ground_topology"
    target_file: TargetFile
    ground_nets: Optional[list[str]] = Field(
        default=None,
        max_length=20,
        description="Specific ground nets to analyze. None = auto-detect all.",
    )
