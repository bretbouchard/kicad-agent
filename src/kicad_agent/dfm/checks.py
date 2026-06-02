"""Built-in DFM checks for manufacturability assessment.

DFM-03: Five pluggable DFM checks that validate PCB design against
manufacturer-specific constraints from ManufacturerProfile.

Checks:
  ANNULAR_RING_01: Pad annular ring adequacy
  SOLDER_MASK_01: Solder mask web/sliver minimum
  THERMAL_RELIEF_01: Thermal relief spokes on copper zone pads
  MIN_TRACE_01: Minimum trace width
  MIN_DRILL_01: Minimum drill size

Usage:
    from kicad_agent.dfm.checks import get_builtin_dfm_checks
    from kicad_agent.dfm.checker import DfmChecker

    checker = DfmChecker(checks=get_builtin_dfm_checks())
    report = checker.run(spatial_model, profile)
"""
from __future__ import annotations

import logging
import math
from typing import Any

from kicad_agent.dfm.checker import DfmCheck, DfmFinding, DfmSeverity

logger = logging.getLogger(__name__)


class AnnularRingCheck(DfmCheck):
    """Validate pad annular ring against profile minimum.

    For each pad with a drill hole, computes annular ring as
    (pad_diameter - drill_diameter) / 2 and flags violations.

    Drill data is extracted from companion SpatialPoint primitives
    with entity_type "drill" matching the pad entity_id prefix.
    If drill data is unavailable, the pad is skipped (not flagged).
    """

    name = "ANNULAR_RING_01"
    description = "Validate pad annular ring against manufacturer minimum"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_annular = profile.min_annular_ring_mm

        primitives = spatial_model.all_primitives if hasattr(spatial_model, "all_primitives") else []

        # Index drill primitives by entity_id prefix
        drills: dict[str, Any] = {}
        for p in primitives:
            etype = getattr(p, "entity_type", "")
            if etype == "drill":
                eid = getattr(p, "entity_id", "")
                # Drill entity_id may be "{pad_id}_drill" or match pad entity_id
                drills[eid] = p
                # Also index by prefix (before "_drill" suffix)
                if eid.endswith("_drill"):
                    drills[eid.replace("_drill", "")] = p

        for p in primitives:
            etype = getattr(p, "entity_type", "")
            if etype != "pad":
                continue

            eid = getattr(p, "entity_id", "")
            ref = getattr(p, "reference", eid)

            # Look up drill data
            drill = drills.get(eid) or drills.get(f"{eid}_drill")
            if drill is None:
                logger.debug("AnnularRingCheck: no drill data for pad %s, skipping", eid)
                continue

            # Compute pad size (min of width/height for square pads)
            x1 = getattr(p, "x1", 0)
            y1 = getattr(p, "y1", 0)
            x2 = getattr(p, "x2", 0)
            y2 = getattr(p, "y2", 0)
            pad_width = x2 - x1
            pad_height = y2 - y1
            pad_diameter = min(pad_width, pad_height)

            # Drill diameter from point's drill_diameter attribute or distance
            drill_diameter = getattr(drill, "drill_diameter", None)
            if drill_diameter is None:
                logger.debug("AnnularRingCheck: no drill_diameter attribute for %s, skipping", eid)
                continue

            annular_ring = (pad_diameter - drill_diameter) / 2.0

            if annular_ring < min_annular:
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Annular ring {annular_ring:.3f}mm below "
                        f"minimum {min_annular}mm for pad {ref}"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=ref,
                    suggestion=(
                        f"Increase pad size or reduce drill diameter to achieve "
                        f"minimum {min_annular}mm annular ring"
                    ),
                    affected_entities=(eid,),
                    details={
                        "annular_ring_mm": round(annular_ring, 4),
                        "pad_diameter_mm": round(pad_diameter, 4),
                        "drill_diameter_mm": round(drill_diameter, 4),
                        "minimum_mm": min_annular,
                    },
                ))

        return findings


class SolderMaskCheck(DfmCheck):
    """Detect solder mask web/sliver violations between nearby pads.

    Checks pad pairs on mask layers (F.Mask, B.Mask) for spacing
    below the profile's minimum solder mask sliver. Only compares
    pads within 2x sliver distance to avoid O(n^2) on full board.
    """

    name = "SOLDER_MASK_01"
    description = "Detect solder mask web/sliver violations between pads"

    _MASK_LAYERS = {"F.Mask", "B.Mask"}

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_sliver = profile.min_solder_mask_sliver_mm

        primitives = spatial_model.all_primitives if hasattr(spatial_model, "all_primitives") else []

        # Collect pads on mask layers
        mask_pads: list[Any] = []
        for p in primitives:
            etype = getattr(p, "entity_type", "")
            layer = getattr(p, "layer", "")
            if etype == "pad" and layer in self._MASK_LAYERS:
                mask_pads.append(p)

        # Cache to_shapely() results to avoid redundant geometry computation.
        # Keyed by entity_id since to_shapely() can be expensive.
        geom_cache: dict[str, Any] = {}

        def _get_geom(pad: Any) -> Any:
            eid = getattr(pad, "entity_id", id(pad))
            if eid not in geom_cache:
                geom_cache[eid] = pad.to_shapely() if hasattr(pad, "to_shapely") else None
            return geom_cache[eid]

        # Compare nearby pairs (within 2x sliver distance)
        max_compare_dist = min_sliver * 4.0  # generous proximity window
        for i, pad_a in enumerate(mask_pads):
            geom_a = _get_geom(pad_a)
            if geom_a is None:
                continue
            ref_a = getattr(pad_a, "reference", getattr(pad_a, "entity_id", ""))
            eid_a = getattr(pad_a, "entity_id", "")

            for pad_b in mask_pads[i + 1:]:
                geom_b = _get_geom(pad_b)
                if geom_b is None:
                    continue

                # Quick bounding box pre-check
                x1_b, y1_b, x2_b, y2_b = getattr(pad_b, "x1", 0), getattr(pad_b, "y1", 0), getattr(pad_b, "x2", 0), getattr(pad_b, "y2", 0)
                x1_a, y1_a, x2_a, y2_a = getattr(pad_a, "x1", 0), getattr(pad_a, "y1", 0), getattr(pad_a, "x2", 0), getattr(pad_a, "y2", 0)
                # If bounding boxes are far apart, skip
                dx = max(0, x1_b - x2_a, x1_a - x2_b)
                dy = max(0, y1_b - y2_a, y1_a - y2_b)
                if dx * dx + dy * dy > (max_compare_dist * 2) ** 2:
                    continue

                distance = geom_a.distance(geom_b)
                if distance < min_sliver:
                    ref_b = getattr(pad_b, "reference", getattr(pad_b, "entity_id", ""))
                    eid_b = getattr(pad_b, "entity_id", "")
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Solder mask sliver {distance:.3f}mm between "
                            f"pads {ref_a} and {ref_b} below minimum {min_sliver}mm"
                        ),
                        severity=DfmSeverity.WARNING,
                        location=f"{ref_a}, {ref_b}",
                        suggestion=(
                            f"Increase spacing between pads to maintain minimum "
                            f"{min_sliver}mm solder mask web"
                        ),
                        affected_entities=(eid_a, eid_b),
                        details={
                            "distance_mm": round(distance, 4),
                            "minimum_mm": min_sliver,
                        },
                    ))

        return findings


class ThermalReliefCheck(DfmCheck):
    """Verify thermal relief spokes on pads connected to copper zones.

    Checks that pads on copper zones have thermal relief traces
    connecting them. Flags pads inside zones with no connecting traces
    as WARNING (potential soldering difficulty).
    """

    name = "THERMAL_RELIEF_01"
    description = "Verify thermal relief spokes on copper zone pads"

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []

        primitives = spatial_model.all_primitives if hasattr(spatial_model, "all_primitives") else []

        # Separate zones and pads by layer+net
        zones: list[Any] = []
        pads: list[Any] = []
        traces: list[Any] = []

        for p in primitives:
            etype = getattr(p, "entity_type", "")
            if etype == "zone":
                zones.append(p)
            elif etype == "pad":
                pads.append(p)
            elif etype in ("trace", "track", "segment"):
                traces.append(p)

        if not zones:
            return findings

        # Build zone geometries
        zone_geoms = []
        for z in zones:
            geom = z.to_shapely() if hasattr(z, "to_shapely") else None
            if geom is not None:
                zone_geoms.append((z, geom))

        if not zone_geoms:
            # Zone data not extractable -> INFO finding
            findings.append(DfmFinding(
                check_id=self.name,
                description="Zone geometry not extractable; thermal relief check skipped",
                severity=DfmSeverity.INFO,
                location="(all zones)",
                suggestion="Ensure zone primitives have to_shapely() support for thermal relief validation",
                affected_entities=tuple(z.entity_id for z in zones),
            ))
            return findings

        # Build trace geometries by net for spoke detection
        trace_by_net: dict[str, list[Any]] = {}
        for t in traces:
            net = getattr(t, "net", "")
            if net:
                trace_by_net.setdefault(net, []).append(t)

        # Check each pad against zones
        for pad in pads:
            pad_geom = pad.to_shapely() if hasattr(pad, "to_shapely") else None
            if pad_geom is None:
                continue

            pad_net = getattr(pad, "net", "")
            pad_eid = getattr(pad, "entity_id", "")
            pad_ref = getattr(pad, "reference", pad_eid)
            pad_layer = getattr(pad, "layer", "")

            for zone, zone_geom in zone_geoms:
                zone_net = getattr(zone, "net", "")
                zone_eid = getattr(zone, "entity_id", "")
                zone_layer = getattr(zone, "layer", "")

                # Zone and pad must share net and layer
                if pad_net != zone_net or pad_layer != zone_layer:
                    continue

                # Check if pad is inside or overlapping zone
                if not pad_geom.intersects(zone_geom) and not zone_geom.contains(pad_geom):
                    continue

                # Pad is inside zone on same net -- check for thermal spokes
                # A thermal spoke is a trace connecting pad to zone on the same net
                pad_traces = trace_by_net.get(pad_net, [])
                has_spoke = False
                for trace in pad_traces:
                    trace_geom = trace.to_shapely() if hasattr(trace, "to_shapely") else None
                    if trace_geom is None:
                        continue
                    # Check if trace connects pad to zone (intersects both or near pad boundary)
                    if pad_geom.intersects(trace_geom) and zone_geom.intersects(trace_geom):
                        has_spoke = True
                        break

                if not has_spoke:
                    findings.append(DfmFinding(
                        check_id=self.name,
                        description=(
                            f"Pad {pad_ref} on copper zone {zone_eid} (net: {pad_net}) "
                            f"may lack thermal relief spokes"
                        ),
                        severity=DfmSeverity.WARNING,
                        location=f"{pad_ref} on zone {zone_eid}",
                        suggestion=(
                            "Add thermal relief spokes to pad connected to copper zone "
                            "for reliable soldering"
                        ),
                        affected_entities=(pad_eid, zone_eid),
                        details={
                            "pad_net": pad_net,
                            "zone_id": zone_eid,
                        },
                    ))

        return findings


class MinTraceWidthCheck(DfmCheck):
    """Flag traces with width below profile minimum.

    Checks SpatialPath primitives with entity_type "trace" or "track"
    against the profile's minimum trace width. Skips traces with
    width=0 (unextracted width data).
    """

    name = "MIN_TRACE_01"
    description = "Flag traces below manufacturer minimum width"

    _TRACE_TYPES = {"trace", "track", "segment", "wire"}

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_width = profile.min_trace_width_mm

        primitives = spatial_model.all_primitives if hasattr(spatial_model, "all_primitives") else []

        for p in primitives:
            etype = getattr(p, "entity_type", "")
            if etype not in self._TRACE_TYPES:
                continue

            width = getattr(p, "width", 0.0)
            if width == 0.0:
                logger.debug("MinTraceWidthCheck: skipping %s with zero width", getattr(p, "entity_id", ""))
                continue

            if width < min_width:
                eid = getattr(p, "entity_id", "")
                layer = getattr(p, "layer", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Trace width {width:.3f}mm below minimum {min_width}mm "
                        f"on layer {layer}"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=f"{eid} ({layer})",
                    suggestion=(
                        f"Increase trace width from {width:.3f}mm to at least "
                        f"{min_width}mm"
                    ),
                    affected_entities=(eid,),
                    details={
                        "width_mm": round(width, 4),
                        "minimum_mm": min_width,
                        "layer": layer,
                    },
                ))

        return findings


class MinDrillCheck(DfmCheck):
    """Flag vias/pads with drill below profile minimum.

    Checks SpatialPoint primitives with entity_type "via_drill" or
    "drill" against the profile's minimum drill size. Drill diameter
    is read from a drill_diameter attribute on the primitive.
    """

    name = "MIN_DRILL_01"
    description = "Flag drills below manufacturer minimum size"

    _DRILL_TYPES = {"via_drill", "drill"}

    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        findings: list[DfmFinding] = []
        min_drill = profile.min_drill_mm

        primitives = spatial_model.all_primitives if hasattr(spatial_model, "all_primitives") else []

        for p in primitives:
            etype = getattr(p, "entity_type", "")
            if etype not in self._DRILL_TYPES:
                continue

            drill_diameter = getattr(p, "drill_diameter", None)
            if drill_diameter is None:
                logger.debug(
                    "MinDrillCheck: no drill_diameter on %s, skipping",
                    getattr(p, "entity_id", ""),
                )
                continue

            if drill_diameter < min_drill:
                eid = getattr(p, "entity_id", "")
                layer = getattr(p, "layer", "")
                findings.append(DfmFinding(
                    check_id=self.name,
                    description=(
                        f"Drill size {drill_diameter:.3f}mm below minimum {min_drill}mm "
                        f"for {eid}"
                    ),
                    severity=DfmSeverity.CRITICAL,
                    location=f"{eid} ({layer})" if layer else eid,
                    suggestion=(
                        f"Increase drill size from {drill_diameter:.3f}mm to at least "
                        f"{min_drill}mm"
                    ),
                    affected_entities=(eid,),
                    details={
                        "drill_diameter_mm": round(drill_diameter, 4),
                        "minimum_mm": min_drill,
                    },
                ))

        return findings


def get_builtin_dfm_checks() -> list[DfmCheck]:
    """Return all built-in DFM check instances.

    Returns:
        List of 5 DfmCheck instances:
        AnnularRingCheck, SolderMaskCheck, ThermalReliefCheck,
        MinTraceWidthCheck, MinDrillCheck.
    """
    return [
        AnnularRingCheck(),
        SolderMaskCheck(),
        ThermalReliefCheck(),
        MinTraceWidthCheck(),
        MinDrillCheck(),
    ]
