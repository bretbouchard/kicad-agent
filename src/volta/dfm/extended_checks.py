"""Extended DFM checks for comprehensive manufacturability assessment.

Expands the DFM engine from 5 to 50+ manufacturing checks covering:
- Acid trap detection
- Copper pour spacing
- Via-in-pad detection
- Solder paste coverage
- Silkscreen clearance
- Board edge clearance
- Via tenting
- Impedance control hints
- Layer stackup verification
- Minimum feature size
- Trace angle validation
- Courtyard overlap
- Pin 1 marker presence
- Via stub detection
- Power plane void area
- Fiducial markers
- Component placement
- Minimum spacing
- Via pad size
- Teardrop presence
- Blind via validation
- Board dimensions
- Castellated holes
- NPTH drill sizes
- Slot dimensions
- Via count
- Solder mask openings
- Trace length
- Pad solder mask clearance
- Via annular ring
- Hole-to-hole spacing
- Pad-to-pad clearance
- Zone fill status
- Copper pour minimum width
"""
from __future__ import annotations

import logging
import math
from typing import Any

from volta.dfm.checker import DfmCheck, DfmFinding, DfmSeverity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POWER_NET_PATTERNS = {"VCC", "VDD", "GND", "VSS", "+3V3", "+5V", "+12V", "-12V",
                       "+3.3V", "+5V", "+1V8", "+1V2", "+1V0"}

_IC_PREFIXES = ("U", "IC", "M", "DDR", "QFP")

_PASSIVE_PREFIXES = ("R", "C", "L", "D", "FB", "RN")

_STANDARD_ANGLES = {0, 45, 90, 135, 180, 225, 270, 315}

_TRACE_TYPES = {"trace", "track", "segment", "wire"}

_VIA_TYPES = {"via", "blind_via", "buried_via"}

_DRILL_TYPES = {"drill", "via_drill", "npth_drill"}

_PAD_TYPES = {"pad", "smd_pad", "tht_pad"}

_MASK_LAYERS = {"F.Mask", "B.Mask"}

_SILKSCREEN_LAYERS = {"F.SilkS", "B.SilkS"}

_EDGE_LAYERS = {"Edge.Cuts"}

_COURTYARD_LAYERS = {"F.CrtYd", "B.CrtYd"}

# Minimum feature sizes in mm (conservative defaults)
_MIN_TEXT_HEIGHT_MM = 0.8
_MIN_TEXT_STROKE_MM = 0.12
_MIN_SLOT_WIDTH_MM = 0.5
_MIN_NPTH_DRILL_MM = 0.4
_MIN_MASK_OPENING_MM = 0.08
_MIN_COPPER_POUR_WIDTH_MM = 0.127
_MIN_HOLE_SPACING_MM = 0.5
_MAX_VIA_STUB_MM = 1.0
_MAX_POWER_VOID_AREA_MM2 = 100.0
_MAX_VIA_COUNT = 500
_MAX_TRACE_LENGTH_INFO_MM = 500.0
_MIN_EDGE_CLEARANCE_MM = 0.5
_MIN_SILKSCREEN_CLEARANCE_MM = 0.15
_MIN_SOLDER_PASTE_COVERAGE = 0.7


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_primitives(spatial_model: Any) -> list[Any]:
    """Extract primitives list from spatial model."""
    if hasattr(spatial_model, "all_primitives"):
        return spatial_model.all_primitives
    return []


def _is_power_net(net_name: str) -> bool:
    """Check if net name indicates a power net."""
    upper = net_name.upper()
    return upper in _POWER_NET_PATTERNS or any(
        upper.startswith(p) for p in ("VCC", "VDD", "GND", "VSS", "+")
    )


def _is_ic_ref(ref: str) -> bool:
    """Check if reference indicates an IC component."""
    for prefix in _IC_PREFIXES:
        if ref.upper().startswith(prefix):
            return True
    return False


def _is_passive_ref(ref: str) -> bool:
    """Check if reference indicates a passive component."""
    for prefix in _PASSIVE_PREFIXES:
        if ref.upper().startswith(prefix):
            return True
    return False


def _geom_or_none(primitive: Any) -> Any:
    """Get shapely geometry from primitive, returning None if unavailable."""
    if hasattr(primitive, "to_shapely"):
        try:
            return primitive.to_shapely()
        except Exception:
            return None
    return None


def _get_ref(primitive: Any) -> str:
    """Get reference string from primitive, returning entity_id as fallback."""
    ref = getattr(primitive, "reference", "")
    return ref if isinstance(ref, str) else getattr(primitive, "entity_id", "")


def _get_float(primitive: Any, attr: str, default: float | None = None) -> float | None:
    """Get a float attribute from primitive, returning default if not a real float."""
    val = getattr(primitive, attr, default)
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    return default


def _feature_size(primitive: Any) -> float:
    """Compute minimum feature size from bounding box."""
    x1 = getattr(primitive, "x1", 0)
    y1 = getattr(primitive, "y1", 0)
    x2 = getattr(primitive, "x2", 0)
    y2 = getattr(primitive, "y2", 0)
    return min(abs(x2 - x1), abs(y2 - y1))


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------


class AcidTrapCheck(DfmCheck):
    """Detect acute angles between trace segments that trap etchant.

    Acid traps occur when two trace segments meet at an acute angle (< 90 degrees),
    creating a pocket where etchant can accumulate during PCB fabrication,
    potentially undercutting the copper.
    """

    name = "ACID_TRAP_01"
    description = "Detect acute angles between traces that can trap etchant"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        # Collect trace segments
        traces = [p for p in primitives if getattr(p, "entity_type", "") in _TRACE_TYPES]
        if len(traces) < 2:
            return findings

        # Find pairs of traces that share an endpoint
        for i, tr_a in enumerate(traces):
            pts_a = getattr(tr_a, "points", [])
            if len(pts_a) < 2:
                continue

            for tr_b in traces[i + 1:]:
                pts_b = getattr(tr_b, "points", [])
                if len(pts_b) < 2:
                    continue

                # Check if traces share an endpoint
                shared_endpoints = []
                for pa in [pts_a[0], pts_a[-1]]:
                    for pb in [pts_b[0], pts_b[-1]]:
                        dx = abs(pa[0] - pb[0])
                        dy = abs(pa[1] - pb[1])
                        if dx < 0.01 and dy < 0.01:
                            shared_endpoints.append((pa, pb))
                            break

                if not shared_endpoints:
                    continue

                # Compute angle between the two traces at shared endpoint
                for pa, pb in shared_endpoints:
                    # Get direction vectors pointing INTO the shared point.
                    # We want the angle between the two incoming segments.
                    idx_a = 0 if pa == pts_a[0] else len(pts_a) - 1
                    idx_b = 0 if pb == pts_b[0] else len(pts_b) - 1

                    # The OTHER endpoint of each trace (the non-shared one)
                    va_idx = len(pts_a) - 1 if idx_a == 0 else 0
                    vb_idx = len(pts_b) - 1 if idx_b == 0 else 0

                    va = pts_a[va_idx]
                    vb = pts_b[vb_idx]

                    # Vectors from non-shared toward shared point
                    dx_a = pa[0] - va[0]
                    dy_a = pa[1] - va[1]
                    # Vector for B: from shared point TOWARD the other endpoint
                    dx_b = vb[0] - pb[0]
                    dy_b = vb[1] - pb[1]

                    mag_a = math.sqrt(dx_a * dx_a + dy_a * dy_a)
                    mag_b = math.sqrt(dx_b * dx_b + dy_b * dy_b)

                    if mag_a < 1e-9 or mag_b < 1e-9:
                        continue

                    cos_angle = (dx_a * dx_b + dy_a * dy_b) / (mag_a * mag_b)
                    cos_angle = max(-1.0, min(1.0, cos_angle))
                    angle_deg = math.degrees(math.acos(cos_angle))

                    if angle_deg < 90:
                        eid_a = getattr(tr_a, "entity_id", "")
                        eid_b = getattr(tr_b, "entity_id", "")
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Acid trap: traces {eid_a} and {eid_b} meet at "
                                f"{angle_deg:.1f} degrees (minimum 90)"
                            ),
                            severity=DfmSeverity.WARNING,
                            location=f"{eid_a}, {eid_b}",
                            suggestion=(
                                "Add a 45-degree chamfer or use rounded corners to "
                                "eliminate the acute angle"
                            ),
                            affected_entities=(eid_a, eid_b),
                            details={"angle_deg": round(angle_deg, 2)},
                        ))

        return findings


class CopperPourSpacingCheck(DfmCheck):
    """Validate spacing between copper pour zones and other copper features.

    Checks that copper zones maintain minimum clearance from pads and traces
    on different nets. Zones on the same net as the feature are exempt.
    """

    name = "COPPER_POUR_01"
    description = "Validate copper pour spacing to pads and traces"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_clearance = profile.min_clearance_mm
        primitives = _get_primitives(spatial_model)

        zones = [p for p in primitives if getattr(p, "entity_type", "") == "zone"]
        features = [p for p in primitives if getattr(p, "entity_type", "")
                     in {"pad", "trace", "track", "segment", "wire", "via"}]

        if not zones or not features:
            return findings

        geom_cache: dict[str, Any] = {}

        def _g(p: Any) -> Any:
            eid = getattr(p, "entity_id", id(p))
            if eid not in geom_cache:
                geom_cache[eid] = _geom_or_none(p)
            return geom_cache[eid]

        for zone in zones:
            zone_geom = _g(zone)
            if zone_geom is None:
                continue

            zone_net = getattr(zone, "net", "")
            zone_eid = getattr(zone, "entity_id", "")

            for feat in features:
                feat_geom = _g(feat)
                if feat_geom is None:
                    continue

                feat_net = getattr(feat, "net", "")
                if feat_net == zone_net:
                    continue

                try:
                    distance = zone_geom.distance(feat_geom)
                except Exception:
                    continue

                if distance < min_clearance:
                    feat_eid = getattr(feat, "entity_id", "")
                    feat_ref = _get_ref(feat)
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Copper pour zone {zone_eid} too close to "
                            f"{feat_ref} ({distance:.3f}mm < {min_clearance}mm)"
                        ),
                        severity=DfmSeverity.WARNING,
                        location=feat_ref,
                        suggestion=(
                            f"Increase clearance between zone and feature "
                            f"to at least {min_clearance}mm"
                        ),
                        affected_entities=(zone_eid, feat_eid),
                        details={
                            "distance_mm": round(distance, 4),
                            "minimum_mm": min_clearance,
                        },
                    ))

        return findings


class ViaInPadCheck(DfmCheck):
    """Detect vias placed inside pads (requires plugged or tented vias).

    Via-in-pad can cause solder wicking during assembly. When detected,
    the via should be plugged (filled and capped) or the design should
    use a via-in-pad footprint with appropriate solder paste adjustments.
    """

    name = "VIA_IN_PAD_01"
    description = "Detect vias placed inside pad geometry"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        pads = [p for p in primitives if getattr(p, "entity_type", "") in _PAD_TYPES]
        vias = [p for p in primitives if getattr(p, "entity_type", "") in _VIA_TYPES]

        if not pads or not vias:
            return findings

        for pad in pads:
            pad_geom = _geom_or_none(pad)
            if pad_geom is None:
                continue

            pad_eid = getattr(pad, "entity_id", "")
            pad_ref = _get_ref(pad)

            for via in vias:
                via_geom = _geom_or_none(via)
                if via_geom is None:
                    continue

                try:
                    if pad_geom.contains(via_geom) or pad_geom.intersects(via_geom):
                        via_eid = getattr(via, "entity_id", "")
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Via {via_eid} is inside pad {pad_ref}. "
                                f"Use plugged/tented via or via-in-pad footprint."
                            ),
                            severity=DfmSeverity.WARNING,
                            location=f"{pad_ref}, {via_eid}",
                            suggestion=(
                                "Plug the via (fill + cap) or use a dedicated "
                                "via-in-pad footprint with adjusted paste"
                            ),
                            affected_entities=(pad_eid, via_eid),
                        ))
                except Exception:
                    continue

        return findings


class SolderPasteCoverageCheck(DfmCheck):
    """Validate solder paste coverage on SMD pads.

    Checks that solder paste openings provide adequate coverage of the pad area.
    Insufficient coverage can cause weak solder joints.
    """

    name = "SOLDER_PASTE_01"
    description = "Validate solder paste coverage on SMD pads"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        pads = [p for p in primitives if getattr(p, "entity_type", "") in _PAD_TYPES
                and getattr(p, "layer", "") not in ("B.Cu",)]
        pastes = [p for p in primitives if getattr(p, "entity_type", "") == "solder_paste"]

        if not pads:
            return findings

        if not pastes:
            # No paste data is normal for THT or bare boards -- INFO only
            smd_pads = [p for p in pads if getattr(p, "layer", "").startswith("F.")]
            if smd_pads:
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"No solder paste data found for {len(smd_pads)} SMD pads. "
                        f"Verify paste layer is populated."
                    ),
                    severity=DfmSeverity.INFO,
                    location="(all SMD pads)",
                    suggestion="Check that solder paste layer is properly defined",
                    affected_entities=(),
                ))
            return findings

        geom_cache: dict[str, Any] = {}

        def _g(p: Any) -> Any:
            eid = getattr(p, "entity_id", id(p))
            if eid not in geom_cache:
                geom_cache[eid] = _geom_or_none(p)
            return geom_cache[eid]

        for pad in pads:
            pad_geom = _g(pad)
            if pad_geom is None:
                continue

            pad_area = pad_geom.area
            if pad_area <= 0:
                continue

            pad_eid = getattr(pad, "entity_id", "")
            pad_ref = _get_ref(pad)
            pad_layer = getattr(pad, "layer", "")

            # Find matching paste (same layer prefix)
            prefix = "F" if pad_layer.startswith("F") else "B"
            paste_layer = f"{prefix}.Paste"

            best_paste_area = 0.0
            for paste in pastes:
                paste_layer_p = getattr(paste, "layer", "")
                if paste_layer_p != paste_layer:
                    continue
                paste_geom = _g(paste)
                if paste_geom is None:
                    continue
                try:
                    intersection = pad_geom.intersection(paste_geom)
                    best_paste_area = max(best_paste_area, intersection.area)
                except Exception:
                    continue

            if best_paste_area > 0:
                coverage = best_paste_area / pad_area
                if coverage < _MIN_SOLDER_PASTE_COVERAGE:
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Solder paste coverage {coverage:.0%} below "
                            f"{_MIN_SOLDER_PASTE_COVERAGE:.0%} for pad {pad_ref}"
                        ),
                        severity=DfmSeverity.WARNING,
                        location=pad_ref,
                        suggestion=(
                            f"Increase solder paste opening to achieve "
                            f"{_MIN_SOLDER_PASTE_COVERAGE:.0%}+ coverage"
                        ),
                        affected_entities=(pad_eid,),
                        details={
                            "coverage": round(coverage, 4),
                            "pad_area_mm2": round(pad_area, 4),
                        },
                    ))

        return findings


class SilkscreenClearanceCheck(DfmCheck):
    """Validate silkscreen clearance from pads and other copper features.

    Silkscreen ink overlapping pads can cause soldering issues.
    """

    name = "SILKSCREEN_01"
    description = "Validate silkscreen clearance from copper features"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        silks = [p for p in primitives
                 if getattr(p, "entity_type", "") in {"silkscreen", "text"}
                 and getattr(p, "layer", "") in _SILKSCREEN_LAYERS]

        features = [p for p in primitives
                    if getattr(p, "entity_type", "") in _PAD_TYPES
                    and getattr(p, "layer", "") not in _SILKSCREEN_LAYERS]

        if not silks or not features:
            return findings

        geom_cache: dict[str, Any] = {}

        def _g(p: Any) -> Any:
            eid = getattr(p, "entity_id", id(p))
            if eid not in geom_cache:
                geom_cache[eid] = _geom_or_none(p)
            return geom_cache[eid]

        for silk in silks:
            silk_geom = _g(silk)
            if silk_geom is None:
                continue

            silk_eid = getattr(silk, "entity_id", "")

            for feat in features:
                feat_geom = _g(feat)
                if feat_geom is None:
                    continue

                try:
                    if silk_geom.intersects(feat_geom):
                        feat_eid = getattr(feat, "entity_id", "")
                        feat_ref = _get_ref(feat)
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Silkscreen {silk_eid} overlaps pad {feat_ref}. "
                                f"Move silkscreen away from copper features."
                            ),
                            severity=DfmSeverity.WARNING,
                            location=f"{silk_eid}, {feat_ref}",
                            suggestion=(
                                "Move silkscreen text/graphics away from pads "
                                f"(minimum {_MIN_SILKSCREEN_CLEARANCE_MM}mm clearance)"
                            ),
                            affected_entities=(silk_eid, feat_eid),
                        ))
                except Exception:
                    continue

        return findings


class BoardEdgeClearanceCheck(DfmCheck):
    """Validate feature clearance from board edge (Edge.Cuts).

    Features too close to the board edge can cause manufacturing issues
    and structural weakness.
    """

    name = "EDGE_CLEAR_01"
    description = "Validate feature clearance from board edge"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        edge_prims = [p for p in primitives if getattr(p, "layer", "") in _EDGE_LAYERS]
        features = [p for p in primitives
                    if getattr(p, "entity_type", "") in _PAD_TYPES
                    or getattr(p, "entity_type", "") in _TRACE_TYPES]

        if not edge_prims or not features:
            return findings

        edge_geoms = []
        for ep in edge_prims:
            eg = _geom_or_none(ep)
            if eg is not None:
                edge_geoms.append(eg)

        if not edge_geoms:
            return findings

        try:
            from shapely.ops import unary_union
            edge_union = unary_union(edge_geoms)
            # Buffer inward to create clearance zone
            edge_zone = edge_union.buffer(_MIN_EDGE_CLEARANCE_MM)
        except Exception:
            return findings

        for feat in features:
            feat_geom = _geom_or_none(feat)
            if feat_geom is None:
                continue

            try:
                if feat_geom.intersects(edge_zone):
                    feat_eid = getattr(feat, "entity_id", "")
                    feat_ref = _get_ref(feat)
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Feature {feat_ref} within {_MIN_EDGE_CLEARANCE_MM}mm "
                            f"of board edge"
                        ),
                        severity=DfmSeverity.WARNING,
                        location=feat_ref,
                        suggestion=(
                            f"Move feature at least {_MIN_EDGE_CLEARANCE_MM}mm "
                            f"away from board edge"
                        ),
                        affected_entities=(feat_eid,),
                    ))
            except Exception:
                continue

        return findings


class ViaTentingCheck(DfmCheck):
    """Check via tenting requirements (covered by solder mask).

    Untented vias expose copper and can cause solder wicking or shorting.
    """

    name = "VIA_TENT_01"
    description = "Check via tenting requirements"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        vias = [p for p in primitives if getattr(p, "entity_type", "") in _VIA_TYPES]

        for via in vias:
            tenting = getattr(via, "tenting", None)
            if tenting is True:
                continue

            # If tenting info is unavailable, emit INFO
            via_eid = getattr(via, "entity_id", "")
            if tenting is None:
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Via {via_eid} tenting status unknown. "
                        f"Verify tenting or plugging for exposed vias."
                    ),
                    severity=DfmSeverity.INFO,
                    location=via_eid,
                    suggestion="Confirm via is tented or plugged per design requirements",
                    affected_entities=(via_eid,),
                ))

        return findings


class ImpedanceControlCheck(DfmCheck):
    """Validate impedance-controlled trace constraints.

    Checks for traces on potentially impedance-critical nets (RF, differential pairs)
    that may need impedance control specification.
    """

    name = "IMPEDANCE_01"
    description = "Validate impedance-controlled trace constraints"

    _IMPEDANCE_HINT_PATTERNS = {"RF", "Differential", "DIFF", "SDA", "SCL",
                                 "USB", "HDMI", "LVDS", "PCI", "DDR", "CLK"}

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        traces = [p for p in primitives if getattr(p, "entity_type", "") in _TRACE_TYPES]

        for trace in traces:
            net = getattr(trace, "net", "")
            upper_net = net.upper()

            is_impedance_critical = any(
                pat in upper_net for pat in self._IMPEDANCE_HINT_PATTERNS
            )

            if not is_impedance_critical:
                continue

            impedance_controlled = getattr(trace, "impedance_controlled", None)
            if impedance_controlled is None:
                eid = getattr(trace, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Trace {eid} on impedance-critical net '{net}' "
                        f"has no impedance control specification"
                    ),
                    severity=DfmSeverity.INFO,
                    location=eid,
                    suggestion=(
                        "Specify impedance target (e.g., 50 ohm single-ended, "
                        "100 ohm differential) for this net"
                    ),
                    affected_entities=(eid,),
                    details={"net": net},
                ))

        return findings


class LayerStackupCheck(DfmCheck):
    """Validate board layer stackup against profile constraints.

    Checks that the board has the correct number of copper layers
    for the selected manufacturer profile.
    """

    name = "STACKUP_01"
    description = "Validate layer stackup against profile constraints"

    _COPPER_LAYERS = {
        "F.Cu", "B.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu",
        "In5.Cu", "In6.Cu", "In7.Cu", "In8.Cu", "In9.Cu", "In10.Cu",
        "In11.Cu", "In12.Cu", "In13.Cu", "In14.Cu", "In15.Cu", "In16.Cu",
        "In17.Cu", "In18.Cu", "In19.Cu", "In20.Cu", "In21.Cu", "In22.Cu",
        "In23.Cu", "In24.Cu", "In25.Cu", "In26.Cu", "In27.Cu", "In28.Cu",
        "In29.Cu", "In30.Cu",
    }

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        # Detect used copper layers
        used_layers: set[str] = set()
        for p in primitives:
            layer = getattr(p, "layer", "")
            if layer in self._COPPER_LAYERS:
                used_layers.add(layer)

        if not used_layers:
            return findings

        layer_count = len(used_layers)
        expected_layers = profile.extra.get("layer_count", 2)

        if layer_count < expected_layers:
            findings.append(DfmFinding(
                check_id=self.name,
                description=(
                    f"Board has {layer_count} copper layers but profile "
                    f"'{profile.name}' expects {expected_layers}. "
                    f"Missing inner layers may indicate a design error."
                ),
                severity=DfmSeverity.CRITICAL,
                location="(layer stackup)",
                suggestion=(
                    f"Add missing inner copper layers or switch to a "
                    f"{layer_count}-layer manufacturer profile"
                ),
                affected_entities=(),
                details={
                    "actual_layers": layer_count,
                    "expected_layers": expected_layers,
                    "used_layers": sorted(used_layers),
                },
            ))

        return findings


class MinFeatureSizeCheck(DfmCheck):
    """Validate minimum feature size per layer type.

    Checks pads, text, and other features against minimum manufacturable sizes.
    """

    name = "MIN_FEATURE_01"
    description = "Validate minimum feature size per layer"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_size = profile.min_trace_width_mm * 0.8  # Features can be slightly smaller than traces
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            etype = getattr(p, "entity_type", "")

            if etype in _PAD_TYPES:
                size = _feature_size(p)
                if size > 0 and size < min_size:
                    eid = getattr(p, "entity_id", "")
                    ref = _get_ref(p)
                    layer = getattr(p, "layer", "")
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Pad {ref} feature size {size:.3f}mm below "
                            f"minimum {min_size:.3f}mm on layer {layer}"
                        ),
                        severity=DfmSeverity.CRITICAL,
                        location=f"{ref} ({layer})",
                        suggestion=(
                            f"Increase pad size to at least {min_size:.3f}mm "
                            f"or verify manufacturer capability"
                        ),
                        affected_entities=(eid,),
                        details={
                            "feature_size_mm": round(size, 4),
                            "minimum_mm": round(min_size, 4),
                        },
                    ))

            elif etype == "text":
                height = getattr(p, "height", 0)
                if height > 0 and height < _MIN_TEXT_HEIGHT_MM:
                    eid = getattr(p, "entity_id", "")
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Text height {height:.3f}mm below minimum "
                            f"{_MIN_TEXT_HEIGHT_MM}mm for {eid}"
                        ),
                        severity=DfmSeverity.INFO,
                        location=eid,
                        suggestion=(
                            f"Increase text height to at least "
                            f"{_MIN_TEXT_HEIGHT_MM}mm for readability"
                        ),
                        affected_entities=(eid,),
                        details={"height_mm": round(height, 4)},
                    ))

                stroke = getattr(p, "width", 0)
                if stroke > 0 and stroke < _MIN_TEXT_STROKE_MM:
                    eid = getattr(p, "entity_id", "")
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Text stroke width {stroke:.3f}mm below minimum "
                            f"{_MIN_TEXT_STROKE_MM}mm for {eid}"
                        ),
                        severity=DfmSeverity.INFO,
                        location=eid,
                        suggestion="Increase text stroke width for manufacturability",
                        affected_entities=(eid,),
                        details={"stroke_mm": round(stroke, 4)},
                    ))

        return findings


class TraceAngleCheck(DfmCheck):
    """Validate trace segment angles for manufacturability.

    Traces should use 45-degree or 90-degree bends. Arbitrary angles
    can cause acid traps and manufacturing issues.
    """

    name = "TRACE_ANGLE_01"
    description = "Validate trace segment angles"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        traces = [p for p in primitives if getattr(p, "entity_type", "") in _TRACE_TYPES]

        for trace in traces:
            pts = getattr(trace, "points", [])
            if len(pts) < 3:
                continue

            for i in range(len(pts) - 2):
                p0, p1, p2 = pts[i], pts[i + 1], pts[i + 2]

                dx1 = p1[0] - p0[0]
                dy1 = p1[1] - p0[1]
                dx2 = p2[0] - p1[0]
                dy2 = p2[1] - p1[1]

                mag1 = math.sqrt(dx1 * dx1 + dy1 * dy1)
                mag2 = math.sqrt(dx2 * dx2 + dy2 * dy2)

                if mag1 < 1e-9 or mag2 < 1e-9:
                    continue

                cos_angle = (dx1 * dx2 + dy1 * dy2) / (mag1 * mag2)
                cos_angle = max(-1.0, min(1.0, cos_angle))
                angle_deg = math.degrees(math.acos(cos_angle))

                # Normalize to 0-180 range
                if angle_deg > 180:
                    angle_deg = 360 - angle_deg

                # Allow standard angles: 45, 90, 135, 180
                is_standard = any(abs(angle_deg - sa) < 5 for sa in _STANDARD_ANGLES)

                if not is_standard:
                    eid = getattr(trace, "entity_id", "")
                    layer = getattr(trace, "layer", "")
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Non-standard trace angle {angle_deg:.1f} degrees "
                            f"in {eid} on {layer}"
                        ),
                        severity=DfmSeverity.INFO,
                        location=f"{eid} ({layer})",
                        suggestion=(
                            "Use 45 or 90-degree trace bends for manufacturability"
                        ),
                        affected_entities=(eid,),
                        details={"angle_deg": round(angle_deg, 2)},
                    ))

        return findings


class CourtyardOverlapCheck(DfmCheck):
    """Detect courtyard overlap between components.

    IPC-7351 requires courtyards not to overlap between different components.
    """

    name = "COURTYARD_01"
    description = "Detect courtyard overlap between components"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        courtyards = [p for p in primitives
                      if getattr(p, "layer", "") in _COURTYARD_LAYERS]

        if len(courtyards) < 2:
            return findings

        geom_cache: dict[str, Any] = {}

        def _g(p: Any) -> Any:
            eid = getattr(p, "entity_id", id(p))
            if eid not in geom_cache:
                geom_cache[eid] = _geom_or_none(p)
            return geom_cache[eid]

        for i, cy_a in enumerate(courtyards):
            geom_a = _g(cy_a)
            if geom_a is None:
                continue

            ref_a = _get_ref(cy_a)
            eid_a = getattr(cy_a, "entity_id", "")

            for cy_b in courtyards[i + 1:]:
                geom_b = _g(cy_b)
                if geom_b is None:
                    continue

                try:
                    if geom_a.intersects(geom_b):
                        ref_b = _get_ref(cy_b)
                        eid_b = getattr(cy_b, "entity_id", "")
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Courtyard overlap between {ref_a} and {ref_b}. "
                                f"Per IPC-7351, courtyards must not overlap."
                            ),
                            severity=DfmSeverity.WARNING,
                            location=f"{ref_a}, {ref_b}",
                            suggestion="Move components apart or adjust courtyard sizes",
                            affected_entities=(eid_a, eid_b),
                        ))
                except Exception:
                    continue

        return findings


class Pin1MarkerCheck(DfmCheck):
    """Verify pin 1 markers are present on IC components.

    Pin 1 markers help identify correct component orientation during assembly.
    """

    name = "PIN1_MARKER_01"
    description = "Verify pin 1 markers on IC components"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        components = [p for p in primitives
                      if getattr(p, "entity_type", "") in {"footprint", "component"}]

        for comp in components:
            ref = getattr(comp, "reference", "")
            if not ref or not _is_ic_ref(ref):
                continue

            has_marker = getattr(comp, "has_pin1_marker", None)
            if has_marker is False or (has_marker is None and not _check_pin1_attr(comp)):
                eid = getattr(comp, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"IC component {ref} missing pin 1 marker. "
                        f"Assembly may orient component incorrectly."
                    ),
                    severity=DfmSeverity.WARNING,
                    location=ref,
                    suggestion="Add pin 1 marker (dot, notch, or triangle) to silkscreen",
                    affected_entities=(eid,),
                ))

        return findings


def _check_pin1_attr(comp: Any) -> bool:
    """Check various pin 1 marker attribute patterns."""
    marker = getattr(comp, "pin1_marker", None)
    if marker:
        return True
    # Check reference text on silkscreen
    ref_text = getattr(comp, "reference_text", "")
    if ref_text and "pin" in str(ref_text).lower():
        return True
    return False


class ViaStubCheck(DfmCheck):
    """Detect via stubs in high-speed designs.

    Via stubs act as resonant stubs at high frequencies and can cause signal
    integrity issues. Back-drilling or blind vias eliminate stubs.
    """

    name = "VIA_STUB_01"
    description = "Detect via stubs in high-speed designs"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        vias = [p for p in primitives if getattr(p, "entity_type", "") in _VIA_TYPES]

        for via in vias:
            stub = _get_float(via, "stub_length_mm")
            if stub is None:
                continue

            if stub > _MAX_VIA_STUB_MM:
                via_eid = getattr(via, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Via {via_eid} has stub length {stub:.2f}mm "
                        f"(maximum {_MAX_VIA_STUB_MM}mm). Consider back-drilling."
                    ),
                    severity=DfmSeverity.WARNING,
                    location=via_eid,
                    suggestion="Back-drill the via or use a blind via to eliminate stub",
                    affected_entities=(via_eid,),
                    details={
                        "stub_length_mm": round(stub, 4),
                        "maximum_mm": _MAX_VIA_STUB_MM,
                    },
                ))

        return findings


class PowerPlaneVoidCheck(DfmCheck):
    """Detect excessive void areas in power planes.

    Large voids in power planes reduce current carrying capacity and
    can cause voltage drop issues.
    """

    name = "POWER_VOID_01"
    description = "Detect excessive void areas in power planes"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            etype = getattr(p, "entity_type", "")
            if etype != "zone":
                continue

            net = getattr(p, "net", "")
            if not _is_power_net(net):
                continue

            void_area = _get_float(p, "void_area_mm2")
            if void_area is not None and void_area > _MAX_POWER_VOID_AREA_MM2:
                eid = getattr(p, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Power zone {eid} (net: {net}) has void area "
                        f"{void_area:.1f}mm^2 (threshold {_MAX_POWER_VOID_AREA_MM2}mm^2). "
                        f"May cause voltage drop."
                    ),
                    severity=DfmSeverity.WARNING,
                    location=f"{eid} ({net})",
                    suggestion=(
                        "Route traces around power zones instead of through them, "
                        "or add additional power plane vias"
                    ),
                    affected_entities=(eid,),
                    details={
                        "void_area_mm2": round(void_area, 2),
                        "net": net,
                    },
                ))

        return findings


class FiducialMarkerCheck(DfmCheck):
    """Check for adequate fiducial marker presence.

    Fiducials are needed for machine vision alignment during assembly.
    """

    name = "FIDUCIAL_01"
    description = "Check for adequate fiducial markers"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        fiducial_count = 0
        for p in primitives:
            etype = getattr(p, "entity_type", "")
            ref = getattr(p, "reference", "")
            if etype in {"fiducial", "fiducial_mark"}:
                fiducial_count += 1
            elif isinstance(ref, str) and ("FIDUCIAL" in ref.upper() or ref.upper().startswith("FID")):
                fiducial_count += 1

        if fiducial_count < 3:
            findings.append(DfmFinding(
                check_id=self.name,
                description=(
                    f"Only {fiducial_count} fiducial(s) found (minimum 3 recommended). "
                    f"Fiducials are needed for machine vision alignment."
                ),
                severity=DfmSeverity.INFO if fiducial_count > 0 else DfmSeverity.WARNING,
                location="(board)",
                suggestion="Add 3 fiducial markers (one corner + two others for rotation)",
                affected_entities=(),
                details={"fiducial_count": fiducial_count},
            ))

        return findings


class ComponentPlacementCheck(DfmCheck):
    """Validate component placement constraints.

    Components should be inside the board outline with adequate clearance
    from edges and connectors.
    """

    name = "COMP_PLACE_01"
    description = "Validate component placement constraints"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        edge_prims = [p for p in primitives if getattr(p, "layer", "") in _EDGE_LAYERS]
        components = [p for p in primitives
                      if getattr(p, "entity_type", "") in {"footprint", "component"}]

        if not edge_prims or not components:
            return findings

        # Build edge geometry
        edge_geoms = []
        for ep in edge_prims:
            eg = _geom_or_none(ep)
            if eg is not None:
                edge_geoms.append(eg)

        if not edge_geoms:
            return findings

        try:
            from shapely.geometry import Polygon as ShapelyPolygon
            from shapely.ops import unary_union, polygonize

            board_outline = unary_union(edge_geoms)

            # Try to polygonize line outlines (closed loops)
            if board_outline.geom_type in ("LineString", "MultiLineString"):
                polygons = list(polygonize([board_outline]))
                if polygons:
                    board_area = unary_union(polygons)
                else:
                    # Fallback: convex hull of all edge coordinates
                    board_area = board_outline.convex_hull
            else:
                board_area = board_outline

            clearance_zone = board_area.buffer(-_MIN_EDGE_CLEARANCE_MM)
            if clearance_zone.is_empty:
                clearance_zone = board_area
        except Exception:
            return findings

        for comp in components:
            comp_geom = _geom_or_none(comp)
            if comp_geom is None:
                continue

            try:
                # Component centroid should be inside cleared area
                cx = (getattr(comp, "x1", 0) + getattr(comp, "x2", 0)) / 2.0
                cy = (getattr(comp, "y1", 0) + getattr(comp, "y2", 0)) / 2.0

                from shapely.geometry import Point
                center = Point(cx, cy)

                if not clearance_zone.contains(center) and not board_area.contains(center):
                    eid = getattr(comp, "entity_id", "")
                    ref = _get_ref(comp)
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Component {ref} is placed outside or too close to "
                            f"board edge"
                        ),
                        severity=DfmSeverity.CRITICAL,
                        location=ref,
                        suggestion=f"Move {ref} inside board outline with {_MIN_EDGE_CLEARANCE_MM}mm clearance",
                        affected_entities=(eid,),
                    ))
            except Exception:
                continue

        return findings


class MinSpacingCheck(DfmCheck):
    """Validate minimum spacing between copper features on different nets.

    Same-net features are exempt from spacing checks.
    """

    name = "MIN_SPACE_01"
    description = "Validate minimum spacing between copper features"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_clearance = profile.min_clearance_mm
        primitives = _get_primitives(spatial_model)

        traces = [p for p in primitives if getattr(p, "entity_type", "") in _TRACE_TYPES]
        if len(traces) < 2:
            return findings

        geom_cache: dict[str, Any] = {}

        def _g(p: Any) -> Any:
            eid = getattr(p, "entity_id", id(p))
            if eid not in geom_cache:
                geom_cache[eid] = _geom_or_none(p)
            return geom_cache[eid]

        for i, tr_a in enumerate(traces):
            geom_a = _g(tr_a)
            if geom_a is None:
                continue

            net_a = getattr(tr_a, "net", "")
            eid_a = getattr(tr_a, "entity_id", "")
            layer_a = getattr(tr_a, "layer", "")

            for tr_b in traces[i + 1:]:
                net_b = getattr(tr_b, "net", "")

                # Same net or different layers: skip
                if net_a == net_b or net_a == "" or net_b == "":
                    continue

                layer_b = getattr(tr_b, "layer", "")
                if layer_a != layer_b:
                    continue

                geom_b = _g(tr_b)
                if geom_b is None:
                    continue

                try:
                    distance = geom_a.distance(geom_b)
                    if distance < min_clearance:
                        eid_b = getattr(tr_b, "entity_id", "")
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Traces {eid_a} and {eid_b} on layer {layer_a} "
                                f"have spacing {distance:.3f}mm (minimum {min_clearance}mm)"
                            ),
                            severity=DfmSeverity.WARNING,
                            location=f"{eid_a}, {eid_b} ({layer_a})",
                            suggestion=f"Increase spacing to at least {min_clearance}mm",
                            affected_entities=(eid_a, eid_b),
                            details={
                                "distance_mm": round(distance, 4),
                                "minimum_mm": min_clearance,
                                "layer": layer_a,
                            },
                        ))
                except Exception:
                    continue

        return findings


class MinViaPadCheck(DfmCheck):
    """Validate minimum via pad diameter.

    Via pads must be large enough for reliable manufacturing.
    """

    name = "MIN_VIA_PAD_01"
    description = "Validate minimum via pad diameter"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_dia = profile.min_via_diameter_mm
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") not in _VIA_TYPES:
                continue

            pad_dia = _get_float(p, "pad_diameter")
            if pad_dia is None:
                continue

            if pad_dia < min_dia:
                eid = getattr(p, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Via pad diameter {pad_dia:.3f}mm below minimum "
                        f"{min_dia:.3f}mm for {eid}"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=eid,
                    suggestion=f"Increase via pad diameter to at least {min_dia:.3f}mm",
                    affected_entities=(eid,),
                    details={
                        "pad_diameter_mm": round(pad_dia, 4),
                        "minimum_mm": min_dia,
                    },
                ))

        return findings


class TeardropCheck(DfmCheck):
    """Check for teardrop recommendations on via-pad transitions.

    Teardrops improve reliability at via-pad junctions by reducing
    stress concentration and improving current flow.
    """

    name = "TEARDROP_01"
    description = "Check teardrop presence on via-pad transitions"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        vias = [p for p in primitives if getattr(p, "entity_type", "") in _VIA_TYPES]

        for via in vias:
            has_teardrop = getattr(via, "has_teardrop", None)
            if has_teardrop is True:
                continue

            via_eid = getattr(via, "entity_id", "")

            if has_teardrop is False:
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Via {via_eid} has no teardrop. "
                        f"Teardrops improve reliability at via-pad junctions."
                    ),
                    severity=DfmSeverity.INFO,
                    location=via_eid,
                    suggestion="Add teardrops to via-pad transitions for improved reliability",
                    affected_entities=(via_eid,),
                ))

        return findings


class BlindViaCheck(DfmCheck):
    """Validate blind via usage against profile support.

    Blind vias require additional manufacturing steps and may not be
    supported by all manufacturers.
    """

    name = "BLIND_VIA_01"
    description = "Validate blind via usage against profile support"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        blind_vias = [p for p in primitives
                      if getattr(p, "entity_type", "") == "blind_via"]

        if not blind_vias:
            return findings

        if not profile.supports_blind_vias:
            for via in blind_vias:
                eid = getattr(via, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Blind via {eid} used but manufacturer '{profile.name}' "
                        f"does not support blind vias"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=eid,
                    suggestion=(
                        f"Switch to a manufacturer that supports blind vias "
                        f"(e.g., PCBWay) or replace with through-hole vias"
                    ),
                    affected_entities=(eid,),
                ))

        return findings


class BoardDimensionCheck(DfmCheck):
    """Validate board dimensions against profile maximum.

    Exceeding manufacturer maximum dimensions may require special pricing
    or panelization.
    """

    name = "BOARD_DIM_01"
    description = "Validate board dimensions against profile maximum"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        edge_prims = [p for p in primitives if getattr(p, "layer", "") in _EDGE_LAYERS]
        if not edge_prims:
            return findings

        edge_geoms = []
        for ep in edge_prims:
            eg = _geom_or_none(ep)
            if eg is not None:
                edge_geoms.append(eg)

        if not edge_geoms:
            return findings

        try:
            bounds = edge_geoms[0].bounds
            for eg in edge_geoms[1:]:
                b = eg.bounds
                bounds = (
                    min(bounds[0], b[0]),
                    min(bounds[1], b[1]),
                    max(bounds[2], b[2]),
                    max(bounds[3], b[3]),
                )

            width_mm = bounds[2] - bounds[0]
            height_mm = bounds[3] - bounds[1]
            max_dim = max(width_mm, height_mm)

            if max_dim > profile.max_board_dim_mm:
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Board dimension {max_dim:.1f}mm exceeds manufacturer "
                        f"maximum {profile.max_board_dim_mm:.1f}mm "
                        f"({width_mm:.1f} x {height_mm:.1f}mm)"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location="(board outline)",
                    suggestion=(
                        f"Reduce board size or split into panels under "
                        f"{profile.max_board_dim_mm:.1f}mm"
                    ),
                    affected_entities=(),
                    details={
                        "width_mm": round(width_mm, 2),
                        "height_mm": round(height_mm, 2),
                        "max_dim_mm": round(max_dim, 2),
                        "maximum_mm": profile.max_board_dim_mm,
                    },
                ))
        except Exception:
            pass

        return findings


class CastellatedHoleCheck(DfmCheck):
    """Validate castellated hole usage against profile support.

    Castellated holes are plated half-holes on the board edge used for
    board-to-board connectors.
    """

    name = "CASTELLATED_01"
    description = "Validate castellated hole usage against profile support"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        castellated = [p for p in primitives
                       if getattr(p, "entity_type", "") == "castellated_pad"]

        if not castellated:
            return findings

        if not profile.supports_castellated:
            for cp in castellated:
                eid = getattr(cp, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Castellated hole {eid} used but manufacturer "
                        f"'{profile.name}' does not support castellated holes"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=eid,
                    suggestion=(
                        "Switch to a manufacturer that supports castellated holes "
                        "(e.g., JLCPCB, PCBWay) or use edge connectors instead"
                    ),
                    affected_entities=(eid,),
                ))

        return findings


class NPTHDrillCheck(DfmCheck):
    """Validate non-plated through hole drill sizes.

    NPTH holes must be large enough for reliable manufacturing and
    component fit.
    """

    name = "NPTH_DRILL_01"
    description = "Validate non-plated through hole drill sizes"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") != "npth_drill":
                continue

            drill_dia = _get_float(p, "drill_diameter")
            if drill_dia is None:
                continue

            if drill_dia < _MIN_NPTH_DRILL_MM:
                eid = getattr(p, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"NPTH drill {eid} diameter {drill_dia:.3f}mm below "
                        f"minimum {_MIN_NPTH_DRILL_MM}mm"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=eid,
                    suggestion=f"Increase NPTH drill to at least {_MIN_NPTH_DRILL_MM}mm",
                    affected_entities=(eid,),
                    details={
                        "drill_diameter_mm": round(drill_dia, 4),
                        "minimum_mm": _MIN_NPTH_DRILL_MM,
                    },
                ))

        return findings


class SlotCheck(DfmCheck):
    """Validate slot dimensions.

    Slots must have minimum width for manufacturability.
    """

    name = "SLOT_01"
    description = "Validate slot dimensions"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") != "slot":
                continue

            size = _feature_size(p)
            if size > 0 and size < _MIN_SLOT_WIDTH_MM:
                eid = getattr(p, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Slot {eid} width {size:.3f}mm below minimum "
                        f"{_MIN_SLOT_WIDTH_MM}mm"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=eid,
                    suggestion=f"Increase slot width to at least {_MIN_SLOT_WIDTH_MM}mm",
                    affected_entities=(eid,),
                    details={
                        "width_mm": round(size, 4),
                        "minimum_mm": _MIN_SLOT_WIDTH_MM,
                    },
                ))

        return findings


class ViaCountCheck(DfmCheck):
    """Validate via density for manufacturing.

    Excessive via count can increase cost and reduce yield.
    """

    name = "VIA_COUNT_01"
    description = "Validate via density for manufacturing"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        via_count = sum(
            1 for p in primitives
            if getattr(p, "entity_type", "") in _VIA_TYPES
        )

        if via_count > _MAX_VIA_COUNT:
            findings.append(DfmFinding(
                check_id=self.name,
                description=(
                    f"Board has {via_count} vias (recommended maximum "
                    f"{_MAX_VIA_COUNT}). High via count increases cost."
                ),
                severity=DfmSeverity.INFO,
                location="(board)",
                suggestion=(
                    f"Review via usage and reduce if possible to stay under "
                    f"{_MAX_VIA_COUNT} vias"
                ),
                affected_entities=(),
                details={"via_count": via_count},
            ))

        return findings


class SolderMaskOpeningCheck(DfmCheck):
    """Validate solder mask openings for pads.

    Solder mask openings must be large enough to prevent mask bleeding
    onto pads.
    """

    name = "MASK_OPEN_01"
    description = "Validate solder mask opening dimensions"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") != "solder_mask_opening":
                continue

            size = _feature_size(p)
            if size > 0 and size < _MIN_MASK_OPENING_MM:
                eid = getattr(p, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Solder mask opening {eid} size {size:.3f}mm below "
                        f"minimum {_MIN_MASK_OPENING_MM}mm"
                    ),
                    severity=DfmSeverity.WARNING,
                    location=eid,
                    suggestion=(
                        f"Increase solder mask opening to at least "
                        f"{_MIN_MASK_OPENING_MM}mm"
                    ),
                    affected_entities=(eid,),
                    details={
                        "size_mm": round(size, 4),
                        "minimum_mm": _MIN_MASK_OPENING_MM,
                    },
                ))

        return findings


class TraceLengthCheck(DfmCheck):
    """Validate trace length for impedance and signal integrity.

    Very long traces may need impedance matching or signal conditioning.
    """

    name = "TRACE_LEN_01"
    description = "Validate trace length for signal integrity"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") not in _TRACE_TYPES:
                continue

            pts = getattr(p, "points", [])
            if len(pts) < 2:
                continue

            length = sum(
                math.sqrt((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2)
                for i in range(len(pts) - 1)
            )

            if length > _MAX_TRACE_LENGTH_INFO_MM:
                eid = getattr(p, "entity_id", "")
                net = getattr(p, "net", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Trace {eid} on net '{net}' is {length:.1f}mm long. "
                        f"Review for impedance matching and signal integrity."
                    ),
                    severity=DfmSeverity.INFO,
                    location=eid,
                    suggestion="Consider impedance matching for traces exceeding 500mm",
                    affected_entities=(eid,),
                    details={
                        "length_mm": round(length, 2),
                        "net": net,
                    },
                ))

        return findings


class PadSolderMaskClearanceCheck(DfmCheck):
    """Validate pad to solder mask clearance.

    Adequate clearance between pads and solder mask boundaries
    prevents solder bridge formation.
    """

    name = "PAD_MASK_CLEAR_01"
    description = "Validate pad to solder mask clearance"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        pads = [p for p in primitives if getattr(p, "entity_type", "") in _PAD_TYPES]
        mask_bounds = [p for p in primitives
                       if getattr(p, "entity_type", "") == "solder_mask_boundary"]

        if not pads or not mask_bounds:
            return findings

        geom_cache: dict[str, Any] = {}

        def _g(p: Any) -> Any:
            eid = getattr(p, "entity_id", id(p))
            if eid not in geom_cache:
                geom_cache[eid] = _geom_or_none(p)
            return geom_cache[eid]

        for pad in pads:
            pad_geom = _g(pad)
            if pad_geom is None:
                continue

            pad_eid = getattr(pad, "entity_id", "")
            pad_ref = _get_ref(pad)

            for mb in mask_bounds:
                mb_geom = _g(mb)
                if mb_geom is None:
                    continue

                try:
                    distance = pad_geom.distance(mb_geom)
                    if distance < profile.min_solder_mask_sliver_mm:
                        mb_eid = getattr(mb, "entity_id", "")
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Pad {pad_ref} too close to solder mask boundary "
                                f"({distance:.3f}mm < {profile.min_solder_mask_sliver_mm}mm)"
                            ),
                            severity=DfmSeverity.WARNING,
                            location=pad_ref,
                            suggestion=(
                                "Increase solder mask clearance around pad or "
                                "adjust pad size"
                            ),
                            affected_entities=(pad_eid, mb_eid),
                            details={
                                "distance_mm": round(distance, 4),
                                "minimum_mm": profile.min_solder_mask_sliver_mm,
                            },
                        ))
                except Exception:
                    continue

        return findings


class ViaAnnularCheck(DfmCheck):
    """Validate via annular ring dimensions.

    Via annular rings must meet minimum requirements for reliability.
    """

    name = "VIA_ANNULAR_01"
    description = "Validate via annular ring dimensions"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_annular = profile.min_annular_ring_mm
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") not in _VIA_TYPES:
                continue

            pad_dia = _get_float(p, "pad_diameter")
            drill_dia = _get_float(p, "drill_diameter")

            if pad_dia is None or drill_dia is None:
                continue

            annular = (pad_dia - drill_dia) / 2.0

            if annular < min_annular:
                eid = getattr(p, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Via {eid} annular ring {annular:.3f}mm below "
                        f"minimum {min_annular}mm"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=eid,
                    suggestion=(
                        f"Increase via pad size or reduce drill to achieve "
                        f"minimum {min_annular}mm annular ring"
                    ),
                    affected_entities=(eid,),
                    details={
                        "annular_ring_mm": round(annular, 4),
                        "pad_diameter_mm": round(pad_dia, 4),
                        "drill_diameter_mm": round(drill_dia, 4),
                        "minimum_mm": min_annular,
                    },
                ))

        return findings


class HoleToHoleCheck(DfmCheck):
    """Validate minimum spacing between drilled holes.

    Holes too close together can cause board weakness or drill breakage.
    """

    name = "HOLE_SPACE_01"
    description = "Validate minimum spacing between drilled holes"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        holes = [p for p in primitives if getattr(p, "entity_type", "") in _DRILL_TYPES]
        if len(holes) < 2:
            return findings

        for i, h_a in enumerate(holes):
            x_a = getattr(h_a, "x", 0)
            y_a = getattr(h_a, "y", 0)
            dia_a = getattr(h_a, "drill_diameter", 0) / 2.0
            eid_a = getattr(h_a, "entity_id", "")

            for h_b in holes[i + 1:]:
                x_b = getattr(h_b, "x", 0)
                y_b = getattr(h_b, "y", 0)
                dia_b = getattr(h_b, "drill_diameter", 0) / 2.0

                # Edge-to-edge distance
                center_dist = math.sqrt((x_b - x_a) ** 2 + (y_b - y_a) ** 2)
                edge_dist = center_dist - dia_a - dia_b

                if edge_dist < _MIN_HOLE_SPACING_MM:
                    eid_b = getattr(h_b, "entity_id", "")
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Holes {eid_a} and {eid_b} edge-to-edge distance "
                            f"{edge_dist:.3f}mm below minimum {_MIN_HOLE_SPACING_MM}mm"
                        ),
                        severity=DfmSeverity.WARNING,
                        location=f"{eid_a}, {eid_b}",
                        suggestion=(
                            f"Increase hole spacing to at least "
                            f"{_MIN_HOLE_SPACING_MM}mm edge-to-edge"
                        ),
                        affected_entities=(eid_a, eid_b),
                        details={
                            "edge_distance_mm": round(max(0, edge_dist), 4),
                            "minimum_mm": _MIN_HOLE_SPACING_MM,
                        },
                    ))

        return findings


class PadToPadClearanceCheck(DfmCheck):
    """Validate pad-to-pad clearance on different nets.

    Same-net pads are exempt from clearance checks.
    """

    name = "PAD_CLEAR_01"
    description = "Validate pad-to-pad clearance"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_clearance = profile.min_clearance_mm
        primitives = _get_primitives(spatial_model)

        pads = [p for p in primitives if getattr(p, "entity_type", "") in _PAD_TYPES]
        if len(pads) < 2:
            return findings

        geom_cache: dict[str, Any] = {}

        def _g(p: Any) -> Any:
            eid = getattr(p, "entity_id", id(p))
            if eid not in geom_cache:
                geom_cache[eid] = _geom_or_none(p)
            return geom_cache[eid]

        for i, pad_a in enumerate(pads):
            geom_a = _g(pad_a)
            if geom_a is None:
                continue

            net_a = getattr(pad_a, "net", "")
            eid_a = getattr(pad_a, "entity_id", "")
            ref_a = _get_ref(pad_a)
            layer_a = getattr(pad_a, "layer", "")

            for pad_b in pads[i + 1:]:
                net_b = getattr(pad_b, "net", "")
                if net_a == net_b or net_a == "" or net_b == "":
                    continue

                layer_b = getattr(pad_b, "layer", "")
                if layer_a != layer_b:
                    continue

                geom_b = _g(pad_b)
                if geom_b is None:
                    continue

                try:
                    distance = geom_a.distance(geom_b)
                    if distance < min_clearance:
                        eid_b = getattr(pad_b, "entity_id", "")
                        ref_b = _get_ref(pad_b)
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Pads {ref_a} and {ref_b} on layer {layer_a} "
                                f"clearance {distance:.3f}mm (minimum {min_clearance}mm)"
                            ),
                            severity=DfmSeverity.WARNING,
                            location=f"{ref_a}, {ref_b} ({layer_a})",
                            suggestion=f"Increase pad spacing to at least {min_clearance}mm",
                            affected_entities=(eid_a, eid_b),
                            details={
                                "distance_mm": round(distance, 4),
                                "minimum_mm": min_clearance,
                                "layer": layer_a,
                            },
                        ))
                except Exception:
                    continue

        return findings


class ZoneFillCheck(DfmCheck):
    """Verify copper zones have been filled.

    Unfilled zones may cause DRC issues and manufacturing problems.
    """

    name = "ZONE_FILL_01"
    description = "Verify copper zones have been filled"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") != "zone":
                continue

            is_filled = getattr(p, "is_filled", None)
            eid = getattr(p, "entity_id", "")
            net = getattr(p, "net", "")

            if is_filled is False:
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Copper zone {eid} (net: {net}) is not filled. "
                        f"Fill zones before manufacturing."
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=f"{eid} ({net})",
                    suggestion="Fill all copper zones before generating Gerbers",
                    affected_entities=(eid,),
                    details={"net": net},
                ))

        return findings


class MinCopperPourWidthCheck(DfmCheck):
    """Validate minimum copper pour feature width.

    Thin copper pour necks can break during etching.
    """

    name = "COPPER_POUR_W_01"
    description = "Validate minimum copper pour feature width"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") != "copper_pour":
                continue

            size = _feature_size(p)
            if size > 0 and size < _MIN_COPPER_POUR_WIDTH_MM:
                eid = getattr(p, "entity_id", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Copper pour {eid} feature width {size:.3f}mm below "
                        f"minimum {_MIN_COPPER_POUR_WIDTH_MM}mm"
                    ),
                    severity=DfmSeverity.WARNING,
                    location=eid,
                    suggestion=(
                        f"Widen copper pour features to at least "
                        f"{_MIN_COPPER_POUR_WIDTH_MM}mm"
                    ),
                    affected_entities=(eid,),
                    details={
                        "width_mm": round(size, 4),
                        "minimum_mm": _MIN_COPPER_POUR_WIDTH_MM,
                    },
                ))

        return findings


# ===========================================================================
# Additional checks to reach 50+ total
# ===========================================================================


class PadAnnularRingCheck(DfmCheck):
    """Validate pad annular ring (complements the existing AnnularRingCheck).

    Uses pad_diameter and drill_diameter attributes directly when available,
    covering pads that have explicit drill data attached rather than
    companion drill primitives.
    """

    name = "PAD_ANNULAR_01"
    description = "Validate pad annular ring using direct pad attributes"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_annular = profile.min_annular_ring_mm
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") not in _PAD_TYPES:
                continue

            pad_dia = _get_float(p, "pad_diameter")
            drill_dia = _get_float(p, "drill_diameter")
            if pad_dia is None or drill_dia is None or drill_dia == 0:
                continue

            annular = (pad_dia - drill_dia) / 2.0
            if annular < min_annular:
                eid = getattr(p, "entity_id", "")
                ref = _get_ref(p)
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Pad {ref} annular ring {annular:.3f}mm below "
                        f"minimum {min_annular}mm"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=ref,
                    suggestion=f"Increase pad size or reduce drill for minimum {min_annular}mm annular ring",
                    affected_entities=(eid,),
                    details={"annular_ring_mm": round(annular, 4), "minimum_mm": min_annular},
                ))

        return findings


class ViaToPadSpacingCheck(DfmCheck):
    """Validate spacing between vias and nearby pads on different nets."""

    name = "VIA_PAD_SPACE_01"
    description = "Validate via-to-pad spacing on different nets"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_clearance = profile.min_clearance_mm
        primitives = _get_primitives(spatial_model)

        vias = [p for p in primitives if getattr(p, "entity_type", "") in _VIA_TYPES]
        pads = [p for p in primitives if getattr(p, "entity_type", "") in _PAD_TYPES]

        if not vias or not pads:
            return findings

        for via in vias:
            via_geom = _geom_or_none(via)
            if via_geom is None:
                continue

            via_net = getattr(via, "net", "")
            via_eid = getattr(via, "entity_id", "")

            for pad in pads:
                pad_net = getattr(pad, "net", "")
                if pad_net == via_net or pad_net == "" or via_net == "":
                    continue

                pad_geom = _geom_or_none(pad)
                if pad_geom is None:
                    continue

                try:
                    distance = via_geom.distance(pad_geom)
                    if distance < min_clearance:
                        pad_eid = getattr(pad, "entity_id", "")
                        pad_ref = _get_ref(pad)
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Via {via_eid} too close to pad {pad_ref} "
                                f"({distance:.3f}mm < {min_clearance}mm)"
                            ),
                            severity=DfmSeverity.WARNING,
                            location=f"{via_eid}, {pad_ref}",
                            suggestion=f"Increase via-to-pad spacing to {min_clearance}mm",
                            affected_entities=(via_eid, pad_eid),
                            details={"distance_mm": round(distance, 4), "minimum_mm": min_clearance},
                        ))
                except Exception:
                    continue

        return findings


class ViaToTraceSpacingCheck(DfmCheck):
    """Validate spacing between vias and traces on different nets."""

    name = "VIA_TRACE_SPACE_01"
    description = "Validate via-to-trace spacing on different nets"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_clearance = profile.min_clearance_mm
        primitives = _get_primitives(spatial_model)

        vias = [p for p in primitives if getattr(p, "entity_type", "") in _VIA_TYPES]
        traces = [p for p in primitives if getattr(p, "entity_type", "") in _TRACE_TYPES]

        if not vias or not traces:
            return findings

        for via in vias:
            via_geom = _geom_or_none(via)
            if via_geom is None:
                continue

            via_net = getattr(via, "net", "")
            via_eid = getattr(via, "entity_id", "")

            for trace in traces:
                trace_net = getattr(trace, "net", "")
                if trace_net == via_net or trace_net == "" or via_net == "":
                    continue

                trace_geom = _geom_or_none(trace)
                if trace_geom is None:
                    continue

                try:
                    distance = via_geom.distance(trace_geom)
                    if distance < min_clearance:
                        trace_eid = getattr(trace, "entity_id", "")
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Via {via_eid} too close to trace {trace_eid} "
                                f"({distance:.3f}mm < {min_clearance}mm)"
                            ),
                            severity=DfmSeverity.WARNING,
                            location=f"{via_eid}, {trace_eid}",
                            suggestion=f"Increase via-to-trace spacing to {min_clearance}mm",
                            affected_entities=(via_eid, trace_eid),
                            details={"distance_mm": round(distance, 4), "minimum_mm": min_clearance},
                        ))
                except Exception:
                    continue

        return findings


class KeepoutZoneViolationCheck(DfmCheck):
    """Detect copper features inside keepout zones."""

    name = "KEEPOUT_01"
    description = "Detect copper features inside keepout zones"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        keepouts = [p for p in primitives if getattr(p, "entity_type", "") == "keepout_zone"]
        features = [p for p in primitives
                    if getattr(p, "entity_type", "") in _PAD_TYPES | _TRACE_TYPES | frozenset(_VIA_TYPES)]

        if not keepouts or not features:
            return findings

        for ko in keepouts:
            ko_geom = _geom_or_none(ko)
            if ko_geom is None:
                continue

            ko_eid = getattr(ko, "entity_id", "")

            for feat in features:
                feat_geom = _geom_or_none(feat)
                if feat_geom is None:
                    continue

                try:
                    if ko_geom.contains(feat_geom):
                        feat_eid = getattr(feat, "entity_id", "")
                        feat_ref = _get_ref(feat)
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Feature {feat_ref} inside keepout zone {ko_eid}. "
                                f"Remove copper from keepout areas."
                            ),
                            severity=DfmSeverity.CRITICAL,
                            location=f"{feat_ref}, {ko_eid}",
                            suggestion="Remove copper features from keepout zones",
                            affected_entities=(feat_eid, ko_eid),
                        ))
                except Exception:
                    continue

        return findings


class DifferentialPairSpacingCheck(DfmCheck):
    """Validate differential pair trace spacing."""

    name = "DIFF_PAIR_01"
    description = "Validate differential pair spacing consistency"

    _DIFF_NET_PATTERNS = {"DIFF", "DP", "D+", "D-", "SDA", "SCL", "USB_D", "USB_D+"}

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        traces = [p for p in primitives if getattr(p, "entity_type", "") in _TRACE_TYPES]

        diff_traces = [
            t for t in traces
            if any(pat in getattr(t, "net", "").upper() for pat in self._DIFF_NET_PATTERNS)
        ]

        if len(diff_traces) < 2:
            return findings

        geom_cache: dict[str, Any] = {}

        def _g(p: Any) -> Any:
            eid = getattr(p, "entity_id", id(p))
            if eid not in geom_cache:
                geom_cache[eid] = _geom_or_none(p)
            return geom_cache[eid]

        for i, tr_a in enumerate(diff_traces):
            geom_a = _g(tr_a)
            if geom_a is None:
                continue

            net_a = getattr(tr_a, "net", "")

            for tr_b in diff_traces[i + 1:]:
                net_b = getattr(tr_b, "net", "")
                if net_a == net_b:
                    continue

                geom_b = _g(tr_b)
                if geom_b is None:
                    continue

                try:
                    distance = geom_a.distance(geom_b)
                    if distance < profile.min_clearance_mm:
                        eid_a = getattr(tr_a, "entity_id", "")
                        eid_b = getattr(tr_b, "entity_id", "")
                        findings.append(DfmFinding(
                            check_id=self.name,
                            description=(
                                f"Differential pair traces {eid_a} ({net_a}) and "
                                f"{eid_b} ({net_b}) spacing {distance:.3f}mm "
                                f"below clearance {profile.min_clearance_mm}mm"
                            ),
                            severity=DfmSeverity.WARNING,
                            location=f"{eid_a}, {eid_b}",
                            suggestion="Maintain consistent differential pair spacing for impedance control",
                            affected_entities=(eid_a, eid_b),
                            details={
                                "distance_mm": round(distance, 4),
                                "minimum_mm": profile.min_clearance_mm,
                                "net_a": net_a,
                                "net_b": net_b,
                            },
                        ))
                except Exception:
                    continue

        return findings


class MinPadDiameterCheck(DfmCheck):
    """Validate minimum pad diameter for SMD and THT pads."""

    name = "MIN_PAD_DIA_01"
    description = "Validate minimum pad diameter"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") not in _PAD_TYPES:
                continue

            pad_dia = _get_float(p, "pad_diameter")
            if pad_dia is None:
                x1 = getattr(p, "x1", 0)
                y1 = getattr(p, "y1", 0)
                x2 = getattr(p, "x2", 0)
                y2 = getattr(p, "y2", 0)
                pad_dia = min(abs(x2 - x1), abs(y2 - y1))
                if pad_dia <= 0:
                    continue

            min_pad = profile.min_via_diameter_mm * 0.8
            if pad_dia < min_pad:
                eid = getattr(p, "entity_id", "")
                ref = _get_ref(p)
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Pad {ref} diameter {pad_dia:.3f}mm below "
                        f"minimum {min_pad:.3f}mm"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=ref,
                    suggestion=f"Increase pad size to at least {min_pad:.3f}mm",
                    affected_entities=(eid,),
                    details={"pad_diameter_mm": round(pad_dia, 4), "minimum_mm": min_pad},
                ))

        return findings


class TraceToEdgeClearanceCheck(DfmCheck):
    """Validate trace clearance from board edge."""

    name = "TRACE_EDGE_01"
    description = "Validate trace clearance from board edge"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        edge_prims = [p for p in primitives if getattr(p, "layer", "") in _EDGE_LAYERS]
        traces = [p for p in primitives if getattr(p, "entity_type", "") in _TRACE_TYPES]

        if not edge_prims or not traces:
            return findings

        edge_geoms = [_geom_or_none(ep) for ep in edge_prims]
        edge_geoms = [eg for eg in edge_geoms if eg is not None]
        if not edge_geoms:
            return findings

        try:
            from shapely.ops import unary_union, polygonize
            board_outline = unary_union(edge_geoms)
            if board_outline.geom_type in ("LineString", "MultiLineString"):
                polygons = list(polygonize([board_outline]))
                if polygons:
                    board_area = unary_union(polygons)
                else:
                    board_area = board_outline.convex_hull
            else:
                board_area = board_outline
            clearance_zone = board_area.buffer(-_MIN_EDGE_CLEARANCE_MM)
            if clearance_zone.is_empty:
                clearance_zone = board_area
        except Exception:
            return findings

        for trace in traces:
            trace_geom = _geom_or_none(trace)
            if trace_geom is None:
                continue

            try:
                if trace_geom.intersects(clearance_zone):
                    eid = getattr(trace, "entity_id", "")
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Trace {eid} within {_MIN_EDGE_CLEARANCE_MM}mm of board edge"
                        ),
                        severity=DfmSeverity.WARNING,
                        location=eid,
                        suggestion=f"Route trace at least {_MIN_EDGE_CLEARANCE_MM}mm from board edge",
                        affected_entities=(eid,),
                    ))
            except Exception:
                continue

        return findings


class PadToEdgeClearanceCheck(DfmCheck):
    """Validate pad clearance from board edge."""

    name = "PAD_EDGE_01"
    description = "Validate pad clearance from board edge"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_clear = profile.min_clearance_mm * 2.0
        primitives = _get_primitives(spatial_model)

        edge_prims = [p for p in primitives if getattr(p, "layer", "") in _EDGE_LAYERS]
        pads = [p for p in primitives if getattr(p, "entity_type", "") in _PAD_TYPES]

        if not edge_prims or not pads:
            return findings

        edge_geoms = [_geom_or_none(ep) for ep in edge_prims]
        edge_geoms = [eg for eg in edge_geoms if eg is not None]
        if not edge_geoms:
            return findings

        try:
            from shapely.ops import unary_union, polygonize
            board_outline = unary_union(edge_geoms)
            if board_outline.geom_type in ("LineString", "MultiLineString"):
                polygons = list(polygonize([board_outline]))
                if polygons:
                    board_area = unary_union(polygons)
                else:
                    board_area = board_outline.convex_hull
            else:
                board_area = board_outline
            clearance_zone = board_area.buffer(-min_clear)
            if clearance_zone.is_empty:
                clearance_zone = board_area
        except Exception:
            return findings

        for pad in pads:
            pad_geom = _geom_or_none(pad)
            if pad_geom is None:
                continue

            try:
                if pad_geom.intersects(clearance_zone):
                    eid = getattr(pad, "entity_id", "")
                    ref = _get_ref(pad)
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Pad {ref} within {min_clear:.1f}mm of board edge"
                        ),
                        severity=DfmSeverity.WARNING,
                        location=ref,
                        suggestion=f"Move pad at least {min_clear:.1f}mm from board edge",
                        affected_entities=(eid,),
                    ))
            except Exception:
                continue

        return findings


class ComponentTooCloseCheck(DfmCheck):
    """Validate minimum center-to-center distance between SMD components."""

    name = "COMP_SPACE_01"
    description = "Validate minimum component spacing"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_spacing = profile.min_clearance_mm * 4.0
        primitives = _get_primitives(spatial_model)

        components = [p for p in primitives
                      if getattr(p, "entity_type", "") in {"footprint", "component"}]

        if len(components) < 2:
            return findings

        for i, comp_a in enumerate(components):
            cx_a = (getattr(comp_a, "x1", 0) + getattr(comp_a, "x2", 0)) / 2.0
            cy_a = (getattr(comp_a, "y1", 0) + getattr(comp_a, "y2", 0)) / 2.0
            eid_a = getattr(comp_a, "entity_id", "")
            ref_a = _get_ref(comp_a)

            for comp_b in components[i + 1:]:
                cx_b = (getattr(comp_b, "x1", 0) + getattr(comp_b, "x2", 0)) / 2.0
                cy_b = (getattr(comp_b, "y1", 0) + getattr(comp_b, "y2", 0)) / 2.0

                dist = math.sqrt((cx_b - cx_a) ** 2 + (cy_b - cy_a) ** 2)
                if dist < min_spacing:
                    eid_b = getattr(comp_b, "entity_id", "")
                    ref_b = _get_ref(comp_b)
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Components {ref_a} and {ref_b} too close "
                            f"({dist:.2f}mm < {min_spacing:.2f}mm)"
                        ),
                        severity=DfmSeverity.INFO,
                        location=f"{ref_a}, {ref_b}",
                        suggestion="Increase component spacing for assembly",
                        affected_entities=(eid_a, eid_b),
                        details={"distance_mm": round(dist, 4), "minimum_mm": round(min_spacing, 4)},
                    ))

        return findings


class BoardOutlineClosedCheck(DfmCheck):
    """Verify board outline forms a closed shape."""

    name = "OUTLINE_CLOSED_01"
    description = "Verify board outline is closed"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        edge_prims = [p for p in primitives if getattr(p, "layer", "") in _EDGE_LAYERS]

        if not edge_prims:
            findings.append(DfmFinding(
                check_id=self.name,
                description="No board outline (Edge.Cuts) found",
                severity=DfmSeverity.CRITICAL,
                location="(board)",
                suggestion="Add board outline on Edge.Cuts layer before manufacturing",
                affected_entities=(),
            ))
            return findings

        edge_geoms = [_geom_or_none(ep) for ep in edge_prims]
        edge_geoms = [eg for eg in edge_geoms if eg is not None]

        if not edge_geoms:
            return findings

        try:
            from shapely.ops import polygonize, unary_union
            outline = unary_union(edge_geoms)
            if outline.geom_type in ("LineString", "MultiLineString"):
                polygons = list(polygonize([outline]))
                if not polygons:
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description="Board outline does not form a closed shape",
                        severity=DfmSeverity.CRITICAL,
                        location="(board outline)",
                        suggestion="Close the board outline by connecting all Edge.Cuts segments",
                        affected_entities=(),
                    ))
        except Exception:
            pass

        return findings


class MinCopperThicknessCheck(DfmCheck):
    """Check copper thickness specification for power traces."""

    name = "COPPER_THICK_01"
    description = "Check copper thickness for power traces"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        for p in primitives:
            if getattr(p, "entity_type", "") not in _TRACE_TYPES:
                continue

            net = getattr(p, "net", "")
            width = _get_float(p, "width", 0)

            if not _is_power_net(net):
                continue

            copper_oz = _get_float(p, "copper_oz")
            eid = getattr(p, "entity_id", "")

            if width > 2.0 and (copper_oz is None or copper_oz < 2.0):
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Power trace {eid} on net '{net}' is {width:.2f}mm wide. "
                        f"Consider 2oz+ copper for high current paths."
                    ),
                    severity=DfmSeverity.INFO,
                    location=eid,
                    suggestion="Use 2oz or thicker copper for wide power traces",
                    affected_entities=(eid,),
                    details={"width_mm": round(width, 4), "net": net},
                ))

        return findings


class ViaOnPadTypeCheck(DfmCheck):
    """Check that via-in-pad footprints are used when vias are on pads."""

    name = "VIA_PAD_TYPE_01"
    description = "Check via-in-pad footprint usage"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        vias = [p for p in primitives if getattr(p, "entity_type", "") in _VIA_TYPES]
        if not vias:
            return findings

        for via in vias:
            via_type = getattr(via, "via_type", None)
            eid = getattr(via, "entity_id", "")

            if via_type == "through" and getattr(via, "on_pad", False):
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Through via {eid} detected on pad. "
                        f"Use filled/plugged via or via-in-pad footprint."
                    ),
                    severity=DfmSeverity.INFO,
                    location=eid,
                    suggestion="Replace with filled via or use dedicated via-in-pad footprint",
                    affected_entities=(eid,),
                ))

        return findings


class ThermalPadCheck(DfmCheck):
    """Check for thermal relief pads on power plane connections."""

    name = "THERMAL_PAD_01"
    description = "Check thermal relief on power plane pads"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        primitives = _get_primitives(spatial_model)

        pads = [p for p in primitives if getattr(p, "entity_type", "") in _PAD_TYPES]

        for pad in pads:
            net = getattr(pad, "net", "")
            if not _is_power_net(net):
                continue

            has_thermal = getattr(pad, "has_thermal_relief", None)
            if has_thermal is False:
                eid = getattr(pad, "entity_id", "")
                ref = _get_ref(pad)
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Power pad {ref} (net: {net}) may lack thermal relief. "
                        f"Direct connection to power plane makes soldering difficult."
                    ),
                    severity=DfmSeverity.INFO,
                    location=ref,
                    suggestion="Add thermal relief spokes to power plane pad connections",
                    affected_entities=(eid,),
                    details={"net": net},
                ))

        return findings