//
//  SchematicParser.swift
//  Phase 221 — Schematic IR
//
//  Parses .kicad_sch files into typed Swift structures.
//  Extracts: symbols, pins (with electrical types), wires, labels,
//  no-connects, and lib_symbols.
//

import Foundation

// MARK: - Schematic IR Types

struct PinInfo: Identifiable, Sendable {
    let id = UUID()
    let ref: String
    let pinNumber: String
    let pinName: String
    let position: (x: Double, y: Double)
    let electricalType: String
}

struct WireInfo: Sendable {
    let start: (x: Double, y: Double)
    let end: (x: Double, y: Double)
}

struct LabelInfo: Sendable {
    let name: String
    let position: (x: Double, y: Double)
}

struct SchematicIR: Sendable {
    let version: String
    let symbols: [SymbolInstance]
    let libSymbols: [LibSymbol]
    let wires: [WireInfo]
    let labels: [LabelInfo]
    let noConnects: [(x: Double, y: Double)]

    var pinCount: Int {
        libSymbols.reduce(0) { $0 + $1.pins.count }
    }
}

struct SymbolInstance: Sendable {
    let reference: String
    let libId: String
    let position: (x: Double, y: Double)
    let mirror: String?
}

struct LibSymbol: Sendable {
    let libId: String
    let pins: [LibPin]
}

struct LibPin: Sendable {
    let number: String
    let name: String
    let electricalType: String
    let position: (x: Double, y: Double)
}

// MARK: - Parser

struct SchematicParser {
    static func parse(_ url: URL) throws -> SchematicIR {
        let sexpr = try SExpr.parse(fileURL: url)
        return try parseSchematic(from: sexpr)
    }

    static func parse(_ text: String) throws -> SchematicIR {
        let sexpr = try SExpr.parse(text)
        return try parseSchematic(from: sexpr)
    }

    private static func parseSchematic(from root: SExpr) throws -> SchematicIR {
        // Root: (kicad_sch (version ...) (generator ...) ...)
        let version = root.find("version")?.childString(0) ?? "unknown"

        // Parse lib_symbols
        let libSymbolsNode = root.find("lib_symbols")
        let libSymbols = (libSymbolsNode?.children ?? []).map { parseLibSymbol($0) }

        // Parse symbol instances (placed components on the schematic)
        let symbolNodes = root.findAll("symbol")
        let symbols = symbolNodes.map { parseSymbolInstance($0) }

        // Parse wires
        let wireNodes = root.findAll("wire")
        let wires = wireNodes.compactMap { parseWire($0) }

        // Parse labels (global labels + local labels + hierarchical labels)
        var labels: [LabelInfo] = []
        for node in root.findAll("label") + root.findAll("global_label") + root.findAll("hierarchical_label") {
            if let label = parseLabel(node) {
                labels.append(label)
            }
        }

        // Parse no_connects
        let ncNodes = root.findAll("no_connect")
        let noConnects = ncNodes.compactMap { node -> (Double, Double)? in
            guard let at = node.find("at") else { return nil }
            let x = at.childDouble(0) ?? 0
            let y = at.childDouble(1) ?? 0
            return (x, y)
        }

        return SchematicIR(
            version: version,
            symbols: symbols,
            libSymbols: libSymbols,
            wires: wires,
            labels: labels,
            noConnects: noConnects
        )
    }

    private static func parseLibSymbol(_ node: SExpr) -> LibSymbol {
        // (symbol "Device:C" (pin ...) ...)
        let libId = node.childString(0) ?? ""
        var pins: [LibPin] = []

        // Symbols can have sub-symbols (units). Collect all pins recursively.
        func collectPins(_ expr: SExpr) {
            for child in expr.children {
                if child.head == "pin" {
                    // (pin <type> <shape> (at X Y R) (length L) (name "N" ...) (number "1" ...))
                    let type = child.childString(0) ?? "passive"
                    let nameNode = child.find("name")
                    let numberNode = child.find("number")
                    let atNode = child.find("at")

                    let name = nameNode?.childString(0) ?? ""
                    let number = numberNode?.childString(0) ?? ""
                    let px = atNode?.childDouble(0) ?? 0
                    let py = atNode?.childDouble(1) ?? 0

                    pins.append(LibPin(number: number, name: name,
                                      electricalType: type, position: (px, py)))
                }
                // Recurse into sub-symbols
                if child.head == "symbol" {
                    collectPins(child)
                }
            }
        }
        collectPins(node)

        return LibSymbol(libId: libId, pins: pins)
    }

    private static func parseSymbolInstance(_ node: SExpr) -> SymbolInstance {
        // (symbol (at X Y R) (property "Reference" "R1" ...) (lib_id "Device:R") ...)
        let atNode = node.find("at")
        let x = atNode?.childDouble(0) ?? 0
        let y = atNode?.childDouble(1) ?? 0

        // Find Reference property
        var ref = "?"
        var libId = ""
        for child in node.children {
            if child.head == "property" {
                let propName = child.childString(0) ?? ""
                let propValue = child.childString(1) ?? ""
                if propName == "Reference" { ref = propValue }
            }
        }

        // lib_id is usually a direct child value
        libId = node.find("lib_id")?.childString(0) ?? ""

        let mirror = node.find("mirror")?.childString(0)

        return SymbolInstance(reference: ref, libId: libId,
                             position: (x, y), mirror: mirror)
    }

    private static func parseWire(_ node: SExpr) -> WireInfo? {
        // (wire (pts (xy X1 Y1) (xy X2 Y2)) ...)
        guard let pts = node.find("pts") else { return nil }
        let xyNodes = pts.findAll("xy")
        guard xyNodes.count >= 2 else { return nil }

        let x1 = xyNodes[0].childDouble(0) ?? 0
        let y1 = xyNodes[0].childDouble(1) ?? 0
        let x2 = xyNodes[1].childDouble(0) ?? 0
        let y2 = xyNodes[1].childDouble(1) ?? 0

        return WireInfo(start: (x1, y1), end: (x2, y2))
    }

    private static func parseLabel(_ node: SExpr) -> LabelInfo? {
        // (label "name" (at X Y R)) or (global_label "name" ...)
        let name = node.childString(0) ?? ""
        let atNode = node.find("at")
        let x = atNode?.childDouble(0) ?? 0
        let y = atNode?.childDouble(1) ?? 0
        return LabelInfo(name: name, position: (x, y))
    }
}
