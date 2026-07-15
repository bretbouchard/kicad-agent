"""Schematic intent completeness gate.

Validates that a schematic has sufficient information to produce a meaningful
PCB before transitioning to the PCB setup stage.

This gate is ADDITIVE to pre_pcb_schematic_gate in ops/validation_gates.py.
That gate handles ERC, power nets, annotation, format validation, and a basic
footprint check. This gate handles deeper metadata completeness, pin-count
validation, and DNP-aware footprint filtering.

Both gates register for the schematic->pcb_setup stage transition and
GateRunner executes both via run_all_gates().

Sub-checks:
  1. Footprint completeness -- every non-DNP, non-power, non-virtual component
     must have a footprint assigned.
  2. Symbol pin count -- verify lib_symbol pin count matches expected count
     parsed from the symbol name (e.g., "NE5532" -> 8, "SOT-23-5" -> 5).
     Full footprint pad-count comparison deferred to Phase 87.
  3. Component metadata -- warn on missing Value/MPN properties for
     non-DNP components with footprints.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from volta.ir.schematic_ir import SchematicIR
from volta.validation.gate_runner import register_gate
from volta.validation.gate_types import DesignStage, GateDefinition, GateResult

logger = logging.getLogger(__name__)

# Regex to extract pin count hints from symbol names.
# Matches patterns like "SOT-23-5" (5 pins), "SOT-223-4" (4 pins),
# "TSSOP-16", "QFN-48", "DIP-8", "SOIC-14", etc.
# Captures the LAST number after the package prefix, which is the pin count.
_PIN_COUNT_PATTERN = re.compile(
    r"(?:SOT|TSSOP|QFN|DIP|SOIC|SSOP|VQFN|LQFP|BGA|QFP|DFN|SON|WLCSP)[-_]\d+(?:[-_](\d+))?",
    re.IGNORECASE,
)

# Known component pin counts indexed by part name.
# Covers the most common ICs that don't have pin count in their package name.
_KNOWN_PIN_COUNTS: dict[str, int] = {
    "NE5532": 8,
    "NE5534": 8,
    "LM358": 8,
    "LM741": 8,
    "LM7805": 3,
    "LM7803": 3,
    "LM317": 3,
    "ATmega328P": 28,
    "ATmega2560": 100,
    "ATmega32U4": 44,
    "ESP32": 38,
    "STM32F103C8": 48,
    "STM32F103C6": 48,
}


def _is_excluded_component(
    component: Any,
    ir: SchematicIR,
) -> bool:
    """Check if a component should be excluded from intent checks.

    Excludes:
    - Virtual components (reference starts with "#")
    - Power symbols (libId starts with "power:")
    - DNP components (component.dnp == True)
    """
    reference = ir.get_component_property(component, "Reference") or ""
    lib_id = getattr(component, "libId", "") or ""

    if reference.startswith("#"):
        return True
    if lib_id.startswith("power:"):
        return True
    if getattr(component, "dnp", False) is True:
        return True

    return False


def _get_lib_symbol_pin_count(
    component: Any,
    ir: SchematicIR,
) -> int | None:
    """Get the pin count from the component's matching lib_symbol.

    Searches lib_symbols for a matching entry by libId and returns
    the pin count from the first unit. Returns None if no match found
    or no pins exist.
    """
    comp_lib_id = getattr(component, "libId", "")
    schematic = ir.schematic

    for lib_sym in schematic.libSymbols:
        sym_lib_id = getattr(lib_sym, "libId", "")
        if sym_lib_id == comp_lib_id:
            # Match found -- get pin count from first unit
            units = getattr(lib_sym, "units", [])
            if units:
                unit = units[0]
                pins = getattr(unit, "pins", [])
                return len(pins)
            # No units -- try direct pins attribute
            pins = getattr(lib_sym, "pins", [])
            if pins:
                return len(pins)
            return None

    # Fallback: match by entry name (handles missing library nickname)
    if ":" in comp_lib_id:
        comp_entry = comp_lib_id.split(":")[-1]
        for lib_sym in schematic.libSymbols:
            sym_lib_id = getattr(lib_sym, "libId", "")
            entry = getattr(lib_sym, "entryName", "")
            if (sym_lib_id == comp_entry or entry == comp_entry) and ":" not in sym_lib_id:
                units = getattr(lib_sym, "units", [])
                if units:
                    return len(getattr(units[0], "pins", []))
                return len(getattr(lib_sym, "pins", []))

    return None


def _parse_expected_pin_count(symbol_name: str) -> int | None:
    """Parse expected pin count from a symbol name.

    Checks two sources:
    1. Package name patterns (SOT-23-5, TSSOP-16, etc.)
    2. Known component name lookup table
    """
    # Extract the entry name from libId (part after colon)
    if ":" in symbol_name:
        symbol_name = symbol_name.split(":")[-1]

    # Check package pattern
    match = _PIN_COUNT_PATTERN.search(symbol_name)
    if match and match.group(1) is not None:
        return int(match.group(1))

    # Check known component table
    for name, count in _KNOWN_PIN_COUNTS.items():
        if name.upper() in symbol_name.upper():
            return count

    return None


def check_footprint_completeness(
    schematic_ir: SchematicIR,
) -> tuple[list[str], list[str]]:
    """Check that all non-DNP, non-power components have footprints assigned.

    Returns:
        (blockers, warnings) -- blockers for missing footprints, warnings for
        generic/placeholder footprint patterns.
    """
    blockers: list[str] = []
    warnings: list[str] = []

    for component in schematic_ir.components:
        if _is_excluded_component(component, schematic_ir):
            continue

        reference = schematic_ir.get_component_property(component, "Reference") or ""
        lib_id = getattr(component, "libId", "")
        footprint = schematic_ir.get_component_property(component, "Footprint") or ""

        if not footprint.strip():
            blockers.append(
                f"Component {reference} ({lib_id}) has no footprint assigned"
            )
        elif _is_generic_footprint(footprint):
            warnings.append(
                f"Component {reference} has generic footprint: {footprint}"
            )

    return blockers, warnings


def _is_generic_footprint(footprint: str) -> bool:
    """Check if a footprint string looks generic/placeholder.

    A generic footprint is one that only specifies a package type
    without a specific library prefix (e.g., just "0805" or "SOT-23"
    without "Resistor_SMD:" or "Package_TO_SOT_SMD:" prefix).
    """
    # If there's no colon, it's likely generic (no library prefix)
    if ":" not in footprint:
        return bool(footprint.strip())
    return False


def check_symbol_pin_count(
    schematic_ir: SchematicIR,
) -> tuple[list[str], list[str]]:
    """Verify symbol pin count matches expected count from name parsing.

    For each non-power, non-DNP component:
    1. Get pin count from the matching lib_symbol
    2. Parse expected pin count from the component name
    3. If both are available and don't match, produce a blocker

    If pin count cannot be determined from the name, skip silently
    (too many false positives for custom parts).

    Full footprint pad-count comparison is deferred to Phase 87
    when footprint resolution is available.

    Returns:
        (blockers, warnings) -- blockers for pin count mismatches.
    """
    blockers: list[str] = []
    warnings: list[str] = []

    for component in schematic_ir.components:
        if _is_excluded_component(component, schematic_ir):
            continue

        reference = schematic_ir.get_component_property(component, "Reference") or ""
        lib_id = getattr(component, "libId", "")

        # Get actual pin count from lib_symbol
        actual_pins = _get_lib_symbol_pin_count(component, schematic_ir)
        if actual_pins is None:
            continue

        # Parse expected pin count from symbol name
        expected_pins = _parse_expected_pin_count(lib_id)
        if expected_pins is None:
            continue

        if actual_pins != expected_pins:
            blockers.append(
                f"Component {reference} ({lib_id}): pin count mismatch -- "
                f"lib_symbol has {actual_pins} pins, expected {expected_pins} "
                f"from symbol name"
            )

    return blockers, warnings


def check_component_metadata(
    schematic_ir: SchematicIR,
) -> tuple[list[str], list[str]]:
    """Check component metadata completeness for non-DNP components.

    For each non-power, non-DNP component with a footprint assigned:
    - Missing Value property: warning
    - Missing MPN/part number: warning

    MPN is nice-to-have for manufacturing but not a PCB validity blocker,
    so missing MPN produces a warning, not a blocker.

    Returns:
        (blockers, warnings) -- metadata issues (all warnings, no blockers).
    """
    blockers: list[str] = []
    warnings: list[str] = []

    for component in schematic_ir.components:
        if _is_excluded_component(component, schematic_ir):
            continue

        footprint = schematic_ir.get_component_property(component, "Footprint") or ""
        if not footprint.strip():
            continue  # Skip components without footprints (caught by footprint check)

        reference = schematic_ir.get_component_property(component, "Reference") or ""

        # Check Value property
        value = schematic_ir.get_component_property(component, "Value") or ""
        if not value.strip():
            warnings.append(
                f"Component {reference} has no value specified"
            )

        # Check MPN property (check both common property names)
        mpn = (
            schematic_ir.get_component_property(component, "MPN")
            or schematic_ir.get_component_property(component, "Manufacturer Part")
            or ""
        )
        if not mpn.strip():
            warnings.append(
                f"Component {reference} has no MPN (Manufacturer Part Number) specified"
            )

    return blockers, warnings


def check_net_intent(
    schematic_ir: SchematicIR,
) -> tuple[list[str], list[str], list[str]]:
    """Run net intent extraction and quality checks.

    Returns (blockers, warnings, artifacts).
    Blockers: hidden power pins, stub symbols.
    Warnings: unclassified nets, ambiguous connectors.
    Artifacts: net classification summary.
    """
    from volta.validation.gates.net_intent import NetIntentExtractor
    from volta.analysis.types import NetClassification

    extractor = NetIntentExtractor()

    # Net classification -- added to artifacts, not blockers
    net_classes = extractor.extract_nets(schematic_ir)
    artifacts: list[str] = [f"{name}: {cls.value}" for name, cls in net_classes.items()]

    # Warn about unknown nets (Thermal Rick suggestion from council review)
    warnings: list[str] = []
    for name, cls in net_classes.items():
        if cls == NetClassification.UNKNOWN:
            warnings.append(
                f"Net '{name}' could not be classified -- "
                "consider adding a naming convention"
            )

    # Quality checks
    blockers: list[str] = []

    hidden_pins = extractor.detect_hidden_power_pins(schematic_ir)
    blockers.extend(f"Hidden power pin: {pin}" for pin in hidden_pins)

    connectors = extractor.detect_ambiguous_connectors(schematic_ir)
    warnings.extend(f"Ambiguous connector: {ref}" for ref in connectors)

    stubs = extractor.detect_stub_symbols(schematic_ir)
    blockers.extend(f"Stub symbol with no pins: {ref}" for ref in stubs)

    return blockers, warnings, artifacts


class SchematicIntentGate:
    """Schematic intent completeness gate.

    ADDITIVE to existing pre_pcb_schematic_gate -- provides deeper
    metadata and pin-count validation that the existing gate does not cover.
    Both gates register for the schematic->pcb_setup transition.
    """

    def run(self, context: dict) -> GateResult:
        """Run all sub-checks and aggregate results.

        Args:
            context: Dict with optional keys:
                - schematic_ir: SchematicIR instance (if pre-built)
                - sch_path: Path to .kicad_sch file (for building IR)
                - project_dir: Path to project directory (fallback)

        Returns:
            GateResult with aggregated blockers and warnings.
        """
        ir = context.get("schematic_ir")
        if ir is None:
            sch_path = context.get("sch_path") or context.get("project_dir")
            if sch_path is None:
                return GateResult(
                    pass_=False,
                    gate_name="schematic_intent",
                    stage=DesignStage.SCHEMATIC,
                    blockers=["No schematic path or IR provided in context"],
                )

            from volta.parser import parse_schematic
            from pathlib import Path

            path = Path(sch_path)
            if path.is_dir():
                # Find .kicad_sch in directory
                sch_files = sorted(path.glob("*.kicad_sch"))
                if not sch_files:
                    return GateResult(
                        pass_=False,
                        gate_name="schematic_intent",
                        stage=DesignStage.SCHEMATIC,
                        blockers=[f"No .kicad_sch files found in {path}"],
                    )
                parse_result = parse_schematic(sch_files[0])
            else:
                parse_result = parse_schematic(path)

            ir = SchematicIR(_parse_result=parse_result)

        # Run all sub-checks with the same IR instance
        fp_blockers, fp_warnings = check_footprint_completeness(ir)
        pc_blockers, pc_warnings = check_symbol_pin_count(ir)
        md_blockers, md_warnings = check_component_metadata(ir)
        ni_blockers, ni_warnings, ni_artifacts = check_net_intent(ir)

        all_blockers = fp_blockers + pc_blockers + md_blockers + ni_blockers
        all_warnings = fp_warnings + pc_warnings + md_warnings + ni_warnings

        # Collect artifacts
        artifacts: list[str] = []
        if all_blockers:
            artifacts.append(f"{len(all_blockers)} blocker(s) found")
        if all_warnings:
            artifacts.append(f"{len(all_warnings)} warning(s) found")
        # Include net classification in artifacts
        if ni_artifacts:
            artifacts.append(f"{len(ni_artifacts)} net(s) classified")

        # Build next actions
        next_actions: list[str] = []
        if fp_blockers:
            next_actions.append(
                f"Assign footprints to {len(fp_blockers)} component(s)"
            )
        if pc_blockers:
            next_actions.append(
                f"Resolve {len(pc_blockers)} pin count mismatch(es)"
            )
        if ni_blockers:
            next_actions.append(
                f"Fix {len(ni_blockers)} net intent issue(s)"
            )

        if all_blockers:
            return GateResult(
                pass_=False,
                gate_name="schematic_intent",
                stage=DesignStage.SCHEMATIC,
                blockers=all_blockers,
                warnings=all_warnings,
                artifacts=artifacts,
                next_actions=next_actions or ["Fix blockers above and retry"],
            )

        return GateResult(
            pass_=True,
            gate_name="schematic_intent",
            stage=DesignStage.PCB_SETUP,
            warnings=all_warnings,
            artifacts=artifacts,
            next_actions=["Proceed to pcb_setup stage"],
        )


# Module-level registration with GateRunner
_gate = SchematicIntentGate()

register_gate(
    GateDefinition(
        name="schematic_intent",
        from_stage=DesignStage.SCHEMATIC,
        to_stage=DesignStage.PCB_SETUP,
        check_fn_name="schematic_intent_gate",
    ),
    check_fn=_gate.run,
)
