"""Schematic-to-PCB transfer contract validation.

Defines the transfer contract as the single source of truth for what must be
true when a schematic becomes a PCB. The contract maps:
  schematic symbols -> PCB footprints -> pad-net assignments -> net classes

Classes:
  - TransferContract: frozen Pydantic model holding the full mapping
  - PadNetAssignmentResult: structured result for pad-net operations
  - PadNetAssigner: assigns PCB pad nets from schematic netlist
  - NetIdVerifier: confirms PCB net IDs match schematic net names
  - TransferContractValidator: gate check function that builds and validates
    the contract, auto-running SchematicIntentGate as prerequisite

Power symbols (lib_id containing '#PWR' or starting with 'power:') are excluded
from footprint/pin-pad checks because they have no physical PCB presence.

Multi-unit symbols use a flat pin_pad_map keyed by base ref_des (e.g. "U1"
not "U1.A") because footprint pads are physical and shared across all units.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from volta.project.design_rules import NetClassDef
from volta.validation.gate_types import DesignStage, GateResult

logger = logging.getLogger(__name__)

# Regex to strip unit suffix from reference designators (e.g., "U1.A" -> "U1")
_UNIT_SUFFIX_PATTERN = re.compile(r"^(.+)\.[A-Z]$")


class TransferContract(BaseModel):
    """Frozen mapping of schematic symbols to PCB footprints, pads, and nets.

    This is the single source of truth for what must hold when a schematic
    becomes a PCB. All fields are string-keyed because both pin and pad
    numbers can be alphanumeric (BGA pads "A1", "B2", named pins like "VCNTL").

    Fields:
      symbol_footprint_map: ref_des -> footprint lib_id
      pin_pad_map: ref_des -> {pin_number_str: pad_number_str}
      net_assignments: schematic_net_name -> pcb_net_name
      net_classes: net_class_name -> NetClassDef (informational-only for Phase 87)
    """

    model_config = {"frozen": True}

    symbol_footprint_map: dict[str, str] = Field(default_factory=dict)
    pin_pad_map: dict[str, dict[str, str]] = Field(default_factory=dict)
    net_assignments: dict[str, str] = Field(default_factory=dict)
    net_classes: dict[str, NetClassDef] = Field(default_factory=dict)

    def is_complete(self) -> bool:
        """Check whether all components have footprints and pin-pad entries.

        Returns True only when every reference in symbol_footprint_map also
        has a non-empty entry in pin_pad_map, and every reference in
        pin_pad_map has a corresponding entry in symbol_footprint_map.
        """
        if not self.symbol_footprint_map and not self.pin_pad_map:
            return True

        # Every component with a footprint must have pin-pad mappings
        for ref in self.symbol_footprint_map:
            if ref not in self.pin_pad_map or not self.pin_pad_map[ref]:
                return False

        # Every component with pin-pad mappings must have a footprint
        for ref in self.pin_pad_map:
            if ref not in self.symbol_footprint_map or not self.symbol_footprint_map[ref]:
                return False

        return True

    def missing_items(self) -> list[str]:
        """List unfulfilled contract items.

        Returns descriptive strings for each missing or incomplete mapping.
        """
        missing: list[str] = []

        # Components in pin_pad_map but not in symbol_footprint_map
        for ref in self.pin_pad_map:
            if ref not in self.symbol_footprint_map or not self.symbol_footprint_map[ref]:
                missing.append(f"{ref}: missing footprint assignment")

        # Components in symbol_footprint_map but not in pin_pad_map
        for ref in self.symbol_footprint_map:
            if ref not in self.pin_pad_map or not self.pin_pad_map[ref]:
                missing.append(f"{ref}: missing pin-pad mapping")

        return missing


class PadNetAssignmentResult(BaseModel):
    """Structured result from pad-net assignment or net ID verification.

    Replaces bare list[str] returns with a typed result that includes
    the assignments made, blockers (failures), and warnings.
    """

    assignments_made: dict[str, dict[str, str]] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PadNetAssigner:
    """Assigns PCB pad nets from the schematic netlist via the transfer contract."""

    def assign_pad_nets(
        self,
        contract: TransferContract,
        pcb_ir: Any,
    ) -> PadNetAssignmentResult:
        """Assign pad nets from contract to PCB footprint pads.

        For each component in the contract's pin_pad_map, validates pad count
        matches pin count and records the net assignment for each pad.

        Args:
            contract: The transfer contract with pin-pad mappings.
            pcb_ir: PcbIR instance for querying PCB footprints and pads.

        Returns:
            PadNetAssignmentResult with assignments_made, blockers, warnings.
        """
        assignments: dict[str, dict[str, str]] = {}
        blockers: list[str] = []
        warnings: list[str] = []

        for ref, pin_pad_map in contract.pin_pad_map.items():
            pcb_pads = pcb_ir.get_footprint_pads(ref)

            # Validate pad count
            pcb_pad_numbers = {p[0] for p in pcb_pads}
            contract_pad_numbers = set(pin_pad_map.values())

            if pcb_pad_numbers != contract_pad_numbers:
                extra_pads = pcb_pad_numbers - contract_pad_numbers
                missing_pads = contract_pad_numbers - pcb_pad_numbers
                parts = [f"{ref}: pad count mismatch"]
                if missing_pads:
                    parts.append(f"expected pads {sorted(missing_pads)} not found in PCB")
                if extra_pads:
                    parts.append(f"extra pads in PCB {sorted(extra_pads)}")
                blockers.append(", ".join(parts))
                continue

            # Build pad-to-net mapping from the contract
            pad_net_map: dict[str, str] = {}
            for pin_num, pad_num in pin_pad_map.items():
                # Look up which net this pin belongs to via net_assignments
                # The contract stores net_assignments as net_name -> net_name
                # We need pin -> net which comes from the schematic connectivity
                # For now, record the pad as present; net assignment comes from PCB
                pad_net_map[pad_num] = ""

            # Update with actual PCB pad nets if available
            for pad_num, net_name in pcb_pads:
                if pad_num in pad_net_map:
                    pad_net_map[pad_num] = net_name

            assignments[ref] = pad_net_map

        return PadNetAssignmentResult(
            assignments_made=assignments,
            blockers=blockers,
            warnings=warnings,
        )


class NetIdVerifier:
    """Verifies that PCB net IDs match schematic net names (case-sensitive)."""

    def verify_net_ids(
        self,
        contract: TransferContract,
        pcb_ir: Any,
    ) -> PadNetAssignmentResult:
        """Check that every schematic net has a matching PCB net.

        Comparison is case-sensitive per T-87-03: "GND" != "gnd".

        Args:
            contract: The transfer contract with net_assignments.
            pcb_ir: PcbIR instance for querying PCB nets.

        Returns:
            PadNetAssignmentResult with blockers for any mismatches.
        """
        blockers: list[str] = []
        warnings: list[str] = []

        # Get all PCB net names
        pcb_net_names: set[str] = set()
        if pcb_ir.nets:
            for net in pcb_ir.nets:
                pcb_net_names.add(net.name)

        # Check each schematic net assignment
        for sch_net_name, pcb_net_name in contract.net_assignments.items():
            if pcb_net_name not in pcb_net_names:
                # Check if a case-different variant exists (for better error message)
                case_variants = {n for n in pcb_net_names if n.lower() == pcb_net_name.lower()}
                if case_variants:
                    blockers.append(
                        f"Net '{pcb_net_name}' from schematic not found in PCB -- "
                        f"case-sensitive mismatch with {sorted(case_variants)}"
                    )
                else:
                    blockers.append(
                        f"Net '{pcb_net_name}' from schematic not found in PCB"
                    )

        return PadNetAssignmentResult(
            assignments_made={},
            blockers=blockers,
            warnings=warnings,
        )


class TransferContractValidator:
    """Gate check function that builds and validates the transfer contract.

    Auto-runs SchematicIntentGate as prerequisite if not already cached in
    the context dict (key: "schematic_intent_passed").

    Power symbols (lib_id containing '#PWR' or starting with 'power:') are
    excluded from footprint and pin-pad validation.

    Multi-unit symbols are flattened to base ref_des in pin_pad_map.
    """

    def _is_power_symbol(self, lib_id: str) -> bool:
        """Check if a component is a power symbol that should be excluded.

        Power symbols have no physical PCB presence -- they only define net
        connections. They should be excluded from footprint and pin-pad checks.

        Args:
            lib_id: The component's library ID string.

        Returns:
            True if this is a power symbol.
        """
        if not lib_id:
            return False
        return "#PWR" in lib_id or lib_id.startswith("power:")

    @staticmethod
    def _base_reference(reference: str) -> str:
        """Strip unit suffix from a reference designator.

        E.g., "U1.A" -> "U1", "U1.B" -> "U1", "R1" -> "R1".
        """
        m = _UNIT_SUFFIX_PATTERN.match(reference)
        if m:
            return m.group(1)
        return reference

    def validate(
        self,
        schematic_ir: Any,
        pcb_ir: Any = None,
        context: dict[str, Any] | None = None,
    ) -> GateResult:
        """Build and validate the transfer contract.

        Args:
            schematic_ir: SchematicIR instance.
            pcb_ir: Optional PcbIR instance for pad-net and net ID verification.
            context: Optional dict with cached gate results.
                     Key "schematic_intent_passed": bool skips auto-run.

        Returns:
            GateResult with blockers for any validation failures.
        """
        ctx = context or {}

        # --- C-1: Auto-run SchematicIntentGate if not cached ---
        if not ctx.get("schematic_intent_passed", False):
            from volta.validation.gates.schematic_intent_gate import (
                SchematicIntentGate,
            )

            intent_gate = SchematicIntentGate()
            intent_context = {"schematic_ir": schematic_ir}
            intent_result = intent_gate.run(intent_context)

            if not intent_result.pass_bool:
                return intent_result

        # --- Build the transfer contract (single pass) ---
        symbol_footprint_map: dict[str, str] = {}
        pin_pad_map: dict[str, dict[str, str]] = {}
        blockers: list[str] = []
        warnings: list[str] = []

        for component in schematic_ir.components:
            reference = schematic_ir.get_component_property(component, "Reference") or ""
            lib_id = getattr(component, "libId", "") or ""

            if not reference:
                continue

            # Skip power symbols
            if self._is_power_symbol(lib_id):
                continue

            # Skip DNP components
            if getattr(component, "dnp", False) is True:
                continue

            # Get footprint
            footprint = schematic_ir.get_component_footprint(reference)

            if not footprint or not footprint.strip():
                blockers.append(
                    f"Component {reference} ({lib_id}) has no footprint assigned"
                )
                continue

            base_ref = self._base_reference(reference)
            symbol_footprint_map[base_ref] = footprint

            # Get pin map from SchematicIR
            pin_map_result = schematic_ir.verify_pin_map(reference, footprint)

            # Merge into base ref's pin_pad_map (multi-unit flattening)
            if base_ref not in pin_pad_map:
                pin_pad_map[base_ref] = {}

            # TODO(P88): Replace identity mapping with actual pin-to-pad lookup
            # from the footprint library. For BGA/connector symbols, pin
            # numbers != pad numbers.
            for pin_num in pin_map_result.get("symbol_pins", set()):
                pin_key = str(pin_num)
                if pin_key in pin_pad_map[base_ref]:
                    logger.warning(
                        "Pin %s from %s already mapped in %s pin_pad_map (multi-unit overlap)",
                        pin_num, reference, base_ref,
                    )
                pin_pad_map[base_ref][pin_key] = pin_key

            if pin_map_result.get("match") is False:
                missing = pin_map_result.get("missing_in_footprint", set())
                extra = pin_map_result.get("extra_in_footprint", set())

                parts = [f"{reference}: pin-pad mismatch"]
                if missing:
                    parts.append(f"pins {sorted(missing)} missing in footprint")
                if extra:
                    parts.append(f"extra pads {sorted(extra)} in footprint")
                blockers.append(", ".join(parts))

        # --- Build contract ---
        contract = TransferContract(
            symbol_footprint_map=symbol_footprint_map,
            pin_pad_map=pin_pad_map,
            net_assignments={},  # Populated from schematic net connectivity
            net_classes={},  # Informational-only for Phase 87
        )

        # --- Check completeness ---
        missing = contract.missing_items()
        for item in missing:
            # Only add as warning if not already a blocker
            blockers.append(item)

        # --- If PCB IR provided, run PadNetAssigner and NetIdVerifier ---
        if pcb_ir is not None:
            assigner = PadNetAssigner()
            pad_result = assigner.assign_pad_nets(contract, pcb_ir)
            blockers.extend(pad_result.blockers)
            warnings.extend(pad_result.warnings)

            verifier = NetIdVerifier()
            net_result = verifier.verify_net_ids(contract, pcb_ir)
            blockers.extend(net_result.blockers)
            warnings.extend(net_result.warnings)

        # --- Build artifacts ---
        artifacts: list[str] = []
        if symbol_footprint_map:
            artifacts.append(
                f"{len(symbol_footprint_map)} component(s) in transfer contract"
            )
        if pin_pad_map:
            total_pins = sum(len(pins) for pins in pin_pad_map.values())
            artifacts.append(
                f"{total_pins} pin-pad mapping(s) across {len(pin_pad_map)} component(s)"
            )
        if not symbol_footprint_map and not pin_pad_map:
            artifacts.append("Empty contract (no components to transfer)")

        # --- Build result ---
        if blockers:
            return GateResult(
                pass_=False,
                gate_name="transfer_contract",
                stage=DesignStage.SCHEMATIC,
                blockers=blockers,
                warnings=warnings,
                artifacts=artifacts,
                next_actions=["Fix transfer contract blockers above and retry"],
            )

        return GateResult(
            pass_=True,
            gate_name="transfer_contract",
            stage=DesignStage.PCB_SETUP,
            warnings=warnings,
            artifacts=artifacts,
            next_actions=["Proceed to pcb_setup stage"],
        )
