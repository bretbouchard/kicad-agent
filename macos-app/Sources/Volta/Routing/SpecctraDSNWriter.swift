//
//  SpecctraDSNWriter.swift
//  Volta
//
//  Phase 253 Task 2 — Specctra DSN Writer
//
//  Pure-Swift Specctra DSN file generator. Converts a PCBBoard
//  (parsed from .kicad_pcb) into a DSN text that Freerouting can
//  consume. Ports the algorithm from
//  src/kicad_agent/routing/dsn_generator.py@fe68b91 (last verified
//  working at 888 LOC, end-to-end-tested on 48 footprints / 57 nets
//  / 76 segments).
//
//  Coordinate transform: KiCad mm ×1000 → DSN um. Exact integer math
//  (no floats in the transform).
//
//  Section order (must match Freerouting 2.2.4's Specctra parser):
//    1. (parser ...)  — host info
//    2. (resolution um 10)
//    3. (unit um)
//    4. (structure ...) — layers + boundary + (control snap_angle)
//    5. (placement ...) — grouped by footprint name
//    6. (library ...) — via padstack + image per package + per-class padstacks
//    7. (network ...) — (class ...) + (net NAME (pins ...))
//    8. (wiring ...)  — emitted only when board.segments is non-empty
//
//  ponytail: the writer is purely functional (board → string) with no
//  global state. The single rounding point (MM_TO_UM) is a static
//  constant — verified exact in SpecctraDSNWriterTests. No side effects,
//  no FileManager IO, no shell-outs. Tests are pure Swift.
//

import Foundation
import VoltaPCBCore

// MARK: - SnapAngle

/// Specctra trace angle mode (T-99-01-04 mitigation). Invalid values
/// throw at construction — no string injection.
public enum SnapAngle: String, Sendable, CaseIterable {
    /// No angle constraint (default — Freerouting picks the most efficient).
    case none
    /// 45° angle mode (M-shorter for production-quality routing).
    case fortyFive = "fortyfive_degree"
    /// 90° angle mode (orthogonal only).
    case ninetyDegree = "ninety_degree"
}

// MARK: - SpecctraDSNWriter

/// Specctra DSN file generator. Stateless — `write(_:)` is pure and
/// reentrant. Configurable via init defaults so callers can override
/// padstack sizes, wire widths, clearances, and snap angle without
/// subclassing.
public struct SpecctraDSNWriter: Sendable {

    // MARK: - Constants

    /// Coordinate transform: KiCad stores dimensions in millimeters;
    /// Specctra DSN uses micrometers. 1mm = 1000um exactly.
    static let MM_TO_UM: Double = 1000.0

    /// Default via padstack name (THT — covers front-to-back layers).
    static let VIA_PADSTACK_NAME = "Via[0-1]"

    // MARK: - Init parameters (all Sendable for cross-actor use)

    public let layers: [String]
    public let padViaDrillUm: Int
    public let padViaSizeUm: Int
    public let wireWidthUm: Int
    public let clearanceUm: Int
    public let snapAngle: SnapAngle

    // MARK: - Init

    public init(
        layers: [String] = ["F.Cu", "B.Cu"],
        padViaDrillUm: Int = 400,
        padViaSizeUm: Int = 800,
        wireWidthUm: Int = 250,
        clearanceUm: Int = 250,
        snapAngle: SnapAngle = .none
    ) {
        // Defense-in-depth (T-99-01-04 mitigation): validate snap_angle
        // here even though the enum already constrains it. Future raw-
        // string callers (e.g., from a YAML config) would otherwise
        // bypass the enum validation.
        let allCases = Set(SnapAngle.allCases.map { $0.rawValue })
        precondition(allCases.contains(snapAngle.rawValue), "Invalid snap angle: \(snapAngle.rawValue)")
        precondition(!layers.isEmpty, "layers must contain at least one copper layer")

        self.layers = layers
        self.padViaDrillUm = padViaDrillUm
        self.padViaSizeUm = padViaSizeUm
        self.wireWidthUm = wireWidthUm
        self.clearanceUm = clearanceUm
        self.snapAngle = snapAngle
    }

    // MARK: - Public API

    /// Generate Specctra DSN text for the given PCB.
    ///
    /// - Parameter board: Parsed PCB from PCBParser.
    /// - Returns: DSN file content as a string (trailing newline).
    /// Internal-only because `PCBBoard` is internal. The writer itself is
    /// public so FreeroutingProvider can call it; the parameter type
    /// pins access to this module.
    func write(_ board: PCBBoard) -> String {
        var lines: [String] = []
        let source = board.version.isEmpty ? "board" : board.version

        lines.append("(pcb \(source)")

        // parser
        emitParser(&lines)

        // resolution + unit
        lines.append("  (resolution um 10)")
        lines.append("  (unit um)")

        // structure
        emitStructure(board: board, into: &lines)

        // placement (only if footprints exist)
        if !board.footprints.isEmpty {
            emitPlacement(board: board, into: &lines)
        }

        // library
        emitLibrary(board: board, into: &lines)

        // network
        emitNetwork(board: board, into: &lines)

        // wiring — only when board has pre-routed segments
        if !board.segments.isEmpty {
            emitWiring(board: board, into: &lines)
        }

        lines.append(")")
        return lines.joined(separator: "\n") + "\n"
    }

    // MARK: - Header sections

    /// Emit (parser ...) block — host info for round-trip provenance.
    private func emitParser(_ lines: inout [String]) {
        lines.append("  (parser")
        lines.append("    (string_quote \")")
        lines.append("    (space_in_quoted_tokens on)")
        lines.append("    (host_cad \"VoltaPCB\")")
        lines.append("    (host_version \"10.0\")")
        lines.append("  )")
    }

    // MARK: - (structure ...)

    private func emitStructure(board: PCBBoard, into lines: inout [String]) {
        lines.append("  (structure")

        for (idx, layer) in layers.enumerated() {
            lines.append("    (layer \(layer)")
            lines.append("      (type signal)")
            lines.append("      (property")
            lines.append("        (index \(idx))")
            lines.append("      )")
            lines.append("    )")
        }

        // Boundary — prefer explicit Edge.Cuts-derived outline if present,
        // else compute from footprint bounding box + 5mm margin (matches
        // _compute_boundary_from_components in the Python reference).
        if let boundary = computeBoundary(board: board) {
            let (ux1, uy1, ux2, uy2) = boundary
            lines.append("    (boundary")
            lines.append("      (path pcb 0  \(ux1) \(uy1)  \(ux2) \(uy1)  \(ux2) \(uy2)  \(ux1) \(uy2)  \(ux1) \(uy1))")
            lines.append("    )")
        }

        // Control snap_angle — emit AFTER boundary per canonical DSN order.
        if snapAngle != .none {
            lines.append("    (control (snap_angle \(snapAngle.rawValue)))")
        }

        lines.append("  )")
    }

    /// Compute the board boundary. Tries Edge.Cuts graphic items first,
    /// falls back to footprint AABB + 5mm margin. Returns (x1, y1, x2, y2)
    /// in um, or nil if the board has no geometry.
    private func computeBoundary(board: PCBBoard) -> (Int, Int, Int, Int)? {
        let edgeCuts = board.graphicItems.filter { $0.layer == "Edge.Cuts" }
        var minX = Double.infinity
        var minY = Double.infinity
        var maxX = -Double.infinity
        var maxY = -Double.infinity

        for gr in edgeCuts {
            if let s = gr.start {
                minX = min(minX, s.x); minY = min(minY, s.y)
                maxX = max(maxX, s.x); maxY = max(maxY, s.y)
            }
            if let e = gr.end {
                minX = min(minX, e.x); minY = min(minY, e.y)
                maxX = max(maxX, e.x); maxY = max(maxY, e.y)
            }
        }

        if !minX.isFinite {
            // Fallback: compute from footprint positions + 5mm margin.
            if board.footprints.isEmpty { return nil }
            let xs = board.footprints.map { $0.position.x }
            let ys = board.footprints.map { $0.position.y }
            minX = (xs.min() ?? 0) - 5.0
            minY = (ys.min() ?? 0) - 5.0
            maxX = (xs.max() ?? 0) + 5.0
            maxY = (ys.max() ?? 0) + 5.0
        }

        let ux1 = Int((minX * Self.MM_TO_UM).rounded())
        let uy1 = Int((minY * Self.MM_TO_UM).rounded())
        let ux2 = Int((maxX * Self.MM_TO_UM).rounded())
        let uy2 = Int((maxY * Self.MM_TO_UM).rounded())
        return (ux1, uy1, ux2, uy2)
    }

    // MARK: - (placement ...)

    private func emitPlacement(board: PCBBoard, into lines: inout [String]) {
        lines.append("  (placement")

        // Group components by lib_id (footprint name).
        var fpGroups: [String: [PCBFootprint]] = [:]
        for fp in board.footprints {
            fpGroups[fp.libId, default: []].append(fp)
        }

        for fpName in fpGroups.keys.sorted() {
            let fps = fpGroups[fpName] ?? []
            lines.append("    (component \"\(escapeDSN(fpName))\"")
            for fp in fps {
                let xUm = Int((fp.position.x * Self.MM_TO_UM).rounded())
                let yUm = Int((fp.position.y * Self.MM_TO_UM).rounded())
                let angle = Int(fp.rotation.rounded())
                let side = fp.layer.hasPrefix("B.") ? "back" : "front"
                lines.append("      (place \(fp.reference) \(xUm) \(yUm) \(side) \(angle))")
            }
            lines.append("    )")
        }

        lines.append("  )")
    }

    // MARK: - (library ...)

    private func emitLibrary(board: PCBBoard, into lines: inout [String]) {
        lines.append("  (library")

        // R-4 deferred — only THT via padstack emitted (2-layer default).
        // Blind/buried padstacks land in Task 2b once a 4-layer fixture
        // exists (Bead volta-fnz: council-deferred,phase-253,deferred-to-task-2b).
        lines.append("    (padstack \"\(Self.VIA_PADSTACK_NAME)\"")
        for layer in layers {
            lines.append("      (shape (circle \(layer) \(padViaSizeUm)))")
        }
        lines.append("      (attach off)")
        lines.append("    )")

        // Per-class via padstacks — H-2 fix from the Python reference.
        for nc in board.netClasses where nc.viaDiameter > 0 {
            let viaName = "Via[\(nc.name)]"
            let sizeUm = Int((nc.viaDiameter * Self.MM_TO_UM).rounded())
            lines.append("    (padstack \"\(viaName)\"")
            for layer in layers {
                lines.append("      (shape (circle \(layer) \(sizeUm)))")
            }
            lines.append("      (attach off)")
            lines.append("    )")
        }

        // SMD padstacks — emit one per unique padstack key.
        let padstacks = buildSmdPadstacks(board: board)
        for psName in padstacks.keys.sorted() {
            guard let ps = padstacks[psName] else { continue }
            lines.append("    (padstack \"\(psName)\"")
            for (layer, sizeUm) in ps.shapes {
                lines.append("      (shape (circle \(layer) \(sizeUm)))")
            }
            lines.append("      (attach \(ps.attach))")
            lines.append("    )")
        }

        // Package images — R-1 outlines (courtyard preferred, pad-bbox fallback).
        let images = buildImages(board: board, padstacks: padstacks)
        for imgName in images.keys.sorted() {
            guard let img = images[imgName] else { continue }
            lines.append("    (image \"\(escapeDSN(imgName))\")")
            lines.append("      (side \(img.side))")
            if let outline = img.outline {
                let (ox1, oy1, ox2, oy2) = outline
                lines.append("      (outline (rect F.Cu \(ox1) \(oy1) \(ox2) \(oy2)))")
            }
            for pin in img.pins {
                // Rule 1 fix: empty pin number → "pad" placeholder so
                // Freerouting's parser sees exactly 4 tokens after `pin`.
                let rawName = pin.name.isEmpty ? "pad" : pin.name
                let safeName = escapeDSN(rawName)
                let px = Int((pin.x * Self.MM_TO_UM).rounded())
                let py = Int((pin.y * Self.MM_TO_UM).rounded())
                lines.append("      (pin \(pin.padstack) \"\(safeName)\" \(px) \(py))")
            }
            lines.append("    )")
        }

        lines.append("  )")
    }

    /// Build SMD padstacks keyed by `SMD_{layer}_{size}um` (Python analog).
    /// Returns {name: {shapes: [(layer, size_um)], attach: "on"|"off"}}.
    private func buildSmdPadstacks(board: PCBBoard) -> [String: (shapes: [(String, Int)], attach: String)] {
        var padstacks: [String: (shapes: [(String, Int)], attach: String)] = [:]
        for fp in board.footprints {
            let defaultLayer = fp.layer.hasPrefix("B.")
                ? (layers.last ?? "B.Cu")
                : (layers.first ?? "F.Cu")
            for pad in fp.pads {
                guard pad.drill == 0 else { continue } // SMD only (THT handled separately)
                let padLayerTokens = pad.layers.split(separator: " ").map(String.init)
                let resolvedLayer: String
                if let firstToken = padLayerTokens.first, layers.contains(firstToken) {
                    resolvedLayer = firstToken
                } else {
                    // Wildcard or non-copper layer (e.g., "F.Paste") → use side-appropriate copper.
                    resolvedLayer = defaultLayer
                }
                let sizeUm = Int((max(pad.size.w, pad.size.h) * Self.MM_TO_UM).rounded())
                let key = "SMD_\(resolvedLayer)_\(sizeUm)_um"
                if padstacks[key] == nil {
                    padstacks[key] = (shapes: [(resolvedLayer, sizeUm)], attach: "on")
                }
            }
        }
        return padstacks
    }

    /// Build images keyed by lib_id. Each image has side, optional outline,
    /// and pins (with padstack references).
    private func buildImages(
        board: PCBBoard,
        padstacks: [String: (shapes: [(String, Int)], attach: String)]
    ) -> [String: ImageData] {
        var images: [String: ImageData] = [:]

        for fp in board.footprints {
            let libId = fp.libId.isEmpty ? fp.reference : fp.libId
            let side = fp.layer.hasPrefix("B.") ? "back" : "front"
            if images[libId] == nil {
                images[libId] = ImageData(side: side, outline: nil, pins: [])
            }

            let defaultLayer = side == "back"
                ? (layers.last ?? "B.Cu")
                : (layers.first ?? "F.Cu")

            for pad in fp.pads {
                let sizeUm = Int((max(pad.size.w, pad.size.h) * Self.MM_TO_UM).rounded())
                let padstack: String
                if pad.drill > 0 {
                    let drillUm = Int((pad.drill * Self.MM_TO_UM).rounded())
                    padstack = "TH_\(sizeUm):\(drillUm)_um"
                } else {
                    let padLayerTokens = pad.layers.split(separator: " ").map(String.init)
                    let resolvedLayer: String
                    if let firstToken = padLayerTokens.first, layers.contains(firstToken) {
                        resolvedLayer = firstToken
                    } else {
                        resolvedLayer = defaultLayer
                    }
                    padstack = "SMD_\(resolvedLayer)_\(sizeUm)_um"
                }
                // Append pin refs using the local (untransformed) coords;
                // the (place ...) block in (placement ...) carries the footprint
                // rotation, so DSN wires them up together.
                var img = images[libId]!
                img.pins.append(PinData(padstack: padstack, name: pad.number, x: pad.position.x, y: pad.position.y))
                images[libId] = img
            }

            // R-1: outline — pad-bbox fallback (rotation-aware AABB of pads).
            // The PCB IR doesn't expose raw graphic_items on footprints
            // (those live in PCBGraphicItem on the board level), so we use
            // pad bounding box as the outline source. Future Task 2b may
            // add courtyard extraction.
            if images[libId]?.outline == nil, !fp.pads.isEmpty {
                let outline = computePadBBoxOutline(footprint: fp)
                if var img = images[libId] {
                    img.outline = outline
                    images[libId] = img
                }
            }
        }
        return images
    }

    /// Compute the outline (in um) of a footprint as the AABB of its pads,
    /// rotated by the footprint angle.
    private func computePadBBoxOutline(footprint: PCBFootprint) -> (Int, Int, Int, Int)? {
        guard !footprint.pads.isEmpty else { return nil }
        let angleRad = footprint.rotation * .pi / 180.0
        let cosA = cos(angleRad)
        let sinA = sin(angleRad)
        let fx = footprint.position.x
        let fy = footprint.position.y

        var minX = Double.infinity
        var minY = Double.infinity
        var maxX = -Double.infinity
        var maxY = -Double.infinity

        for pad in footprint.pads {
            let lx = pad.position.x
            let ly = pad.position.y
            let hw = pad.size.w / 2.0
            let hh = pad.size.h / 2.0
            // Four corners, rotated and translated.
            for (cx, cy) in [(lx - hw, ly - hh), (lx + hw, ly - hh), (lx - hw, ly + hh), (lx + hw, ly + hh)] {
                let wx = fx + cx * cosA - cy * sinA
                let wy = fy + cx * sinA + cy * cosA
                minX = min(minX, wx); minY = min(minY, wy)
                maxX = max(maxX, wx); maxY = max(maxY, wy)
            }
        }

        guard minX.isFinite else { return nil }
        return (
            Int((minX * Self.MM_TO_UM).rounded()),
            Int((minY * Self.MM_TO_UM).rounded()),
            Int((maxX * Self.MM_TO_UM).rounded()),
            Int((maxY * Self.MM_TO_UM).rounded())
        )
    }

    // MARK: - (network ...)

    private func emitNetwork(board: PCBBoard, into lines: inout [String]) {
        lines.append("  (network")

        // Per-class rules (R-2) — each named net class emits its own
        // (class NAME ...) with width, clearance, and via reference.
        for nc in board.netClasses {
            // Net class fields are in mm (Double), wire/clearance um are
            // Int. Convert: width_um = nc.trackWidth_mm * 1000.
            let widthUm = nc.trackWidth > 0
                ? Int((nc.trackWidth * Self.MM_TO_UM).rounded())
                : wireWidthUm
            let clearanceUmLocal = nc.clearance > 0
                ? Int((nc.clearance * Self.MM_TO_UM).rounded())
                : clearanceUm
            let viaRef: String = nc.viaDiameter > 0 ? "Via[\(nc.name)]" : Self.VIA_PADSTACK_NAME
            let members = nc.nets.joined(separator: " ")
            lines.append("    (class \"\(escapeDSN(nc.name))\" \(members)")
            lines.append("      (circuit")
            lines.append("        (use_layer \(layers.joined(separator: " ")))")
            lines.append("        (use_via \"\(viaRef)\")")
            lines.append("      )")
            lines.append("      (rule")
            lines.append("        (width \(widthUm))")
            lines.append("        (clearance \(clearanceUmLocal))")
            lines.append("      )")
            lines.append("    )")
        }

        // Default class for nets not in any named class.
        let netsInNamedClasses = Set(board.netClasses.flatMap { $0.nets })
        let allNets = collectNetNames(board: board)
        let defaultNets = allNets.subtracting(netsInNamedClasses).sorted()
        if defaultNets.isEmpty {
            lines.append("    (class default \"\")")
        } else {
            let defaultMembers = defaultNets.joined(separator: " ")
            lines.append("    (class default \"\" \(defaultMembers))")
        }
        lines.append("      (circuit")
        lines.append("        (use_layer \(layers.joined(separator: " ")))")
        lines.append("        (use_via \"\(Self.VIA_PADSTACK_NAME)\")")
        lines.append("      )")
        lines.append("      (rule")
        lines.append("        (width \(wireWidthUm))")
        lines.append("        (clearance \(clearanceUm))")
        lines.append("      )")
        lines.append("    )")

        // Per-net pin lists — Bead #28 sanitization replaces
        // KiCad 10's `{slash}` escape with `_` since Specctra parsers
        // reject non-ANSI chars in net names.
        let netPins = collectNetPins(board: board)
        for netName in netPins.keys.sorted() {
            let pins = netPins[netName] ?? []
            if pins.isEmpty { continue }
            let safeName = sanitizeNetName(netName)
            let pinsStr = pins.joined(separator: " ")
            lines.append("    (net \"\(safeName)\"")
            lines.append("      (pins \(pinsStr))")
            lines.append("    )")
        }

        lines.append("  )")
    }

    /// Collect all unique net names from the board's pads.
    private func collectNetNames(board: PCBBoard) -> Set<String> {
        var names: Set<String> = []
        for fp in board.footprints {
            for pad in fp.pads where !pad.netName.isEmpty {
                names.insert(pad.netName)
            }
        }
        return names
    }

    /// Collect pin refs (REF-PAD) per net name.
    private func collectNetPins(board: PCBBoard) -> [String: [String]] {
        var nets: [String: [String]] = [:]
        for fp in board.footprints {
            let ref = fp.reference
            guard !ref.isEmpty else { continue }
            for pad in fp.pads where !pad.netName.isEmpty {
                let safePadNum = sanitizeNetName(pad.number)
                let pinRef = "\(ref)-\(safePadNum)"
                nets[pad.netName, default: []].append(pinRef)
            }
        }
        return nets
    }

    /// Bead #28 fix: replace KiCad 10's `{slash}` escape + bare braces with `_`.
    private func sanitizeNetName(_ name: String) -> String {
        var s = name
        s = s.replacingOccurrences(of: "{slash}", with: "_")
        s = s.replacingOccurrences(of: "{", with: "_")
        s = s.replacingOccurrences(of: "}", with: "_")
        return escapeDSN(s)
    }

    /// Specctra DSN doubled-quote escaping per Council WR-03. Pin names
    /// containing `"` are escaped as `""` (the canonical DSN string escape).
    private func escapeDSN(_ s: String) -> String {
        s.replacingOccurrences(of: "\"", with: "\"\"")
    }

    // MARK: - (wiring ...)

    private func emitWiring(board: PCBBoard, into lines: inout [String]) {
        lines.append("  (wiring")

        // Convert each PCB segment → (wire ...) with (type fix).
        // Coordinate transform: mm ×1000 → um, exact.
        for seg in board.segments {
            let sxUm = Int((seg.start.x * Self.MM_TO_UM).rounded())
            let syUm = Int((seg.start.y * Self.MM_TO_UM).rounded())
            let exUm = Int((seg.end.x * Self.MM_TO_UM).rounded())
            let eyUm = Int((seg.end.y * Self.MM_TO_UM).rounded())
            let widthUm = Int((seg.width * Self.MM_TO_UM).rounded())
            let safeNet = sanitizeNetName(seg.netName)
            lines.append("    (wire (path \(seg.layer) \(widthUm) \(sxUm) \(syUm) \(exUm) \(eyUm)) (net \"\(safeNet)\") (type fix))")
        }

        // Convert each PCB via → (via ...) with (type fix).
        for via in board.vias {
            let xUm = Int((via.position.x * Self.MM_TO_UM).rounded())
            let yUm = Int((via.position.y * Self.MM_TO_UM).rounded())
            let safeNet = sanitizeNetName(via.netName)
            lines.append("    (via \(Self.VIA_PADSTACK_NAME) \(xUm) \(yUm) (net \"\(safeNet)\") (type fix))")
        }

        lines.append("  )")
    }

    // MARK: - Private helper structs (file-private)

    /// Image data computed during library emission.
    private struct ImageData {
        var side: String
        var outline: (Int, Int, Int, Int)?
        var pins: [PinData]
    }

    /// Pin data: padstack reference + pin name + local footprint-relative position.
    private struct PinData {
        var padstack: String
        var name: String
        var x: Double
        var y: Double
    }
}
