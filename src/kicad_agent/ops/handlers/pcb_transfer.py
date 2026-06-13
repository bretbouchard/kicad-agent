"""PCB transfer handler -- schematic-to-PCB transfer with gate enforcement.

Implements UpdateFromSchematicOp: validates the transfer contract before any
PCB mutation. Gate failures prevent mutation (fail-closed design).

This operation is DIFFERENT from UpdatePcbFromSchematicOp (which uses kicad-cli
netlist export for actual PCB sync). This operation:
- Validates the transfer CONTRACT before any PCB mutation
- Runs TransferContractValidator which auto-runs SchematicIntentGate
- Has NO force/bypass flag in the operation schema (gates fail closed)
- Provides stub/placeholder footprint detection
- CLI-only --force flag exists for human testing but is NOT in the operation schema

Security (T-87-06, T-87-07):
- No force/bypass field in the Pydantic schema -- LLM agents cannot bypass gates
- force parameter exists only at the handler function level (CLI-only escape hatch)
- The force flag is documented as testing-only and NOT exposed via MCP or operation schema
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Footprint patterns indicating a placeholder/stub assignment
_STUB_FOOTPRINT_PATTERNS: set[str] = {"~", "", "*", "?"}


# ---------------------------------------------------------------------------
# Operation schema (Pydantic model, no force/bypass field)
# ---------------------------------------------------------------------------


class UpdateFromSchematicOp(BaseModel):
    """Transfer schematic intent to PCB via validated contract.

    Validates the transfer contract (symbol->footprint->pad->net mapping)
    before allowing any PCB mutation. Gate failures prevent mutation.

    Attributes:
        op_type: Discriminator literal ``"update_from_schematic"``.
        schematic_path: Path to the schematic file (.kicad_sch).
        pcb_path: Optional path to the PCB file (.kicad_pcb). If not provided,
            only contract validation is performed.
        dry_run: If True, return the contract result without mutating any files.
            Useful for pre-flight checks.
    """

    op_type: Literal["update_from_schematic"] = "update_from_schematic"
    schematic_path: str = Field(
        min_length=1,
        max_length=512,
        description="Path to the schematic file (.kicad_sch)",
    )
    pcb_path: str | None = Field(
        default=None,
        max_length=512,
        description="Optional path to the PCB file (.kicad_pcb)",
    )
    dry_run: bool = Field(
        default=False,
        description="Return contract without mutating files",
    )

    # NOTE: NO force/bypass field. Gates fail closed. LLM agents cannot bypass.
    # The handler function accepts an optional force parameter for CLI-only human testing.


# ---------------------------------------------------------------------------
# Stub detection functions
# ---------------------------------------------------------------------------


def detect_stub_footprints(schematic_ir: Any) -> list[str]:
    """Detect components with placeholder/unknown footprints.

    Returns descriptive error messages for each component that has a stub
    footprint. Stub footprints indicate the component is not ready for PCB
    transfer.

    Power symbols (lib_id containing '#PWR' or starting with 'power:') and
    DNP components are excluded from this check.

    Args:
        schematic_ir: SchematicIR instance with components.

    Returns:
        List of descriptive error messages, one per stub component.
    """
    stubs: list[str] = []

    for component in schematic_ir.components:
        reference = schematic_ir.get_component_property(component, "Reference") or ""
        lib_id = getattr(component, "libId", "") or ""

        if not reference:
            continue

        # Skip power symbols
        if "#PWR" in lib_id or lib_id.startswith("power:"):
            continue

        # Skip DNP components
        if getattr(component, "dnp", False) is True:
            continue

        footprint = schematic_ir.get_component_footprint(reference)

        if not footprint or not footprint.strip() or footprint.strip() in _STUB_FOOTPRINT_PATTERNS:
            fp_display = footprint if footprint else "(empty)"
            stubs.append(
                f"{reference} has placeholder footprint '{fp_display}' "
                f"(assign a real footprint before transfer)"
            )

    return stubs


def detect_placeholder_pads(schematic_ir: Any, pcb_ir: Any) -> list[str]:
    """Detect footprints with suspiciously few pads relative to symbol pin count.

    A footprint with 1 pad but a symbol with >1 pin is likely a placeholder
    footprint (e.g., a generic 1-pad package used as a stand-in).

    Args:
        schematic_ir: SchematicIR instance with components and pin data.
        pcb_ir: PcbIR instance for querying PCB footprint pads.

    Returns:
        List of descriptive error messages, one per placeholder pad detection.
    """
    placeholders: list[str] = []

    for component in schematic_ir.components:
        reference = schematic_ir.get_component_property(component, "Reference") or ""
        lib_id = getattr(component, "libId", "") or ""

        if not reference:
            continue

        # Skip power symbols
        if "#PWR" in lib_id or lib_id.startswith("power:"):
            continue

        # Skip DNP components
        if getattr(component, "dnp", False) is True:
            continue

        # Get pin count from schematic
        pin_map_result = schematic_ir.verify_pin_map(reference, "")
        symbol_pins = pin_map_result.get("symbol_pins", set())

        if not symbol_pins or len(symbol_pins) <= 1:
            # Single-pin or no-pin components don't trigger this check
            continue

        # Get pad count from PCB
        pcb_pads = pcb_ir.get_footprint_pads(reference)
        pad_count = len(pcb_pads)
        pin_count = len(symbol_pins)

        # Flag if pad count is suspiciously low for a multi-pin symbol
        if pad_count == 1 and pin_count > 1:
            placeholders.append(
                f"{reference} footprint has {pad_count} pad but symbol {reference} "
                f"has {pin_count} pins (wrong footprint?)"
            )

    return placeholders


# ---------------------------------------------------------------------------
# Handler implementation
# ---------------------------------------------------------------------------


def handle_update_from_schematic(
    op: UpdateFromSchematicOp,
    ir_map: dict[Path, Any],
    base_dir: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Execute the schematic-to-PCB transfer operation.

    Flow:
    1. Locate schematic IR from ir_map
    2. Run stub detection on schematic components
    3. Run TransferContractValidator (which auto-runs SchematicIntentGate)
    4. If gate fails, return failure without mutation
    5. If PCB exists: run placeholder pad detection, return contract status
    6. If no PCB: report contract ready for PCB creation
    7. dry_run returns contract without any file mutation

    Args:
        op: The UpdateFromSchematicOp with schematic_path, pcb_path, dry_run.
        ir_map: Dict of file path -> IR instance (SchematicIR, PcbIR).
        base_dir: Base directory for resolving paths.
        force: CLI-only bypass flag. NOT part of the operation schema.
            When True, skips gate validation for human testing.
            This is a testing-only escape hatch and must NOT be exposed via MCP.

    Returns:
        Dict with pass, gate, blockers, warnings, artifacts, and contract status.
    """
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.ir.schematic_ir import SchematicIR
    from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

    # --- Force bypass (CLI-only, NOT in operation schema) ---
    # Must come BEFORE schematic IR check so force=True always succeeds
    if force:
        logger.warning("Gate bypassed via --force flag (CLI-only, testing mode)")

        result = {
            "pass": True,
            "gate": "transfer_contract",
            "force_bypassed": True,
            "blockers": [],
            "warnings": [
                "Gate validation bypassed via --force (CLI-only testing mode)"
            ],
            "artifacts": ["Force bypass -- contract not validated"],
        }
        if op.dry_run:
            result["dry_run"] = True
        return result

    # --- Locate schematic IR ---
    sch_ir: SchematicIR | None = None
    pcb_ir: PcbIR | None = None

    for file_path, ir in ir_map.items():
        if isinstance(ir, SchematicIR):
            sch_ir = ir
        elif isinstance(ir, PcbIR):
            pcb_ir = ir

    if sch_ir is None:
        return {
            "pass": False,
            "gate": "transfer_contract",
            "blockers": ["No schematic IR provided -- cannot validate transfer contract"],
            "warnings": [],
            "artifacts": [],
        }

    # --- Stub detection ---
    stubs = detect_stub_footprints(sch_ir)

    # --- Run TransferContractValidator ---
    validator = TransferContractValidator()
    gate_result = validator.validate(schematic_ir=sch_ir, pcb_ir=pcb_ir)

    # --- Combine stub detection with gate result ---
    all_blockers = list(gate_result.blockers)
    all_warnings = list(gate_result.warnings)
    all_artifacts = list(gate_result.artifacts)

    # Stubs from our detection are blockers (not warnings)
    for stub in stubs:
        if stub not in all_blockers:
            all_blockers.append(stub)

    # --- Placeholder pad detection (only if PCB exists) ---
    if pcb_ir is not None:
        pad_placeholders = detect_placeholder_pads(sch_ir, pcb_ir)
        for ph in pad_placeholders:
            if ph not in all_blockers:
                all_blockers.append(ph)

    # --- Build result ---
    if all_blockers:
        result = {
            "pass": False,
            "gate": gate_result.gate_name,
            "blockers": all_blockers,
            "warnings": all_warnings,
            "artifacts": all_artifacts,
            "next_actions": gate_result.next_actions or ["Fix transfer contract blockers and retry"],
        }
    else:
        result = {
            "pass": True,
            "gate": gate_result.gate_name,
            "blockers": [],
            "warnings": all_warnings,
            "artifacts": all_artifacts,
            "contract_ready": True,  # Contract passed; ready for PCB creation or pad-net assignment
            "next_actions": gate_result.next_actions,
        }

    if op.dry_run:
        result["dry_run"] = True

    return result
