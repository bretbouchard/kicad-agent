//
//  PCBParser.swift
//  Phase 223 — Swift PCB Parser
//
//  Parses .kicad_pcb files into typed Swift structures using the
//  SExpression parser from Phase 221.
//
//  Ports: pcb_native_parser.py + pcb_native_types.py
//  ponytail: uses SExpr tree, ~300 LOC for the types + parser.
//

import Foundation

// MARK: - PCB IR Types

struct PCBBoard: Sendable {
    let version: String
    let footprints: [PCBFootprint]
    let segments: [PCBSegment]
    let vias: [PCBVia]
    let nets: [PCBNet]
    let netClasses: [PCBNetClass]
    let graphicItems: [PCBGraphicItem]
    let layers: [String]

    var padCount: Int { footprints.reduce(0) { $0 + $1.pads.count } }
}

struct PCBFootprint: Sendable {
    let reference: String
    let libId: String
    let layer: String
    let position: (x: Double, y: Double)
    let rotation: Double
    let pads: [PCBPad]
}

struct PCBPad: Sendable {
    let number: String
    let type: String  // thruhole, smd, npth, connect
    let shape: String // circle, rect, oval, etc
    let position: (x: Double, y: Double)  // relative to footprint
    let size: (w: Double, h: Double)
    let layers: String
    let netName: String
    let drill: Double
}

struct PCBSegment: Sendable {
    let start: (x: Double, y: Double)
    let end: (x: Double, y: Double)
    let width: Double
    let layer: String
    let netName: String
}

struct PCBVia: Sendable {
    let position: (x: Double, y: Double)
    let size: Double
    let drill: Double
    let layers: String
    let netName: String
}

struct PCBNet: Sendable {
    let number: Int
    let name: String
}

struct PCBNetClass: Sendable {
    let name: String
    let trackWidth: Double
    let clearance: Double
    let viaDiameter: Double
    let viaDrill: Double
    let nets: [String]
}

struct PCBGraphicItem: Sendable {
    let type: String  // gr_line, gr_arc, etc
    let layer: String
    let start: (x: Double, y: Double)?
    let end: (x: Double, y: Double)?
}

// MARK: - Parser

struct PCBParser {
    static func parse(_ url: URL) throws -> PCBBoard {
        let sexpr = try SExpr.parse(fileURL: url)
        return parseBoard(from: sexpr)
    }

    static func parse(_ text: String) throws -> PCBBoard {
        let sexpr = try SExpr.parse(text)
        return parseBoard(from: sexpr)
    }

    private static func parseBoard(from root: SExpr) -> PCBBoard {
        let version = root.find("version")?.childString(0) ?? "unknown"

        // Parse layers
        let layersNode = root.find("layers")
        let layers = layersNode?.children.compactMap { $0.head } ?? []

        // Parse nets
        var netNames: [Int: String] = [:]
        for netNode in root.findAll("net") {
            let num = Int(netNode.childString(0) ?? "0") ?? 0
            let name = netNode.childString(1) ?? ""
            netNames[num] = name
        }
        let nets = netNames.map { PCBNet(number: $0.key, name: $0.value) }

        // Parse net classes
        let netClasses = root.findAll("net_class").map { parseNetClass($0) }

        // Build net number → name lookup
        let netLookup = Dictionary(uniqueKeysWithValues: netNames.map { ($0.key, $0.value) })

        // Parse footprints
        let footprints = root.findAll("footprint").map { parseFootprint($0, netLookup: netLookup) }

        // Parse segments (tracks)
        let segments = root.findAll("segment").map { parseSegment($0, netLookup: netLookup) }

        // Parse vias
        let vias = root.findAll("via").map { parseVia($0, netLookup: netLookup) }

        // Parse graphic items
        let graphicItems = root.children.compactMap { node -> PCBGraphicItem? in
            let h = node.head ?? ""
            if h.hasPrefix("gr_") {
                let layer = node.find("layer")?.childString(0) ?? ""
                let start = node.find("start").map { ($0.childDouble(0) ?? 0, $0.childDouble(1) ?? 0) }
                let end = node.find("end").map { ($0.childDouble(0) ?? 0, $0.childDouble(1) ?? 0) }
                return PCBGraphicItem(type: h, layer: layer, start: start, end: end)
            }
            return nil
        }

        return PCBBoard(
            version: version,
            footprints: footprints,
            segments: segments,
            vias: vias,
            nets: nets,
            netClasses: netClasses,
            graphicItems: graphicItems,
            layers: layers
        )
    }

    private static func parseNetClass(_ node: SExpr) -> PCBNetClass {
        let name = node.childString(0) ?? "Default"
        let trackWidth = node.find("track_width")?.childDouble(0) ?? 0.25
        let clearance = node.find("clearance")?.childDouble(0) ?? 0.127
        let viaDiameter = node.find("via_dia")?.childDouble(0) ?? 0.6
        let viaDrill = node.find("via_drill")?.childDouble(0) ?? 0.3

        // add_net entries
        let nets = node.findAll("add_net").compactMap { $0.childString(0) }

        return PCBNetClass(
            name: name, trackWidth: trackWidth, clearance: clearance,
            viaDiameter: viaDiameter, viaDrill: viaDrill, nets: nets
        )
    }

    private static func parseFootprint(_ node: SExpr, netLookup: [Int: String]) -> PCBFootprint {
        // (footprint "lib:fp" (layer "F.Cu") (at X Y R) (property "Reference" "R1" ...) (pad ...))
        let libId = node.childString(0) ?? ""
        let layer = node.find("layer")?.childString(0) ?? "F.Cu"
        let atNode = node.find("at")
        let x = atNode?.childDouble(0) ?? 0
        let y = atNode?.childDouble(1) ?? 0
        let rot = atNode?.childDouble(2) ?? 0

        // Find Reference property
        var ref = "?"
        for child in node.children {
            if child.head == "property" && child.childString(0) == "Reference" {
                ref = child.childString(1) ?? "?"
            }
        }

        // Parse pads
        let pads = node.findAll("pad").map { parsePad($0, netLookup: netLookup) }

        return PCBFootprint(
            reference: ref, libId: libId, layer: layer,
            position: (x, y), rotation: rot, pads: pads
        )
    }

    private static func parsePad(_ node: SExpr, netLookup: [Int: String]) -> PCBPad {
        // (pad "1" thru_hole circle (at X Y) (size W H) (drill D) (layers "...") (net N "name"))
        let number = node.childString(0) ?? ""
        let type = node.childString(1) ?? "thru_hole"
        let shape = node.childString(2) ?? "circle"

        let atNode = node.find("at")
        let px = atNode?.childDouble(0) ?? 0
        let py = atNode?.childDouble(1) ?? 0

        let sizeNode = node.find("size")
        let sw = sizeNode?.childDouble(0) ?? 0.6
        let sh = sizeNode?.childDouble(1) ?? 0.6

        let drill = node.find("drill")?.childDouble(0) ?? 0
        let layers = node.find("layers")?.childString(0) ?? "*.Cu"

        let netNode = node.find("net")
        let netNum = Int(netNode?.childString(0) ?? "0") ?? 0
        let netName = netLookup[netNum] ?? netNode?.childString(1) ?? ""

        return PCBPad(
            number: number, type: type, shape: shape,
            position: (px, py), size: (sw, sh),
            layers: layers, netName: netName, drill: drill
        )
    }

    private static func parseSegment(_ node: SExpr, netLookup: [Int: String]) -> PCBSegment {
        let startNode = node.find("start")
        let endNode = node.find("end")
        let widthNode = node.find("width")
        let layer = node.find("layer")?.childString(0) ?? "F.Cu"

        let netNode = node.find("net")
        let netNum = Int(netNode?.childString(0) ?? "0") ?? 0
        let netName = netLookup[netNum] ?? ""

        return PCBSegment(
            start: (startNode?.childDouble(0) ?? 0, startNode?.childDouble(1) ?? 0),
            end: (endNode?.childDouble(0) ?? 0, endNode?.childDouble(1) ?? 0),
            width: widthNode?.childDouble(0) ?? 0.2,
            layer: layer, netName: netName
        )
    }

    private static func parseVia(_ node: SExpr, netLookup: [Int: String]) -> PCBVia {
        let atNode = node.find("at")
        let sizeNode = node.find("size")
        let drillNode = node.find("drill")
        let layers = node.find("layers")?.childString(0) ?? "F.Cu"

        let netNode = node.find("net")
        let netNum = Int(netNode?.childString(0) ?? "0") ?? 0
        let netName = netLookup[netNum] ?? ""

        return PCBVia(
            position: (atNode?.childDouble(0) ?? 0, atNode?.childDouble(1) ?? 0),
            size: sizeNode?.childDouble(0) ?? 0.6,
            drill: drillNode?.childDouble(0) ?? 0.3,
            layers: layers, netName: netName
        )
    }
}
