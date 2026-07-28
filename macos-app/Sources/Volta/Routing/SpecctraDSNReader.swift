//
//  SpecctraDSNReader.swift
//  Volta
//
//  Phase 253 Task 2 — Specctra DSN Reader (semantic layer)
//
//  Reads a Freerouting-output Specctra DSN file into a structured
//  SpecctraBoard that downstream code (SegmentSplicer) can splice into
//  a .kicad_pcb. Built on top of DSNConverter's tokenizer — no parallel
//  parsing.
//
//  Architecture (Council H-03):
//    - Single tokenizer: DSNConverter.tokenize() / findSection() /
//      validateBalance().
//    - Semantic layer: this file reads (wiring ...) section in full
//      detail (geometry + width + layer + net name + via padstacks),
//      not just counts.
//
//  Council L-05: DSNConverter.stripQuotesAndUnescape() handles Specctra
//  DSN doubled-quote escaping (`""` → `"`).
//
//  ponytail: no separate tokenizer, no separate scanner. Reuses
//  DSNConverter's primitives + the new stripQuotesAndUnescape helper.
//  The reader is ~200 LOC of pure semantic extraction.
//

import Foundation
import VoltaPCBCore

// MARK: - WireType

/// Type of wire in the Specctra (wiring ...) section.
public enum WireType: String, Sendable, Equatable {
    /// Normal routed wire (default Freerouting output).
    case normal
    /// Fixed wire — must not be ripped up by Freerouting.
    case fix
    /// Reserved for future Specctra wire types.
    case route
    case shunt
}

// MARK: - SpecctraWire

/// One wire path (a sequence of points on a single layer) emitted by
/// Freerouting in the (wiring ...) section.
public struct SpecctraWire: Sendable {
    public let netName: String
    public let points: [(x: Int, y: Int)]   // um
    public let widthUm: Int
    public let type: WireType
    public let layer: String?              // "F.Cu", "B.Cu" — nil if not on a known layer

    public init(netName: String, points: [(x: Int, y: Int)], widthUm: Int, type: WireType, layer: String? = nil) {
        self.netName = netName
        self.points = points
        self.widthUm = widthUm
        self.type = type
        self.layer = layer
    }
}

// MARK: - SpecctraVia

/// One via emitted by Freerouting in the (wiring ...) section.
public struct SpecctraVia: Sendable {
    public let netName: String
    public let position: (x: Int, y: Int)
    public let padstack: String

    public init(netName: String, position: (x: Int, y: Int), padstack: String) {
        self.netName = netName
        self.position = position
        self.padstack = padstack
    }
}

// MARK: - SpecctraPlacement

/// One footprint placement extracted from the (placement ...) section.
public struct SpecctraPlacement: Sendable, Equatable {
    public let componentName: String  // footprint lib_id
    public let reference: String      // board-level reference (e.g., "R1")
    public let xUm: Int
    public let yUm: Int
    public let side: String           // "front" | "back"
    public let rotation: Int

    public init(componentName: String, reference: String, xUm: Int, yUm: Int, side: String, rotation: Int) {
        self.componentName = componentName
        self.reference = reference
        self.xUm = xUm
        self.yUm = yUm
        self.side = side
        self.rotation = rotation
    }
}

// MARK: - SpecctraImage

/// One package image extracted from the (library ...) section.
public struct SpecctraImage: Sendable, Equatable {
    public let name: String
    public let side: String
    public let padstacks: [String]

    public init(name: String, side: String, padstacks: [String]) {
        self.name = name
        self.side = side
        self.padstacks = padstacks
    }
}

// MARK: - SpecctraNetwork

/// Per-net wiring metadata extracted from the (network ...) section.
public struct SpecctraNetwork: Sendable, Equatable {
    public let netNames: [String]
    public let padstackByNet: [String: String]

    public init(netNames: [String], padstackByNet: [String: String]) {
        self.netNames = netNames
        self.padstackByNet = padstackByNet
    }
}

// MARK: - SpecctraWiring

/// The (wiring ...) section contents — wires + vias emitted by Freerouting.
public struct SpecctraWiring: Sendable {
    public let wires: [SpecctraWire]
    public let vias: [SpecctraVia]

    public init(wires: [SpecctraWire], vias: [SpecctraVia]) {
        self.wires = wires
        self.vias = vias
    }
}

// MARK: - SpecctraBoard

/// Top-level Specctra DSN parsed structure. Mirrors the section layout.
public struct SpecctraBoard: Sendable {
    public let placements: [SpecctraPlacement]
    public let images: [SpecctraImage]
    public let network: SpecctraNetwork
    public let wiring: SpecctraWiring

    public init(placements: [SpecctraPlacement], images: [SpecctraImage], network: SpecctraNetwork, wiring: SpecctraWiring) {
        self.placements = placements
        self.images = images
        self.network = network
        self.wiring = wiring
    }

    public static let empty = SpecctraBoard(
        placements: [],
        images: [],
        network: SpecctraNetwork(netNames: [], padstackByNet: [:]),
        wiring: SpecctraWiring(wires: [], vias: [])
    )
}

// MARK: - SpecctraDSNReader

/// Semantic Specctra DSN reader. Built on top of DSNConverter's
/// tokenizer (single source of tokenization truth, Council H-03).
public struct SpecctraDSNReader: Sendable {

    public init() {}

    /// Read a Freerouting-output Specctra DSN file into a SpecctraBoard.
    public func read(_ dsnText: String) throws -> SpecctraBoard {
        let trimmed = dsnText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw DSNError.empty }

        try DSNConverter.validateBalance(trimmed)
        let tokens = DSNConverter.tokenize(trimmed)
        guard let pcbRange = DSNConverter.findSection(named: "pcb", in: tokens) else {
            throw DSNError.missingRoot
        }
        let pcbTokens = Array(tokens[pcbRange])

        let placements = extractPlacements(tokens: pcbTokens)
        let images = extractImages(tokens: pcbTokens)
        let network = extractNetwork(tokens: pcbTokens)
        let wiring = extractWiring(tokens: pcbTokens)

        return SpecctraBoard(
            placements: placements,
            images: images,
            network: network,
            wiring: wiring
        )
    }

    // MARK: - (placement ...)

    private func extractPlacements(tokens: [String]) -> [SpecctraPlacement] {
        guard let range = DSNConverter.findSection(named: "placement", in: tokens) else {
            return []
        }
        let section = Array(tokens[range])
        var placements: [SpecctraPlacement] = []
        var componentIndex = 0

        while componentIndex + 2 < section.count {
            guard section[componentIndex] == "(",
                  section[componentIndex + 1] == "component" else {
                componentIndex += 1
                continue
            }

            let componentName = DSNConverter.stripQuotesAndUnescape(section[componentIndex + 2])
            let componentEnd = skipBlock(tokens: section, startIndex: componentIndex)
            var placeIndex = componentIndex + 3

            while placeIndex + 6 < componentEnd {
                guard section[placeIndex] == "(",
                      section[placeIndex + 1] == "place",
                      let xUm = Int(section[placeIndex + 3]),
                      let yUm = Int(section[placeIndex + 4]),
                      let rotation = Int(section[placeIndex + 6]) else {
                    placeIndex += 1
                    continue
                }

                placements.append(SpecctraPlacement(
                    componentName: componentName,
                    reference: DSNConverter.stripQuotesAndUnescape(section[placeIndex + 2]),
                    xUm: xUm,
                    yUm: yUm,
                    side: DSNConverter.stripQuotesAndUnescape(section[placeIndex + 5]),
                    rotation: rotation
                ))
                placeIndex = skipBlock(tokens: section, startIndex: placeIndex)
            }
            componentIndex = componentEnd
        }
        return placements
    }

    // MARK: - (library ...)

    private func extractImages(tokens: [String]) -> [SpecctraImage] {
        guard let range = DSNConverter.findSection(named: "library", in: tokens) else {
            return []
        }
        let section = Array(tokens[range])
        var images: [SpecctraImage] = []
        var imageIndex = 0

        while imageIndex + 2 < section.count {
            guard section[imageIndex] == "(", section[imageIndex + 1] == "image" else {
                imageIndex += 1
                continue
            }

            let name = DSNConverter.stripQuotesAndUnescape(section[imageIndex + 2])
            let imageEnd = skipBlock(tokens: section, startIndex: imageIndex)
            var side = "front"
            var padstacks: [String] = []
            var childIndex = imageIndex + 3

            while childIndex + 2 < imageEnd {
                if section[childIndex] == "(", section[childIndex + 1] == "side" {
                    side = DSNConverter.stripQuotesAndUnescape(section[childIndex + 2])
                    childIndex = skipBlock(tokens: section, startIndex: childIndex)
                    continue
                }
                if section[childIndex] == "(", section[childIndex + 1] == "pin" {
                    padstacks.append(DSNConverter.stripQuotesAndUnescape(section[childIndex + 2]))
                    childIndex = skipBlock(tokens: section, startIndex: childIndex)
                    continue
                }
                childIndex += 1
            }

            images.append(SpecctraImage(name: name, side: side, padstacks: padstacks))
            imageIndex = imageEnd
        }
        return images
    }

    // MARK: - (network ...)

    private func extractNetwork(tokens: [String]) -> SpecctraNetwork {
        guard let range = DSNConverter.findSection(named: "network", in: tokens) else {
            return SpecctraNetwork(netNames: [], padstackByNet: [:])
        }
        let section = Array(tokens[range])
        var netNames: [String] = []
        var padstackByNet: [String: String] = [:]
        var netIndex = 0

        while netIndex + 2 < section.count {
            guard section[netIndex] == "(", section[netIndex + 1] == "net" else {
                netIndex += 1
                continue
            }

            let netName = DSNConverter.stripQuotesAndUnescape(section[netIndex + 2])
            let netEnd = skipBlock(tokens: section, startIndex: netIndex)
            if !netName.isEmpty {
                netNames.append(netName)
                var childIndex = netIndex + 3
                while childIndex + 2 < netEnd {
                    if section[childIndex] == "(", section[childIndex + 1] == "use_via" {
                        padstackByNet[netName] = DSNConverter.stripQuotesAndUnescape(section[childIndex + 2])
                        break
                    }
                    childIndex += 1
                }
            }
            netIndex = netEnd
        }
        return SpecctraNetwork(netNames: netNames, padstackByNet: padstackByNet)
    }

    // MARK: - (wiring ...)

    private func extractWiring(tokens: [String]) -> SpecctraWiring {
        guard let range = DSNConverter.findSection(named: "wiring", in: tokens) else {
            return SpecctraWiring(wires: [], vias: [])
        }
        let section = Array(tokens[range])
        var wires: [SpecctraWire] = []
        var vias: [SpecctraVia] = []
        var childIndex = 2

        while childIndex + 1 < section.count {
            guard section[childIndex] == "(" else {
                childIndex += 1
                continue
            }

            switch section[childIndex + 1] {
            case "wire":
                if let wire = parseWire(tokens: section, startIndex: childIndex) {
                    wires.append(wire)
                }
            case "via":
                if let via = parseVia(tokens: section, startIndex: childIndex) {
                    vias.append(via)
                }
            default:
                break
            }
            childIndex = skipBlock(tokens: section, startIndex: childIndex)
        }

        return SpecctraWiring(wires: wires, vias: vias)
    }

    /// Parse one (wire ...) block. Returns nil if the wire is malformed.
    private func parseWire(tokens: [String], startIndex: Int) -> SpecctraWire? {
        let wireEnd = skipBlock(tokens: tokens, startIndex: startIndex)
        var path: (layer: String, widthUm: Int, points: [(x: Int, y: Int)])?
        var netName = ""
        var wireType: WireType = .normal
        var childIndex = startIndex + 2

        while childIndex + 1 < wireEnd {
            guard tokens[childIndex] == "(" else {
                childIndex += 1
                continue
            }

            let childEnd = skipBlock(tokens: tokens, startIndex: childIndex)
            switch tokens[childIndex + 1] {
            case "path":
                path = parsePath(tokens: tokens, startIndex: childIndex, endIndex: childEnd)
            case "net" where childIndex + 2 < childEnd:
                netName = DSNConverter.stripQuotesAndUnescape(tokens[childIndex + 2])
            case "type" where childIndex + 2 < childEnd:
                wireType = WireType(rawValue: tokens[childIndex + 2]) ?? .normal
            default:
                break
            }
            childIndex = childEnd
        }

        guard let path else { return nil }
        return SpecctraWire(
            netName: netName,
            points: path.points,
            widthUm: path.widthUm,
            type: wireType,
            layer: path.layer
        )
    }

    private func parsePath(
        tokens: [String],
        startIndex: Int,
        endIndex: Int
    ) -> (layer: String, widthUm: Int, points: [(x: Int, y: Int)])? {
        guard startIndex + 3 < endIndex,
              let widthUm = Int(tokens[startIndex + 3]) else {
            return nil
        }

        var points: [(x: Int, y: Int)] = []
        var coordinateIndex = startIndex + 4
        while coordinateIndex + 1 < endIndex,
              tokens[coordinateIndex] != ")" {
            guard let x = Int(tokens[coordinateIndex]),
                  let y = Int(tokens[coordinateIndex + 1]) else {
                return nil
            }
            points.append((x: x, y: y))
            coordinateIndex += 2
        }
        guard points.count >= 2 else { return nil }

        return (
            layer: DSNConverter.stripQuotesAndUnescape(tokens[startIndex + 2]),
            widthUm: widthUm,
            points: points
        )
    }

    /// Parse one (via PADSTACK X Y (net "NAME") (type fix)) block.
    private func parseVia(tokens: [String], startIndex: Int) -> SpecctraVia? {
        let viaEnd = skipBlock(tokens: tokens, startIndex: startIndex)
        guard startIndex + 4 < viaEnd,
              let xUm = Int(tokens[startIndex + 3]),
              let yUm = Int(tokens[startIndex + 4]) else {
            return nil
        }

        var netName = ""
        var childIndex = startIndex + 5
        while childIndex + 2 < viaEnd {
            if tokens[childIndex] == "(", tokens[childIndex + 1] == "net" {
                netName = DSNConverter.stripQuotesAndUnescape(tokens[childIndex + 2])
                break
            }
            childIndex += 1
        }

        return SpecctraVia(
            netName: netName,
            position: (x: xUm, y: yUm),
            padstack: DSNConverter.stripQuotesAndUnescape(tokens[startIndex + 2])
        )
    }

    /// Skip past a top-level block, returning the index just after the closing paren.
    private func skipBlock(tokens: [String], startIndex: Int) -> Int {
        var depth = 0
        var i = startIndex
        while i < tokens.count {
            if tokens[i] == "(" { depth += 1 }
            else if tokens[i] == ")" {
                depth -= 1
                if depth == 0 { return i + 1 }
            }
            i += 1
        }
        return tokens.count
    }
}
