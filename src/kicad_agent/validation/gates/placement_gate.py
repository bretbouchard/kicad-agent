"""Placement readiness gate -- validates placement quality before routing.

Six sub-checks validate placement quality:
1. Footprint bounds: All footprints inside board outline
2. Courtyard clearance: No courtyard overlaps
3. Mechanical positions: Connectors at edge, mounting holes at corners
4. Decoupling proximity: Bypass caps within 5mm of IC power pins
5. Thermal spacing: Hot components have adequate clearance
6. Routability heuristics: Density, ratsnest, blocked channels

Plus an analog/digital grouping check that warns when sections overlap.

Gate registers as placement_readiness for PLACEMENT -> ROUTING transition.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from kicad_agent.analysis.types import NetClassification
from kicad_agent.validation.gate_runner import register_gate
from kicad_agent.validation.gate_types import DesignStage, GateDefinition, GateResult
from kicad_agent.validation.gates.component_classifier import (
    ComponentRole,
    ComponentTypeClassifier,
)

logger = logging.getLogger(__name__)

# Thresholds
_DECOUPLING_MAX_DISTANCE_MM = 5.0
_THERMAL_DEFAULT_CLEARANCE_MM = 3.0
_CONNECTOR_EDGE_MAX_MM = 5.0
_MOUNTING_HOLE_CORNER_MAX_MM = 15.0
_DENSITY_WARNING_THRESHOLD = 0.7
_BLOCKED_CHANNEL_MIN_MM = 2.0
_ANALOG_DIGITAL_OVERLAP_MM = 20.0


# ---------------------------------------------------------------------------
# PlacementReadinessGate
# ---------------------------------------------------------------------------


class PlacementReadinessGate:
    """Validates placement quality across 6 sub-checks before routing.

    Context dict requires:
        - "pcb_ir": PcbIR instance
        - "schematic_ir": SchematicIR instance (for net_intent)
        - "constraints": DesignConstraints instance
        - "net_classifications": Optional pre-computed dict[str, NetClassification]
    """

    def run(self, context: dict[str, Any]) -> GateResult:
        """Execute all placement readiness sub-checks.

        Returns GateResult with pass/fail for PLACEMENT -> ROUTING transition.
        """
        pcb_ir = context.get("pcb_ir")
        schematic_ir = context.get("schematic_ir")
        constraints = context.get("constraints")

        if pcb_ir is None:
            return GateResult(
                pass_=False,
                gate_name="placement_readiness",
                stage=DesignStage.PLACEMENT,
                blockers=["No pcb_ir in context. Load a PCB before checking placement."],
            )

        # Get or compute net classifications
        net_classifications: dict[str, NetClassification] = context.get(
            "net_classifications", {}
        )
        if not net_classifications and schematic_ir is not None:
            try:
                from kicad_agent.validation.gates.net_intent import NetIntentExtractor
                net_classifications = NetIntentExtractor().extract_nets(schematic_ir)
            except Exception as exc:
                logger.warning("Failed to extract net intent: %s", exc)

        # Run sub-checks
        all_blockers: list[str] = []
        all_warnings: list[str] = []

        for check_fn in [
            lambda: self._check_footprint_bounds(pcb_ir),
            lambda: self._check_courtyard_clearance(pcb_ir),
            lambda: self._check_mechanical_positions(pcb_ir),
            lambda: self._check_decoupling_proximity(
                pcb_ir, schematic_ir, constraints, net_classifications
            ),
            lambda: self._check_thermal_spacing(
                pcb_ir, constraints, net_classifications
            ),
            lambda: self._check_routability(pcb_ir, constraints),
        ]:
            blockers, warnings = check_fn()
            all_blockers.extend(blockers)
            all_warnings.extend(warnings)

        # Analog/digital grouping check
        grouping_warnings = self._check_analog_digital_grouping(
            pcb_ir, net_classifications
        )
        all_warnings.extend(grouping_warnings)

        # Build artifacts
        artifacts: list[str] = []
        fp_count = len(pcb_ir.footprints)
        artifacts.append(f"{fp_count} footprints checked")

        board_bounds = pcb_ir.get_board_bounds()
        if board_bounds:
            w = board_bounds[2] - board_bounds[0]
            h = board_bounds[3] - board_bounds[1]
            artifacts.append(f"board: {w:.1f} x {h:.1f} mm")

        passed = len(all_blockers) == 0
        next_actions = (
            ["Proceed to routing stage"]
            if passed
            else ["Fix placement issues and re-run gate"]
        )

        return GateResult(
            pass_=passed,
            gate_name="placement_readiness",
            stage=DesignStage.PLACEMENT,
            blockers=all_blockers,
            warnings=all_warnings,
            artifacts=artifacts,
            next_actions=next_actions,
        )

    # -----------------------------------------------------------------------
    # Sub-check 1: Footprint bounds
    # -----------------------------------------------------------------------

    def _check_footprint_bounds(
        self, pcb_ir: Any
    ) -> tuple[list[str], list[str]]:
        """Check all footprints are inside the board outline."""
        blockers: list[str] = []
        warnings: list[str] = []

        board_bounds = pcb_ir.get_board_bounds()
        if board_bounds is None:
            warnings.append("No board outline found, skipping bounds check")
            return blockers, warnings

        bx_min, by_min, bx_max, by_max = board_bounds
        margin = 1.0  # near-edge warning margin in mm

        for fp in pcb_ir.footprints:
            ref = fp.properties.get("Reference", "?")
            try:
                fp_bounds = self._footprint_bounds(pcb_ir, ref)
            except (KeyError, ValueError):
                continue

            fx_min, fy_min, fx_max, fy_max = fp_bounds

            # Check if footprint is completely outside
            if (fx_max < bx_min or fx_min > bx_max
                    or fy_max < by_min or fy_min > by_max):
                blockers.append(
                    f"Footprint {ref} is outside board outline"
                )
            # Check if footprint is near edge
            elif (fx_min < bx_min + margin or fx_max > bx_max - margin
                  or fy_min < by_min + margin or fy_max > by_max - margin):
                warnings.append(
                    f"Footprint {ref} is within {margin}mm of board edge"
                )

        return blockers, warnings

    # -----------------------------------------------------------------------
    # Sub-check 2: Courtyard clearance
    # -----------------------------------------------------------------------

    def _check_courtyard_clearance(
        self, pcb_ir: Any
    ) -> tuple[list[str], list[str]]:
        """Check no courtyard overlaps between footprints."""
        blockers: list[str] = []
        warnings: list[str] = []

        footprints = pcb_ir.footprints
        refs_bounds: list[tuple[str, tuple[float, float, float, float]]] = []

        for fp in footprints:
            ref = fp.properties.get("Reference", "?")
            try:
                bounds = self._footprint_bounds(pcb_ir, ref)
            except (KeyError, ValueError):
                continue
            refs_bounds.append((ref, bounds))

        # O(n^2) with bounding-box spatial pruning
        for i in range(len(refs_bounds)):
            ref1, (x1_min, y1_min, x1_max, y1_max) = refs_bounds[i]
            for j in range(i + 1, len(refs_bounds)):
                ref2, (x2_min, y2_min, x2_max, y2_max) = refs_bounds[j]

                # Quick bounding box non-overlap check
                if (x1_max <= x2_min or x2_max <= x1_min
                        or y1_max <= y2_min or y2_max <= y1_min):
                    continue

                # Bounding boxes overlap — this is a courtyard overlap
                blockers.append(
                    f"Courtyard overlap between {ref1} and {ref2}"
                )

        return blockers, warnings

    # -----------------------------------------------------------------------
    # Sub-check 3: Mechanical positions
    # -----------------------------------------------------------------------

    def _check_mechanical_positions(
        self, pcb_ir: Any
    ) -> tuple[list[str], list[str]]:
        """Check connectors at board edge, mounting holes near corners."""
        blockers: list[str] = []
        warnings: list[str] = []

        board_bounds = pcb_ir.get_board_bounds()
        if board_bounds is None:
            return blockers, warnings

        bx_min, by_min, bx_max, by_max = board_bounds
        corners = [
            (bx_min, by_min), (bx_max, by_min),
            (bx_min, by_max), (bx_max, by_max),
        ]

        classifier = ComponentTypeClassifier()

        for fp in pcb_ir.footprints:
            ref = fp.properties.get("Reference", "?")
            lib_id = (
                getattr(fp, "lib_id", None)
                or getattr(fp, "libId", "")
            )
            role = classifier.classify(lib_id)

            try:
                x, y, _ = self._footprint_position(pcb_ir, ref)
            except (KeyError, ValueError):
                continue

            # Connector check
            if role == ComponentRole.CONNECTOR:
                dist_to_edge = min(
                    abs(x - bx_min), abs(x - bx_max),
                    abs(y - by_min), abs(y - by_max),
                )
                if dist_to_edge > _CONNECTOR_EDGE_MAX_MM:
                    warnings.append(
                        f"Connector {ref} is {dist_to_edge:.1f}mm from board edge "
                        f"(recommended < {_CONNECTOR_EDGE_MAX_MM}mm)"
                    )

            # Mounting hole check
            lib_upper = lib_id.upper()
            is_mounting = "MOUNTING" in lib_upper or "MOUNTHOLE" in lib_upper
            if is_mounting:
                dist_to_nearest_corner = min(
                    math.hypot(x - cx, y - cy) for cx, cy in corners
                )
                if dist_to_nearest_corner > _MOUNTING_HOLE_CORNER_MAX_MM:
                    warnings.append(
                        f"Mounting hole {ref} is {dist_to_nearest_corner:.1f}mm "
                        f"from nearest corner (recommended < {_MOUNTING_HOLE_CORNER_MAX_MM}mm)"
                    )

        return blockers, warnings

    # -----------------------------------------------------------------------
    # Sub-check 4: Decoupling proximity
    # -----------------------------------------------------------------------

    def _check_decoupling_proximity(
        self,
        pcb_ir: Any,
        schematic_ir: Any,
        constraints: Any,
        net_classifications: dict[str, NetClassification],
    ) -> tuple[list[str], list[str]]:
        """Check decoupling caps are near their associated ICs."""
        warnings: list[str] = []
        blockers: list[str] = []

        classifier = ComponentTypeClassifier()

        # Classify all components and collect their positions
        fp_data: list[tuple[str, ComponentRole, float, float, list[str]]] = []
        for fp in pcb_ir.footprints:
            ref = fp.properties.get("Reference", "?")
            lib_id = (
                getattr(fp, "lib_id", None)
                or getattr(fp, "libId", "")
            )
            try:
                x, y, _ = self._footprint_position(pcb_ir, ref)
            except (KeyError, ValueError):
                continue

            # Get connected net names
            net_names: list[str] = []
            for pad in fp.pads:
                if pcb_ir._is_native:
                    net_name = pad.net_name
                else:
                    net_name = pad.net.name if pad.net is not None else ""
                if net_name and net_name not in net_names:
                    net_names.append(net_name)

            role = classifier.classify(
                lib_id, connected_net_names=net_names,
                net_classifications=net_classifications,
            )
            fp_data.append((ref, role, x, y, net_names))

        # For each decoupling cap, find nearest IC on shared power/ground net
        for ref, role, cx, cy, cap_nets in fp_data:
            if role != ComponentRole.DECOUPLING_CAP:
                continue

            # Find power/ground nets this cap is on
            power_nets = {
                n for n in cap_nets
                if net_classifications.get(n) in (
                    NetClassification.POWER, NetClassification.GROUND
                )
            }

            if not power_nets:
                continue

            # Find nearest IC sharing a power/ground net
            best_dist = float("inf")
            best_ic_ref = ""

            for ic_ref, ic_role, ix, iy, ic_nets in fp_data:
                if ic_role not in (ComponentRole.IC, ComponentRole.POWER_REGULATOR):
                    continue
                shared_power = power_nets & set(ic_nets)
                if not shared_power:
                    continue
                dist = abs(cx - ix) + abs(cy - iy)  # Manhattan distance
                if dist < best_dist:
                    best_dist = dist
                    best_ic_ref = ic_ref

            if best_ic_ref:
                if best_dist > _DECOUPLING_MAX_DISTANCE_MM:
                    warnings.append(
                        f"Decoupling cap {ref} is {best_dist:.1f}mm from "
                        f"IC {best_ic_ref} (recommended < {_DECOUPLING_MAX_DISTANCE_MM}mm)"
                    )
            else:
                warnings.append(
                    f"Decoupling cap {ref} has no associated IC on shared power net"
                )

        return blockers, warnings

    # -----------------------------------------------------------------------
    # Sub-check 5: Thermal spacing
    # -----------------------------------------------------------------------

    def _check_thermal_spacing(
        self,
        pcb_ir: Any,
        constraints: Any,
        net_classifications: dict[str, NetClassification],
    ) -> tuple[list[str], list[str]]:
        """Check thermal components have adequate clearance."""
        blockers: list[str] = []
        warnings: list[str] = []

        classifier = ComponentTypeClassifier()
        clearance_mm = _THERMAL_DEFAULT_CLEARANCE_MM

        # Collect thermal components and all components
        thermal: list[tuple[str, float, float]] = []
        all_fps: list[tuple[str, float, float]] = []

        for fp in pcb_ir.footprints:
            ref = fp.properties.get("Reference", "?")
            lib_id = (
                getattr(fp, "lib_id", None)
                or getattr(fp, "libId", "")
            )
            try:
                x, y, _ = self._footprint_position(pcb_ir, ref)
            except (KeyError, ValueError):
                continue

            net_names: list[str] = []
            for pad in fp.pads:
                if pcb_ir._is_native:
                    net_name = pad.net_name
                else:
                    net_name = pad.net.name if pad.net is not None else ""
                if net_name and net_name not in net_names:
                    net_names.append(net_name)

            role = classifier.classify(
                lib_id, connected_net_names=net_names,
                net_classifications=net_classifications,
            )
            all_fps.append((ref, x, y))

            if ComponentTypeClassifier.is_thermal(role):
                thermal.append((ref, x, y))

        # Check thermal-to-other spacing
        for t_ref, tx, ty in thermal:
            for ref, x, y in all_fps:
                if ref == t_ref:
                    continue
                dist = math.hypot(tx - x, ty - y)
                if dist < clearance_mm:
                    # Escalate to blocker if two thermal components are adjacent
                    is_other_thermal = any(
                        r == ref for r, _, _ in thermal
                    )
                    msg = (
                        f"Thermal component {t_ref} is within {dist:.1f}mm "
                        f"of {ref} (recommended > {clearance_mm}mm)"
                    )
                    if is_other_thermal:
                        blockers.append(msg)
                    else:
                        warnings.append(msg)

        return blockers, warnings

    # -----------------------------------------------------------------------
    # Sub-check 6: Routability heuristics
    # -----------------------------------------------------------------------

    def _check_routability(
        self, pcb_ir: Any, constraints: Any
    ) -> tuple[list[str], list[str]]:
        """Check density, ratsnest estimate, and blocked channels."""
        blockers: list[str] = []
        warnings: list[str] = []

        board_bounds = pcb_ir.get_board_bounds()
        if board_bounds is None:
            return blockers, warnings

        bx_min, by_min, bx_max, by_max = board_bounds
        board_area = (bx_max - bx_min) * (by_max - by_min)
        if board_area <= 0:
            return blockers, warnings

        # Collect footprint bounding boxes
        fp_boxes: list[tuple[str, tuple[float, float, float, float]]] = []
        for fp in pcb_ir.footprints:
            ref = fp.properties.get("Reference", "?")
            try:
                bounds = self._footprint_bounds(pcb_ir, ref)
            except (KeyError, ValueError):
                continue
            fp_boxes.append((ref, bounds))

        # 1. Density score
        total_fp_area = sum(
            (x2 - x1) * (y2 - y1)
            for _, (x1, y1, x2, y2) in fp_boxes
        )
        density = total_fp_area / board_area
        if density > _DENSITY_WARNING_THRESHOLD:
            warnings.append(
                f"Component density is {density:.0%} "
                f"(recommended < {_DENSITY_WARNING_THRESHOLD:.0%})"
            )

        # 2. Blocked channel detection
        for i in range(len(fp_boxes)):
            ref1, (x1_min, y1_min, x1_max, y1_max) = fp_boxes[i]
            for j in range(i + 1, len(fp_boxes)):
                ref2, (x2_min, y2_min, x2_max, y2_max) = fp_boxes[j]

                # Compute gap between bounding boxes
                gap_x = max(x1_min, x2_min) - min(x1_max, x2_max)
                gap_y = max(y1_min, y2_min) - min(y1_max, y2_max)

                # Bounding boxes overlap if both gap_x and gap_y are negative
                if gap_x < 0 and gap_y < 0:
                    continue  # Already caught by courtyard check

                # Gap exists in at least one axis
                min_gap = min(gap_x, gap_y)
                # Only check if boxes are close in both axes (potential channel)
                if min_gap < _BLOCKED_CHANNEL_MIN_MM:
                    max_gap = max(gap_x, gap_y)
                    if max_gap > 0:  # There IS a channel, but it's narrow
                        warnings.append(
                            f"Blocked channel between {ref1} and {ref2} "
                            f"({max(gap_x, gap_y):.1f}mm gap)"
                        )

        return blockers, warnings

    # -----------------------------------------------------------------------
    # Analog/digital grouping check
    # -----------------------------------------------------------------------

    def _check_analog_digital_grouping(
        self,
        pcb_ir: Any,
        net_classifications: dict[str, NetClassification],
    ) -> list[str]:
        """Warn when analog and digital sections overlap spatially."""
        warnings: list[str] = []

        if not net_classifications:
            return warnings

        analog_nets = {
            n for n, c in net_classifications.items()
            if c == NetClassification.ANALOG
        }
        digital_nets = {
            n for n, c in net_classifications.items()
            if c == NetClassification.DIGITAL
        }

        if not analog_nets or not digital_nets:
            return warnings

        # Collect component positions grouped by analog/digital
        analog_positions: list[tuple[float, float]] = []
        digital_positions: list[tuple[float, float]] = []

        for fp in pcb_ir.footprints:
            ref = fp.properties.get("Reference", "?")
            try:
                x, y, _ = self._footprint_position(pcb_ir, ref)
            except (KeyError, ValueError):
                continue

            fp_nets: set[str] = set()
            for pad in fp.pads:
                if pcb_ir._is_native:
                    net_name = pad.net_name
                else:
                    net_name = pad.net.name if pad.net is not None else ""
                if net_name:
                    fp_nets.add(net_name)

            if fp_nets & analog_nets:
                analog_positions.append((x, y))
            if fp_nets & digital_nets:
                digital_positions.append((x, y))

        if not analog_positions or not digital_positions:
            return warnings

        # Compute centroids
        a_cx = sum(p[0] for p in analog_positions) / len(analog_positions)
        a_cy = sum(p[1] for p in analog_positions) / len(analog_positions)
        d_cx = sum(p[0] for p in digital_positions) / len(digital_positions)
        d_cy = sum(p[1] for p in digital_positions) / len(digital_positions)

        dist = math.hypot(a_cx - d_cx, a_cy - d_cy)
        if dist < _ANALOG_DIGITAL_OVERLAP_MM:
            warnings.append(
                f"Analog and digital sections overlap "
                f"(centroid distance: {dist:.1f}mm)"
            )

        return warnings

    # -----------------------------------------------------------------------
    # PcbIR helper methods (thin wrappers)
    # -----------------------------------------------------------------------

    @staticmethod
    def _footprint_position(
        pcb_ir: Any, ref: str
    ) -> tuple[float, float, float]:
        """Get (x, y, rotation) for a footprint by reference."""
        fp = pcb_ir.get_footprint_by_ref(ref)
        if fp is None:
            raise KeyError(f"Footprint '{ref}' not found")
        return pcb_ir._unpack_position(fp.position)

    @staticmethod
    def _footprint_bounds(
        pcb_ir: Any, ref: str
    ) -> tuple[float, float, float, float]:
        """Get bounding box (min_x, min_y, max_x, max_y) for a footprint.

        Computed from footprint position + pad positions.
        """
        fp = pcb_ir.get_footprint_by_ref(ref)
        if fp is None:
            raise KeyError(f"Footprint '{ref}' not found")

        fp_x, fp_y, fp_angle = pcb_ir._unpack_position(fp.position)

        pad_xs: list[float] = [fp_x]
        pad_ys: list[float] = [fp_y]

        for pad in fp.pads:
            pad_pos = pad.position
            if hasattr(pad_pos, "X"):
                local_x, local_y = pad_pos.X, pad_pos.Y
            elif hasattr(pad_pos, "__len__") and len(pad_pos) >= 2:
                local_x = pad_pos[0]
                local_y = pad_pos[1]
            else:
                continue

            if fp_angle != 0.0:
                rad = math.radians(fp_angle)
                cos_a = math.cos(rad)
                sin_a = math.sin(rad)
                px = fp_x + local_x * cos_a - local_y * sin_a
                py = fp_y + local_x * sin_a + local_y * cos_a
            else:
                px = fp_x + local_x
                py = fp_y + local_y

            pad_xs.append(px)
            pad_ys.append(py)

        return (min(pad_xs), min(pad_ys), max(pad_xs), max(pad_ys))


# ---------------------------------------------------------------------------
# Module-level gate registration
# ---------------------------------------------------------------------------

_gate = PlacementReadinessGate()

register_gate(
    GateDefinition(
        name="placement_readiness",
        from_stage=DesignStage.PLACEMENT,
        to_stage=DesignStage.ROUTING,
        check_fn_name="placement_readiness_gate",
    ),
    check_fn=_gate.run,
)
