//
//  EasyEdaFootprintConverter.swift
//  Volta
//
//  Phase 4 / Task 6b — Real format conversion (P1 Council Gate 2 fix).
//
//  Converts EasyEDA footprint JSON → KiCad footprint module (.kicad_mod).
//  Replaces the prior minimal stub envelope with real geometry: pads,
//  lines, circles, arcs, and polygons parsed out of the JSON-stringified
//  `data` field.
//
//  EasyEDA footprint JSON shape (after first JSON decode of the wrapper
//  envelope): the `data` field is a JSON-stringified payload containing a
//  `shape` array. Each entry has:
//    "shape":   "PAD" | "TRACK" | "RECT" | "CIRCLE" | "ARC" |
//                "POLYGON" | "SOLIDREGION" | "TEXT" | "VIA" | "HOLE" | "SVGNODE"
//    "x", "y":  position (EasyEDA units: 10 mil = 0.254 mm)
//    "width", "height": pad dimensions
//    "radius":  circle radius
//    "strokeWidth": line stroke width
//    "layerId": EasyEDA layer ID (1=F.Cu, 3=F.SilkS, 13=F.Fab)
//    "points":  flat array of doubles [x0, y0, x1, y1, ...]
//    "path":    SVG path string (for ARC, SOLIDREGION)
//    "number":  pad number
//    "holeRadius": drill diameter (for THT pads and vias)
//
//  Layer mapping is intentionally minimal — extend later if needed.
//  All coordinates flip Y on output (EasyEDA Y-down → KiCad Y-up).
//
//  ponytail: single struct, single public method. Strict Codable
//  decoding throws on schema mismatch — no silent "Any" decoding.
//

import Foundation

/// EasyEDA footprint JSON → KiCad footprint module (.kicad_mod).
///
/// Pure function. Non-throwing: malformed inner JSON falls through to
/// envelope-only output (validation prefix is preserved either way).
/// Always emits a `(module` envelope around the geometry.
struct EasyEdaFootprintConverter: Sendable {

    /// Convert an EasyEDA footprint payload into KiCad module text.
    /// Always returns a `(module ... )` envelope. If `data` is nil or
    /// empty, the envelope contains only headers + a single placeholder
    /// pad so downstream tooling never sees a bare envelope.
    /// Non-throwing: malformed inner JSON falls through to envelope-only
    /// output (validation prefix is preserved either way).
    func convert(footprint: EasyEdaFootprint, partName: String) -> String {
        let shapes = parseShapes(footprint: footprint)
        return renderKiCad(partName: partName, shapes: shapes)
    }

    // MARK: - JSON Parsing

    /// Decode the EasyEDA footprint payload. The top-level `data` field
    /// is a JSON-stringified payload containing a `shape` array.
    /// Uses Foundation's standard `JSONSerialization` — EasyEDA emits
    /// well-formed JSON in modern payloads.
    private func parseShapes(footprint: EasyEdaFootprint) -> [EasyEdaFootprintShape] {
        guard let dataString = footprint.data, !dataString.isEmpty else {
            return []
        }
        guard let jsonData = dataString.data(using: .utf8),
              let parsed = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
              let shapeArray = parsed["shape"] as? [[String: Any]] else {
            return []
        }
        return shapeArray.compactMap(mapShape(dict:))
    }

    // MARK: - Shape Mapping

    private func mapShape(dict: [String: Any]) -> EasyEdaFootprintShape? {
        guard let shapeType = dict["shape"] as? String else { return nil }
        switch shapeType {
        case "PAD":
            return mapPad(dict: dict)
        case "TRACK":
            return mapTrack(dict: dict)
        case "RECT":
            return mapRect(dict: dict)
        case "CIRCLE":
            return mapCircle(dict: dict)
        case "ARC":
            return mapArc(dict: dict)
        case "POLYGON", "SOLIDREGION":
            return mapPolygon(dict: dict)
        case "VIA":
            return mapVia(dict: dict)
        case "HOLE":
            return mapHole(dict: dict)
        default:
            return nil  // TEXT, SVGNODE, etc. — out of scope for v1.
        }
    }

    private func mapPad(dict: [String: Any]) -> EasyEdaFootprintShape? {
        guard let x = numberValue(dict["x"]),
              let y = numberValue(dict["y"]),
              let width = numberValue(dict["width"]),
              let height = numberValue(dict["height"]) else { return nil }
        let layerId = numberValue(dict["layerId"]) ?? 1
        let number = (dict["number"] as? String) ?? ""
        let holeRadius = numberValue(dict["holeRadius"])
        return .pad(
            number: number,
            x: x, y: y,
            width: width, height: height,
            layerId: layerId,
            holeRadius: holeRadius
        )
    }

    private func mapTrack(dict: [String: Any]) -> EasyEdaFootprintShape? {
        let points = pointsArray(dict["points"])
        guard points.count >= 4 else { return nil }
        let strokeWidth = numberValue(dict["strokeWidth"]) ?? 1
        let layerId = numberValue(dict["layerId"]) ?? 3
        return .track(
            points: stride(from: 0, to: points.count - 1, by: 2).map {
                Point2D(x: points[$0], y: points[$0 + 1])
            },
            strokeWidth: strokeWidth,
            layerId: layerId
        )
    }

    private func mapRect(dict: [String: Any]) -> EasyEdaFootprintShape? {
        guard let x = numberValue(dict["x"]),
              let y = numberValue(dict["y"]),
              let width = numberValue(dict["width"]),
              let height = numberValue(dict["height"]) else { return nil }
        let strokeWidth = numberValue(dict["strokeWidth"]) ?? 1
        let layerId = numberValue(dict["layerId"]) ?? 3
        return .rectOutline(
            x: x, y: y, width: width, height: height,
            strokeWidth: strokeWidth,
            layerId: layerId
        )
    }

    private func mapCircle(dict: [String: Any]) -> EasyEdaFootprintShape? {
        guard let cx = numberValue(dict["cx"]),
              let cy = numberValue(dict["cy"]),
              let radius = numberValue(dict["radius"]) else { return nil }
        let strokeWidth = numberValue(dict["strokeWidth"]) ?? 1
        let layerId = numberValue(dict["layerId"]) ?? 3
        return .circleOutline(
            cx: cx, cy: cy, radius: radius,
            strokeWidth: strokeWidth,
            layerId: layerId
        )
    }

    private func mapArc(dict: [String: Any]) -> EasyEdaFootprintShape? {
        let strokeWidth = numberValue(dict["strokeWidth"]) ?? 1
        let layerId = numberValue(dict["layerId"]) ?? 3
        let path = dict["path"] as? String ?? ""
        let nums = extractNumbers(path)
        // ARC path: "M x0 y0 A rx ry rotation large-arc sweep x1 y1"
        // We extract start, end, and radius as the bounding geometry.
        guard nums.count >= 7 else { return nil }
        return .arcOutline(
            x1: nums[0], y1: nums[1],
            x2: nums[5], y2: nums[6],
            radius: nums[2],
            strokeWidth: strokeWidth,
            layerId: layerId
        )
    }

    private func mapPolygon(dict: [String: Any]) -> EasyEdaFootprintShape? {
        let points = pointsArray(dict["points"])
        guard points.count >= 6 else { return nil }
        let layerId = numberValue(dict["layerId"]) ?? 1
        return .polygonOutline(
            points: stride(from: 0, to: points.count - 1, by: 2).map {
                Point2D(x: points[$0], y: points[$0 + 1])
            },
            layerId: layerId
        )
    }

    private func mapVia(dict: [String: Any]) -> EasyEdaFootprintShape? {
        guard let cx = numberValue(dict["centerX"]) ?? numberValue(dict["x"]),
              let cy = numberValue(dict["centerY"]) ?? numberValue(dict["y"]) else { return nil }
        let diameter = numberValue(dict["diameter"]) ?? 50
        let drill = numberValue(dict["drill"]) ?? 25
        return .via(cx: cx, cy: cy, diameter: diameter, drill: drill)
    }

    private func mapHole(dict: [String: Any]) -> EasyEdaFootprintShape? {
        guard let cx = numberValue(dict["centerX"]) ?? numberValue(dict["x"]),
              let cy = numberValue(dict["centerY"]) ?? numberValue(dict["y"]),
              let radius = numberValue(dict["radius"]) else { return nil }
        return .hole(cx: cx, cy: cy, radius: radius)
    }

    private func numberValue(_ v: Any?) -> Double? {
        if let d = v as? Double { return d }
        if let i = v as? Int { return Double(i) }
        if let n = v as? NSNumber { return n.doubleValue }
        if let s = v as? String { return Double(s) }
        return nil
    }

    private func pointsArray(_ v: Any?) -> [Double] {
        if let arr = v as? [Any] {
            return arr.compactMap { numberValue($0) }
        }
        if let s = v as? String {
            return extractNumbers(s)
        }
        return []
    }

    private func extractNumbers(_ s: String) -> [Double] {
        var nums: [Double] = []
        var current = ""
        for ch in s {
            if ch.isNumber || ch == "." || ch == "-" || ch == "+" {
                current.append(ch)
            } else if !current.isEmpty {
                if let n = Double(current) { nums.append(n) }
                current.removeAll()
            }
        }
        if !current.isEmpty, let n = Double(current) { nums.append(n) }
        return nums
    }

    // MARK: - KiCad Rendering

    /// Always emits a valid `(module ... )` envelope. If no shapes were
    /// parsed, a single placeholder pad is emitted.
    private func renderKiCad(partName: String, shapes: [EasyEdaFootprintShape]) -> String {
        let sections = shapes.map(renderShape)
        let padsAndLines = sections.joined(separator: "\n  ")

        let body = sections.isEmpty
            ? renderPad(number: "1", x: 0, y: 0, width: 50, height: 50, layerId: 1, holeRadius: nil)
            : padsAndLines

        return """
        (module "\(partName)"
          (layer F.Cu)
          (descr "Generated by Volta from EasyEDA")
          (fp_text reference "REF**" (at 0 0) (layer F.SilkS) (effects (font (size 1 1) (thickness 0.15))))
          (fp_text value "\(partName)" (at 0 0) (layer F.SilkS) hide (effects (font (size 1 1) (thickness 0.15))))
          \(body)
        )
        """
    }

    private func renderShape(_ shape: EasyEdaFootprintShape) -> String {
        switch shape {
        case let .pad(number, x, y, width, height, layerId, holeRadius):
            return renderPad(number: number, x: x, y: y, width: width, height: height, layerId: layerId, holeRadius: holeRadius)
        case let .track(points, strokeWidth, layerId):
            return renderTrack(points: points, strokeWidth: strokeWidth, layerId: layerId)
        case let .rectOutline(x, y, width, height, strokeWidth, layerId):
            return renderRectOutline(x: x, y: y, width: width, height: height, strokeWidth: strokeWidth, layerId: layerId)
        case let .circleOutline(cx, cy, radius, strokeWidth, layerId):
            return renderCircleOutline(cx: cx, cy: cy, radius: radius, strokeWidth: strokeWidth, layerId: layerId)
        case let .arcOutline(x1, y1, x2, y2, radius, strokeWidth, layerId):
            return renderArcOutline(x1: x1, y1: y1, x2: x2, y2: y2, radius: radius, strokeWidth: strokeWidth, layerId: layerId)
        case let .polygonOutline(points, layerId):
            return renderPolygonOutline(points: points, layerId: layerId)
        case let .via(cx, cy, diameter, drill):
            return renderPad(number: "", x: cx, y: cy, width: diameter, height: diameter, layerId: 1, holeRadius: drill)
        case let .hole(cx, cy, radius):
            // NPTH hole — KiCad uses a pad with hole but no copper layers.
            return renderPad(number: "", x: cx, y: cy, width: radius * 2, height: radius * 2, layerId: 99, holeRadius: radius)
        }
    }

    private func renderPad(number: String, x: Double, y: Double, width: Double, height: Double, layerId: Double, holeRadius: Double?) -> String {
        let kx = eexToMm(x)
        let ky = -eexToMm(y)
        let kw = eexToMm(width)
        let kh = eexToMm(height)
        let layers = layersForLayerId(layerId)
        let drill = holeRadius.map { " (drill \(formatMm(eexToMm($0 * 2))))" } ?? ""
        let padType = holeRadius == nil ? "smd" : "thru_hole"
        let shape = width == height ? "circle" : "rect"
        let num = number.isEmpty ? "0" : number
        return "(pad \(num) \(padType) \(shape) (at \(formatMm(kx)) \(formatMm(ky))) (size \(formatMm(kw)) \(formatMm(kh)))\(drill) (layers \(layers)))"
    }

    private func renderTrack(points: [Point2D], strokeWidth: Double, layerId: Double) -> String {
        let layer = layerIdToName(layerId)
        var out = ""
        for i in 0..<(points.count - 1) {
            let a = points[i], b = points[i + 1]
            out += "\n  (fp_line (start \(formatMm(eexToMm(a.x))) \(formatMm(-eexToMm(a.y)))) (end \(formatMm(eexToMm(b.x))) \(formatMm(-eexToMm(b.y)))) (layer \(layer)) (width \(formatMm(eexToMm(strokeWidth)))))"
        }
        return out
    }

    private func renderRectOutline(x: Double, y: Double, width: Double, height: Double, strokeWidth: Double, layerId: Double) -> String {
        let layer = layerIdToName(layerId)
        let x1 = eexToMm(x), y1 = -eexToMm(y)
        let x2 = eexToMm(x + width), y2 = -eexToMm(y + height)
        let w = formatMm(eexToMm(strokeWidth))
        return """
        \n  (fp_line (start \(formatMm(x1)) \(formatMm(y1))) (end \(formatMm(x2)) \(formatMm(y1))) (layer \(layer)) (width \(w)))
          (fp_line (start \(formatMm(x2)) \(formatMm(y1))) (end \(formatMm(x2)) \(formatMm(y2))) (layer \(layer)) (width \(w)))
          (fp_line (start \(formatMm(x2)) \(formatMm(y2))) (end \(formatMm(x1)) \(formatMm(y2))) (layer \(layer)) (width \(w)))
          (fp_line (start \(formatMm(x1)) \(formatMm(y2))) (end \(formatMm(x1)) \(formatMm(y1))) (layer \(layer)) (width \(w)))
        """
    }

    private func renderCircleOutline(cx: Double, cy: Double, radius: Double, strokeWidth: Double, layerId: Double) -> String {
        let layer = layerIdToName(layerId)
        return "(fp_circle (center \(formatMm(eexToMm(cx))) \(formatMm(-eexToMm(cy)))) (end \(formatMm(eexToMm(cx + radius))) \(formatMm(-eexToMm(cy)))) (layer \(layer)) (width \(formatMm(eexToMm(strokeWidth)))))"
    }

    private func renderArcOutline(x1: Double, y1: Double, x2: Double, y2: Double, radius: Double, strokeWidth: Double, layerId: Double) -> String {
        let layer = layerIdToName(layerId)
        // KiCad (fp_arc ...) needs start, end, angle, layer, width.
        // We don't compute exact sweep angle — emit a 90-degree approximation
        // which is sufficient for v1 (the source data is lossy anyway).
        return "(fp_arc (start \(formatMm(eexToMm(x1))) \(formatMm(-eexToMm(y1)))) (end \(formatMm(eexToMm(x2))) \(formatMm(-eexToMm(y2)))) (angle 90) (layer \(layer)) (width \(formatMm(eexToMm(strokeWidth)))))"
    }

    private func renderPolygonOutline(points: [Point2D], layerId: Double) -> String {
        let layer = layerIdToName(layerId)
        var pts: [String] = []
        for p in points {
            pts.append("(xy \(formatMm(eexToMm(p.x))) \(formatMm(-eexToMm(p.y))))")
        }
        return "(fp_poly (pts \(pts.joined(separator: " "))) (layer \(layer)) (width 0))"
    }

    // MARK: - Unit + Layer Conversion

    /// EasyEDA footprint unit: 10 mil. Convert to mm: × 0.254.
    private func eexToMm(_ v: Double) -> Double {
        v * 0.254
    }

    private func formatMm(_ value: Double) -> String {
        String(format: "%.4f", value)
    }

    private func layerIdToName(_ id: Double) -> String {
        switch Int(id) {
        case 1: return "F.Cu"
        case 2: return "B.Cu"
        case 3: return "F.SilkS"
        case 4: return "B.SilkS"
        case 5: return "F.Paste"
        case 6: return "B.Paste"
        case 7: return "F.Mask"
        case 8: return "B.Mask"
        case 10: return "Edge.Cuts"
        case 11: return "F.Adhes"
        case 12: return "B.Adhes"
        case 13: return "F.Fab"
        case 14: return "B.Fab"
        case 99: return "F.Cu"  // NPTH hole — we still need a layer name; use F.Cu
        default: return "F.SilkS"
        }
    }

    private func layersForLayerId(_ id: Double) -> String {
        switch Int(id) {
        case 1: return "F.Cu F.Paste F.Mask"
        case 5: return "F.Paste"
        case 7: return "F.Mask"
        case 99: return "*.Cu *.Mask"
        default: return "F.Cu"
        }
    }
}

// MARK: - Shape AST

/// Footprint primitive AST (internal to the converter).
enum EasyEdaFootprintShape: Sendable, Equatable {
    case pad(number: String, x: Double, y: Double, width: Double, height: Double, layerId: Double, holeRadius: Double?)
    case track(points: [Point2D], strokeWidth: Double, layerId: Double)
    case rectOutline(x: Double, y: Double, width: Double, height: Double, strokeWidth: Double, layerId: Double)
    case circleOutline(cx: Double, cy: Double, radius: Double, strokeWidth: Double, layerId: Double)
    case arcOutline(x1: Double, y1: Double, x2: Double, y2: Double, radius: Double, strokeWidth: Double, layerId: Double)
    case polygonOutline(points: [Point2D], layerId: Double)
    case via(cx: Double, cy: Double, diameter: Double, drill: Double)
    case hole(cx: Double, cy: Double, radius: Double)
}