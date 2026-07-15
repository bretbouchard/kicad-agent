"""Constraint propagator and completeness gate for PCB setup.

ConstraintPropagator writes design constraints into .kicad_dru net classes
via the existing project/design_rules.py serialization layer.

ConstraintCompletenessGate validates that all nontrivial nets (identified by
Phase 86 schematic intent classification) have electrical constraints before
allowing the PCB_SETUP -> PLACEMENT transition.

This gate is the SOLE gate for the PCB_SETUP -> PLACEMENT transition.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from volta.analysis.types import NetClassification
from volta.project.design_rules import (
    DesignRulesFile,
    NetClassDef,
    parse_design_rules,
)
from volta.validation.gate_runner import register_gate
from volta.validation.gate_types import DesignStage, GateDefinition, GateResult
from volta.validation.gates.constraint_schema import (
    DesignConstraints,
    ElectricalConstraints,
)

logger = logging.getLogger(__name__)

# Nets with these classifications are "nontrivial" and MUST have
# electrical constraints assigned before placement begins.
_NONTRIVIAL_CLASSIFICATIONS = frozenset({
    NetClassification.POWER,
    NetClassification.HIGH_CURRENT,
    NetClassification.DIFFERENTIAL_PAIR,
    NetClassification.CLOCK,
})


class ConstraintPropagator:
    """Propagates design constraints into .kicad_dru net class definitions.

    Uses the existing project/design_rules.py (DesignRulesFile, NetClassDef)
    as the serialization layer. Loads existing .kicad_dru if present,
    converts ElectricalConstraints to NetClassDef instances, and writes
    back via DesignRulesFile.to_file().
    """

    def propagate(
        self,
        constraints: DesignConstraints,
        dru_path: Path,
    ) -> list[str]:
        """Write constraint net classes into .kicad_dru.

        Args:
            constraints: The DesignConstraints to propagate.
            dru_path: Path to the .kicad_dru file (created if missing).

        Returns:
            List of warning strings (empty = all OK).
        """
        warnings: list[str] = []

        # Load existing DRU file if present
        if dru_path.exists():
            try:
                dru = parse_design_rules(dru_path)
            except (ValueError, FileNotFoundError):
                dru = DesignRulesFile()
        else:
            dru = DesignRulesFile()

        # Check achievability before writing
        warnings.extend(
            constraints.fab.validate_achievable(constraints.electrical)
        )

        # Convert each ElectricalConstraints to a NetClassDef and add
        existing_names = {nc.name for nc in dru.net_classes}
        for ec in constraints.electrical:
            class_name = ec.net_name
            description = self._build_description(ec)

            nc_def = self._electrical_to_net_class(ec, class_name, description)

            if class_name in existing_names:
                logger.info(
                    "Net class '%s' already exists in .kicad_dru, skipping",
                    class_name,
                )
                continue

            try:
                dru.add_net_class(nc_def)
                logger.info(
                    "Propagated net class '%s' from constraints", class_name
                )
            except ValueError as e:
                warnings.append(
                    f"Failed to add net class '{class_name}': {e}"
                )

        # Write back to file
        dru.to_file(dru_path)
        logger.info("Wrote %d net classes to %s", len(dru.net_classes), dru_path)

        return warnings

    def _build_description(self, ec: ElectricalConstraints) -> str:
        """Build a human-readable description for the net class."""
        parts: list[str] = []
        if ec.impedance_ohm is not None:
            parts.append(f"{ec.impedance_ohm}ohm")
        if ec.current_ma is not None:
            parts.append(f"{ec.current_ma}mA")
        if ec.diff_pair is not None:
            parts.append(f"diff_pair({ec.diff_pair.pair_name})")
        if ec.frequency_hz is not None:
            parts.append(f"{ec.frequency_hz}Hz")
        return " ".join(parts) if parts else ""

    def _electrical_to_net_class(
        self,
        ec: ElectricalConstraints,
        name: str,
        description: str,
    ) -> NetClassDef:
        """Convert an ElectricalConstraints to a NetClassDef.

        Maps impedance to diff_pair_width/gap, current to track_width,
        and uses fab profile minimums where not specified.
        """
        # Default dimensions from impedance calculation (simplified):
        # 50-ohm microstrip on 2-layer 1.6mm FR4 ~ 2.7mm width
        track_width = 0.25
        clearance = 0.15
        diff_pair_width = 0.0
        diff_pair_gap = 0.0
        via_drill = 0.3

        if ec.impedance_ohm is not None:
            # Rough approximation for microstrip on 1.6mm FR4
            if ec.impedance_ohm >= 50:
                track_width = 0.15  # narrower for higher impedance
                clearance = 0.15
            else:
                track_width = 0.25  # wider for lower impedance
                clearance = 0.2

        if ec.current_ma is not None and ec.current_ma > 500:
            # Wider trace for high current: ~1mm per 1A at 10C rise
            track_width = max(track_width, ec.current_ma / 1000.0)

        if ec.diff_pair is not None:
            diff_pair_gap = ec.diff_pair.gap_mm
            diff_pair_width = max(ec.diff_pair.gap_mm * 2, track_width)

        if ec.voltage_v is not None and ec.voltage_v > 60:
            clearance = max(clearance, 0.5)

        return NetClassDef(
            name=name,
            description=description,
            clearance=clearance,
            track_width=track_width,
            via_diameter=via_drill * 2,
            via_drill=via_drill,
            diff_pair_width=diff_pair_width,
            diff_pair_gap=diff_pair_gap,
        )


class ConstraintCompletenessGate:
    """Validates that nontrivial nets have electrical constraints.

    Checks that nets classified as POWER, HIGH_CURRENT, DIFFERENTIAL_PAIR,
    or CLOCK (from Phase 86 schematic intent) have corresponding
    ElectricalConstraints entries.

    This is the SOLE gate for the PCB_SETUP -> PLACEMENT transition.
    """

    def run(self, context: dict[str, Any]) -> GateResult:
        """Execute the constraint completeness check.

        Args:
            context: Must contain:
                - "design_constraints": DesignConstraints instance
                - "net_intent": dict[str, NetClassification] mapping
                  net names to their classifications

        Returns:
            GateResult with pass/fail status for PCB_SETUP -> PLACEMENT.
        """
        design_constraints = context.get("design_constraints")
        net_intent: dict[str, Any] = context.get("net_intent", {})

        if design_constraints is None:
            return GateResult(
                pass_=False,
                gate_name="constraint_completeness",
                stage=DesignStage.PCB_SETUP,
                blockers=[
                    "No design_constraints found in context. "
                    "Run constraint propagation before placement."
                ],
            )

        if not isinstance(design_constraints, DesignConstraints):
            return GateResult(
                pass_=False,
                gate_name="constraint_completeness",
                stage=DesignStage.PCB_SETUP,
                blockers=[
                    f"design_constraints has wrong type: "
                    f"{type(design_constraints).__name__}, "
                    f"expected DesignConstraints"
                ],
            )

        warnings: list[str] = []
        blockers: list[str] = []
        artifacts: list[str] = []

        # Identify nontrivial nets from net_intent
        nontrivial_nets: dict[str, NetClassification] = {}
        for net_name, classification in net_intent.items():
            if isinstance(classification, NetClassification):
                if classification in _NONTRIVIAL_CLASSIFICATIONS:
                    nontrivial_nets[net_name] = classification

        # Build index of nets that have electrical constraints
        constrained_net_names = {
            ec.net_name for ec in design_constraints.electrical
        }

        # Check each nontrivial net has constraints
        missing_nets: list[str] = []
        for net_name, classification in nontrivial_nets.items():
            if net_name not in constrained_net_names:
                missing_nets.append(
                    f"{net_name} ({classification.value})"
                )

        if missing_nets:
            blockers.append(
                f"Nontrivial nets missing electrical constraints: "
                f"{', '.join(missing_nets)}. "
                f"Add constraints before placement."
            )
            blockers.append(
                "Nets classified as POWER, HIGH_CURRENT, "
                "DIFFERENTIAL_PAIR, or CLOCK require explicit "
                "electrical constraints."
            )

        # Check fab profile is not all defaults
        fab = design_constraints.fab
        if (
            fab.min_trace_width_mm == 0.15
            and fab.min_drill_mm == 0.2
            and fab.min_clearance_mm == 0.15
            and fab.layer_count == 2
            and fab.material == "FR-4"
        ):
            warnings.append(
                "Fab profile uses all default values. "
                "Consider selecting a specific manufacturer preset "
                "(jlcpcb, jlcpcb_4layer, pcbway, osh_park)."
            )

        # Cross-constraint validation
        cross_warnings = design_constraints.validate_cross_constraints()
        warnings.extend(cross_warnings)

        # Build artifacts
        artifacts.append(
            f"{len(design_constraints.electrical)} electrical constraints"
        )
        if design_constraints.mechanical is not None:
            artifacts.append("mechanical constraints present")
        artifacts.append(
            f"fab profile: {fab.layer_count}-layer {fab.material}"
        )

        passed = len(blockers) == 0
        next_actions = (
            ["Proceed to placement stage"]
            if passed
            else ["Add missing constraints and re-run gate"]
        )

        return GateResult(
            pass_=passed,
            gate_name="constraint_completeness",
            stage=DesignStage.PCB_SETUP,
            blockers=blockers,
            warnings=warnings,
            artifacts=artifacts,
            next_actions=next_actions,
        )


# ---------------------------------------------------------------------------
# Module-level gate registration (matches schematic_intent_gate.py:447-458)
# ---------------------------------------------------------------------------

_gate = ConstraintCompletenessGate()

register_gate(
    GateDefinition(
        name="constraint_completeness",
        from_stage=DesignStage.PCB_SETUP,
        to_stage=DesignStage.PLACEMENT,
        check_fn_name="constraint_completeness_gate",
    ),
    check_fn=_gate.run,
)
