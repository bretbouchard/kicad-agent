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
from kicad_agent.validation.gate_types import (
    DesignStage,
    GateResult,
    GateDefinition,
)
from kicad_agent.validation.gate_runner import (
    GateRunner,
    get_gate_runner,
    register_gate,
)

# These imports depend on modules that may not exist at all commits.
# Import them lazily to avoid cascading ImportError at package init.
try:
    from kicad_agent.validation.structural import (
        validate_structural,
        validate_uuid_uniqueness,
        StructuralResult,
        StructuralViolation,
        ViolationKind,
    )
except ImportError:
    pass

try:
    from kicad_agent.validation.pipeline import (
        ValidationPipeline,
        PipelineResult,
        PipelineStage,
        StageResult,
    )
except ImportError:
    pass

try:
    from kicad_agent.validation.drc_intel import (
        IntelligentDrcAnalyzer,
        EnrichedViolation,
        ViolationClassification,
        SpatialFixSuggestion,
        IntelligentDrcReport,
        FixSuggester,
    )
except ImportError:
    pass

try:
    from kicad_agent.validation.pcb_design_rules import (
        ClearanceCheckRule,
        ImpedanceCheckRule,
        ThermalProximityRule,
        get_pcb_design_rules,
    )
except ImportError:
    pass

try:
    from kicad_agent.validation.split_plane import (
        analyze_split_plane,
        SplitPlaneAnalysis,
        SplitGap,
        SplitCrossing,
    )
except ImportError:
    pass

try:
    from kicad_agent.validation.silkscreen_clearance import (
        check_silkscreen_clearance,
        SilkscreenViolation,
        SilkscreenClearanceResult,
    )
except ImportError:
    pass

__all__ = [
    "round_trip_stable",
    "round_trip_compare",
    "run_erc",
    "run_drc",
    "ErcResult",
    "DrcResult",
    "Violation",
    "Severity",
    "validate_kicad10_format",
    "FormatCheck",
    "FormatCheckResult",
    "check_grid_alignment",
    "GridCheckResult",
    "check_symbol_copy_mismatch",
    "SymbolMismatchResult",
    "DesignStage",
    "GateResult",
    "GateDefinition",
    "GateRunner",
    "get_gate_runner",
    "register_gate",
]
