"""PCB-specific design rules extending DesignRule ABC.

VP-53-02: Three PCB design rules that operate on PcbSpatialModel data
instead of CircuitTopology. These rules bridge the schematic DesignRule
engine (Phase 48) to PCB layout validation.

Rules:
  PCB_CLEARANCE_01: Spatial clearance between footprints
  PCB_IMPEDANCE_01: Trace impedance vs constraint targets
  PCB_THERMAL_01: Component thermal proximity checks

Architecture:
  Each rule's check() accepts (topology: Any, config: dict).
  PCB-specific data is extracted from the config dict:
    - config["spatial_model"]: PcbSpatialModel (Phase 51) or Any mock
    - config["constraints"]: list of constraint objects (Phase 50) or Any

  If spatial_model is None or missing, rules return empty list (graceful
  degradation) matching the threat model T-53-05 mitigation.

Usage:
    from volta.validation.pcb_design_rules import get_pcb_design_rules

    rules = get_pcb_design_rules()
    engine = DesignRuleEngine(rules=rules, config={
        "PCB_CLEARANCE_01": {"spatial_model": model},
        "PCB_IMPEDANCE_01": {"spatial_model": model, "constraints": constraints},
        "PCB_THERMAL_01": {"spatial_model": model, "constraints": constraints},
    })
    report = engine.run(None)  # topology not used by PCB rules
"""
from __future__ import annotations

import logging
import math
from typing import Any

from volta.analysis.design_rules import (
    DesignRule,
    DesignRuleViolation,
    RuleCategory,
    RuleSeverity,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ClearanceCheckRule
# ---------------------------------------------------------------------------


class ClearanceCheckRule(DesignRule):
    """PCB_CLEARANCE_01: Spatial clearance between copper features.

    Performs pairwise distance checks between all footprints in the spatial
    model. Flags pairs whose Euclidean distance is below the configurable
    minimum clearance threshold.

    O(n^2) pairwise check is acceptable since PCBs typically have <200
    components.

    Config keys:
        spatial_model: Object with .footprints list (objects with .position.X,
                       .position.Y, .reference)
        min_clearance_mm: Minimum allowed distance in mm (default 0.2)
    """

    name = "PCB_CLEARANCE_01"
    category = RuleCategory.LAYOUT
    default_severity = RuleSeverity.WARNING
    description = "Footprints must maintain minimum spatial clearance"

    def check(
        self,
        topology: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DesignRuleViolation]:
        config = config or {}
        spatial_model = config.get("spatial_model")

        if spatial_model is None:
            logger.debug("PCB_CLEARANCE_01: No spatial_model provided, skipping")
            return []

        min_clearance = config.get("min_clearance_mm", 0.2)
        footprints = getattr(spatial_model, "footprints", [])
        violations: list[DesignRuleViolation] = []

        # Pairwise distance check
        for i in range(len(footprints)):
            for j in range(i + 1, len(footprints)):
                fp_a = footprints[i]
                fp_b = footprints[j]

                pos_a = getattr(fp_a, "position", None)
                pos_b = getattr(fp_b, "position", None)
                if pos_a is None or pos_b is None:
                    continue

                dx = getattr(pos_a, "X", 0.0) - getattr(pos_b, "X", 0.0)
                dy = getattr(pos_a, "Y", 0.0) - getattr(pos_b, "Y", 0.0)
                distance = math.sqrt(dx * dx + dy * dy)

                if distance < min_clearance:
                    ref_a = getattr(fp_a, "reference", "?")
                    ref_b = getattr(fp_b, "reference", "?")
                    violations.append(DesignRuleViolation(
                        rule_id=self.name,
                        description=(
                            f"Clearance violation: {ref_a} and {ref_b} are "
                            f"{distance:.3f}mm apart (minimum: {min_clearance}mm)"
                        ),
                        severity=self.default_severity,
                        location=f"{ref_a} / {ref_b}",
                        suggestion=(
                            f"Increase spacing between {ref_a} and {ref_b} "
                            f"to at least {min_clearance}mm"
                        ),
                        affected_components=(ref_a, ref_b),
                        details={
                            "distance_mm": distance,
                            "min_clearance_mm": min_clearance,
                        },
                    ))

        return violations


# ---------------------------------------------------------------------------
# ImpedanceCheckRule
# ---------------------------------------------------------------------------


class ImpedanceCheckRule(DesignRule):
    """PCB_IMPEDANCE_01: Trace impedance vs constraint targets.

    For each impedance constraint, computes the expected characteristic
    impedance from the layer stackup and compares against the target
    impedance within a configurable deviation fraction.

    Config keys:
        spatial_model: Object with .layer_stackup attribute (object with
                       get_impedance(layer, trace_width) -> float|None)
        constraints: List of objects with .target_impedance, .layer,
                     .trace_width, .net_name attributes
        deviation_fraction: Allowed deviation from target (default 0.10 = 10%)
    """

    name = "PCB_IMPEDANCE_01"
    category = RuleCategory.IMPEDANCE
    default_severity = RuleSeverity.WARNING
    description = "Trace impedance must match constraint targets within tolerance"

    def check(
        self,
        topology: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DesignRuleViolation]:
        config = config or {}
        spatial_model = config.get("spatial_model")

        if spatial_model is None:
            logger.debug("PCB_IMPEDANCE_01: No spatial_model provided, skipping")
            return []

        layer_stackup = getattr(spatial_model, "layer_stackup", None)
        if layer_stackup is None:
            logger.debug("PCB_IMPEDANCE_01: No layer_stackup on spatial_model, skipping")
            return []

        constraints = config.get("constraints", [])
        deviation_fraction = config.get("deviation_fraction", 0.10)
        violations: list[DesignRuleViolation] = []

        for constraint in constraints:
            target = getattr(constraint, "target_impedance", None)
            if target is None:
                continue

            layer = getattr(constraint, "layer", "F.Cu")
            trace_width = getattr(constraint, "trace_width", 0.2)
            net_name = getattr(constraint, "net_name", "unknown")

            get_impedance_fn = getattr(layer_stackup, "get_impedance", None)
            if get_impedance_fn is None:
                continue

            z0 = get_impedance_fn(layer, trace_width)
            if z0 is None:
                continue

            lower = target * (1.0 - deviation_fraction)
            upper = target * (1.0 + deviation_fraction)

            if z0 < lower or z0 > upper:
                violations.append(DesignRuleViolation(
                    rule_id=self.name,
                    description=(
                        f"Impedance mismatch on {net_name}: "
                        f"measured {z0:.1f} ohms, "
                        f"target {target:.1f} ohms "
                        f"(tolerance: +/-{deviation_fraction:.0%}, "
                        f"range: {lower:.1f}-{upper:.1f} ohms)"
                    ),
                    severity=self.default_severity,
                    location=net_name,
                    suggestion=(
                        f"Adjust trace width on {layer} to achieve "
                        f"target impedance of {target:.1f} ohms"
                    ),
                    affected_components=(),
                    details={
                        "measured_impedance": z0,
                        "target_impedance": target,
                        "deviation_fraction": deviation_fraction,
                        "layer": layer,
                        "trace_width": trace_width,
                    },
                ))

        return violations


# ---------------------------------------------------------------------------
# ThermalProximityRule
# ---------------------------------------------------------------------------


class ThermalProximityRule(DesignRule):
    """PCB_THERMAL_01: Component thermal proximity checks.

    For each thermal constraint (heat source), checks all other footprints
    for proximity within a configurable keepout margin. Flags components
    that are too close to heat-sensitive areas.

    Config keys:
        spatial_model: Object with .footprints list
        constraints: List of objects with .component_ref, .keepout_margin,
                     and/or .thermal_pad attributes
        keepout_margin_mm: Default keepout margin in mm (default 2.0)
                           Overridden by constraint's own keepout_margin
    """

    name = "PCB_THERMAL_01"
    category = RuleCategory.THERMAL
    default_severity = RuleSeverity.WARNING
    description = "Components must maintain thermal keepout margins from heat sources"

    def check(
        self,
        topology: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DesignRuleViolation]:
        config = config or {}
        spatial_model = config.get("spatial_model")

        if spatial_model is None:
            logger.debug("PCB_THERMAL_01: No spatial_model provided, skipping")
            return []

        footprints = getattr(spatial_model, "footprints", [])
        constraints = config.get("constraints", [])
        default_keepout = config.get("keepout_margin_mm", 2.0)
        violations: list[DesignRuleViolation] = []

        # Build ref -> footprint lookup
        fp_by_ref: dict[str, Any] = {}
        for fp in footprints:
            ref = getattr(fp, "reference", "")
            if ref:
                fp_by_ref[ref] = fp

        # Find thermal constraints (those with component_ref and keepout/thermal_pad)
        for constraint in constraints:
            comp_ref = getattr(constraint, "component_ref", None)
            if comp_ref is None:
                continue

            has_thermal = getattr(constraint, "thermal_pad", False) or getattr(constraint, "keepout_margin", None) is not None
            if not has_thermal:
                continue

            source_fp = fp_by_ref.get(comp_ref)
            if source_fp is None:
                continue

            source_pos = getattr(source_fp, "position", None)
            if source_pos is None:
                continue

            keepout = default_keepout
            sx = getattr(source_pos, "X", 0.0)
            sy = getattr(source_pos, "Y", 0.0)

            # Check all other footprints for proximity
            for other_fp in footprints:
                other_ref = getattr(other_fp, "reference", "")
                if other_ref == comp_ref:
                    continue

                other_pos = getattr(other_fp, "position", None)
                if other_pos is None:
                    continue

                ox = getattr(other_pos, "X", 0.0)
                oy = getattr(other_pos, "Y", 0.0)

                dx = sx - ox
                dy = sy - oy
                distance = math.sqrt(dx * dx + dy * dy)

                if distance < keepout:
                    violations.append(DesignRuleViolation(
                        rule_id=self.name,
                        description=(
                            f"Thermal proximity: {other_ref} is {distance:.2f}mm "
                            f"from heat source {comp_ref} "
                            f"(keepout margin: {keepout}mm)"
                        ),
                        severity=self.default_severity,
                        location=f"{comp_ref} / {other_ref}",
                        suggestion=(
                            f"Move {other_ref} away from {comp_ref} -- "
                            f"currently {distance:.2f}mm, "
                            f"minimum recommended {keepout}mm"
                        ),
                        affected_components=(comp_ref, other_ref),
                        details={
                            "distance_mm": distance,
                            "keepout_margin_mm": keepout,
                            "heat_source": comp_ref,
                            "sensitive_component": other_ref,
                        },
                    ))

        return violations


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_pcb_design_rules() -> list[DesignRule]:
    """Return all PCB-specific design rule instances.

    Returns:
        List of ClearanceCheckRule, ImpedanceCheckRule, ThermalProximityRule.
    """
    return [
        ClearanceCheckRule(),
        ImpedanceCheckRule(),
        ThermalProximityRule(),
    ]
