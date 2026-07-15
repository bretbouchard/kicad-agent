//
//  NativeDRC.swift
//  Phase 222 — Swift Native DRC Engine
//
//  Pure Swift port of native_drc.py. Uses Geometry.swift instead of shapely.
//
//  Checks:
//    5.  Copper spacing (segment/pad/via pairwise with spatial hash)
//    6.  Board edge clearance
//    7.  Netclass width enforcement
//    8.  Global minimum track width
//    9.  Courtyard overlap
//    10. Hole-to-hole clearance
//    11. Annular ring
//

import Foundation
import OSLog

// MARK: - Result Types

struct DRCViolation: Identifiable, Sendable {
    let id = UUID()
    let severity: String
    let checkId: String
    let description: String
    var layer: String = ""
    var net: String = ""
    var position: (Double, Double)?
    var value: Double?
    var limit: Double?

    func toDict() -> [String: Any] {
        var d: [String: Any] = [
            "severity": severity, "check_id": checkId, "description": description,
        ]
        if !layer.isEmpty { d["layer"] = layer }
        if !net.isEmpty { d["net"] = net }
        if let pos = position { d["position"] = [pos.0, pos.1] }
        if let v = value { d["value"] = v }
        if let l = limit { d["limit"] = l }
        return d
    }
}

struct NativeDrcResult: Sendable {
    let violations: [DRCViolation]
    let checksRun: [String]
    let checksSkipped: [String]

    var errorCount: Int { violations.filter { $0.severity == "error" }.count }
    var warningCount: Int { violations.filter { $0.severity == "warning" }.count }
    var passed: Bool { errorCount == 0 }

    func toDict() -> [String: Any] {
        [
            "clean": passed,
            "error_count": errorCount,
            "warning_count": warningCount,
            "violations": violations.map { $0.toDict() },
            "checks_run": checksRun,
            "checks_skipped": checksSkipped,
        ]
    }
}

// MARK: - DRC Defaults

let DEFAULT_MIN_CLEARANCE: Double = 0.127
let DEFAULT_MIN_TRACK_WIDTH: Double = 0.127
let DEFAULT_MIN_DRILL: Double = 0.3
let DEFAULT_MIN_ANNULAR: Double = 0.15
let DEFAULT_EDGE_CLEARANCE: Double = 0.3
let DEFAULT_HOLE_TO_HOLE: Double = 0.3

// MARK: - Native DRC

struct NativeDRC {

    // MARK: - Check 7+8: Track Width

    static func checkTrackWidths(
        segments: [(start: CGPoint, end: CGPoint, width: Double, net: String, layer: String)],
        minWidth: Double = DEFAULT_MIN_TRACK_WIDTH
    ) -> [DRCViolation] {
        segments.filter { !$0.net.isEmpty && $0.width < minWidth }.map { seg in
            let mid = CGPoint((seg.start.x + seg.end.x) / 2, (seg.start.y + seg.end.y) / 2)
            return DRCViolation(
                severity: "error", checkId: "DRC_MIN_TRACK_WIDTH",
                description: String(format: "Track width %.3fmm < minimum %.3fmm", seg.width, minWidth),
                layer: seg.layer, net: seg.net,
                position: (Double(mid.x), Double(mid.y)),
                value: seg.width, limit: minWidth
            )
        }
    }

    // MARK: - Check 10: Hole-to-Hole

    static func checkHoleClearance(
        holes: [(pos: CGPoint, drill: Double, ref: String, fpRef: String)],
        minClearance: Double = DEFAULT_HOLE_TO_HOLE
    ) -> [DRCViolation] {
        var violations: [DRCViolation] = []
        for i in 0..<holes.count {
            for j in (i+1)..<holes.count {
                let a = holes[i], b = holes[j]
                if !a.fpRef.isEmpty && a.fpRef == b.fpRef { continue }
                let centerDist = a.pos.distance(to: b.pos)
                let edgeDist = centerDist - (a.drill + b.drill) / 2
                if edgeDist < minClearance {
                    let display = max(0, edgeDist)
                    violations.append(DRCViolation(
                        severity: "error", checkId: "DRC_HOLE_CLEARANCE",
                        description: String(format: "Hole-to-hole %.3fmm < %.3fmm (%@ ↔ %@)",
                                           display, minClearance, a.ref, b.ref),
                        position: (Double((a.pos.x + b.pos.x) / 2), Double((a.pos.y + b.pos.y) / 2)),
                        value: display, limit: minClearance
                    ))
                }
            }
        }
        return violations
    }

    // MARK: - Check 12: Annular Ring

    static func checkAnnularRing(
        vias: [(pos: CGPoint, size: Double, drill: Double)],
        pads: [(pos: CGPoint, size: [Double], drill: Double, ref: String)],
        minAnnular: Double = DEFAULT_MIN_ANNULAR
    ) -> [DRCViolation] {
        var violations: [DRCViolation] = []

        for via in vias {
            let annular = (via.size - via.drill) / 2
            if annular < minAnnular {
                violations.append(DRCViolation(
                    severity: "error", checkId: "DRC_ANNULAR_RING",
                    description: String(format: "Via annular ring %.3fmm < %.3fmm", annular, minAnnular),
                    position: (Double(via.pos.x), Double(via.pos.y)),
                    value: annular, limit: minAnnular
                ))
            }
        }

        for pad in pads {
            guard pad.drill > 0 else { continue }
            let minSize = min(pad.size[0], pad.size.count > 1 ? pad.size[1] : pad.size[0])
            let annular = (minSize - pad.drill) / 2
            if annular < minAnnular {
                violations.append(DRCViolation(
                    severity: "error", checkId: "DRC_ANNULAR_RING",
                    description: String(format: "Pad %@ annular ring %.3fmm < %.3fmm", pad.ref, annular, minAnnular),
                    position: (Double(pad.pos.x), Double(pad.pos.y)),
                    value: annular, limit: minAnnular
                ))
            }
        }
        return violations
    }

    // MARK: - Check 5: Copper Spacing

    /// Copper items for spacing check.
    enum CopperItem {
        case segment(LineSegment, width: Double, net: String, layer: String)
        case pad(Rect, net: String, layer: String, fpRef: String)
        case via(GeomCircle, net: String, layer: String)
    }

    static func checkCopperSpacing(
        items: [CopperItem],
        minClearance: Double = DEFAULT_MIN_CLEARANCE
    ) -> [DRCViolation] {
        var violations: [DRCViolation] = []

        // Convert to comparable geometries with metadata
        struct ItemGeom {
            let center: CGPoint
            let net: String
            let layer: String
            let type: String
            let distance: (CGPoint) -> Double  // distance from a point
        }

        var geoms: [ItemGeom] = []
        for item in items {
            switch item {
            case .segment(let seg, let width, let net, let layer):
                let mid = CGPoint((seg.start.x + seg.end.x) / 2, (seg.start.y + seg.end.y) / 2)
                geoms.append(ItemGeom(center: mid, net: net, layer: layer, type: "segment") { pt in
                    max(0, seg.distance(to: pt) - width / 2)
                })
            case .pad(let rect, let net, let layer, _):
                geoms.append(ItemGeom(center: rect.center, net: net, layer: layer, type: "pad") { pt in
                    rect.distance(to: Rect(pt.x, pt.y, 0, 0))
                })
            case .via(let circle, let net, let layer):
                geoms.append(ItemGeom(center: circle.center, net: net, layer: layer, type: "via") { pt in
                    max(0, circle.center.distance(to: pt) - circle.radius)
                })
            }
        }

        // Phase 232: Use SpatialHash for O(n log n) instead of O(n²)
        var spatial = SpatialHash<(Int, ItemGeom)>(cellSize: minClearance * 4) { _, geom in
            (geom.center.x, geom.center.y)
        }
        for (i, geom) in geoms.enumerated() {
            spatial.insert((i, geom))
        }

        for (i, a) in geoms.enumerated() {
            // Query nearby items only
            let nearby = spatial.query(near: a.center.x, a.center.y, radius: minClearance * 4)
            for (j, b) in nearby {
                if j <= i { continue }
                if !a.net.isEmpty && a.net == b.net { continue }
                if a.net.isEmpty && b.net.isEmpty { continue }
                if !a.layer.isEmpty && !b.layer.isEmpty && a.layer != b.layer { continue }

                let centerDist = a.center.distance(to: b.center)
                if centerDist == 0 { continue }
                let distA = a.distance(b.center)
                let distB = b.distance(a.center)
                let dist = min(distA, distB)

                if dist < minClearance {
                    violations.append(DRCViolation(
                        severity: "error", checkId: "DRC_COPPER_CLEARANCE",
                        description: String(format: "Copper clearance: %@-%@ %.3fmm < %.3fmm",
                                           a.type, b.type, dist, minClearance),
                        layer: a.layer,
                        position: (Double((a.center.x + b.center.x) / 2), Double((a.center.y + b.center.y) / 2)),
                        value: dist, limit: minClearance
                    ))
                }
            }
        }
        return violations
    }
}
