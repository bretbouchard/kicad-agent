"""KiCad file validation: round-trip stability, ERC, DRC, format checks, and pipeline."""

from kicad_agent.validation.roundtrip import round_trip_stable, round_trip_compare
from kicad_agent.validation.erc_drc import (
    run_erc,
    run_drc,
    ErcResult,
    DrcResult,
    Violation,
    Severity,
)
from kicad_agent.validation.structural import (
    validate_structural,
    validate_uuid_uniqueness,
    StructuralResult,
    StructuralViolation,
    ViolationKind,
)
from kicad_agent.validation.format_check import (
    validate_kicad10_format,
    FormatCheck,
    FormatCheckResult,
)
from kicad_agent.validation.grid_check import (
    check_grid_alignment,
    GridCheckResult,
)
from kicad_agent.validation.symbol_mismatch import (
    check_symbol_copy_mismatch,
    SymbolMismatchResult,
)
from kicad_agent.validation.pipeline import (
    ValidationPipeline,
    PipelineResult,
    PipelineStage,
    StageResult,
)

__all__ = [
    "round_trip_stable",
    "round_trip_compare",
    "run_erc",
    "run_drc",
    "ErcResult",
    "DrcResult",
    "Violation",
    "Severity",
    "validate_structural",
    "validate_uuid_uniqueness",
    "StructuralResult",
    "StructuralViolation",
    "ViolationKind",
    "validate_kicad10_format",
    "FormatCheck",
    "FormatCheckResult",
    "check_grid_alignment",
    "GridCheckResult",
    "check_symbol_copy_mismatch",
    "SymbolMismatchResult",
    "ValidationPipeline",
    "PipelineResult",
    "PipelineStage",
    "StageResult",
]
