//
//  SegmentSplicer.swift
//  Volta
//
//  Phase 253 Task 2 — Specctra routes to KiCad PCB splice
//
//  Converts semantic Freerouting output into native KiCad S-expressions.
//  The existing PCB text is parsed before and after insertion so malformed
//  input or generated output cannot escape this boundary.
//

import Foundation

public struct SpliceStats: Sendable, Equatable {
    public let segmentsInserted: Int
    public let viasInserted: Int
    public let netsRouted: Int
    public let skipped: Int

    public init(
        segmentsInserted: Int,
        viasInserted: Int,
        netsRouted: Int,
        skipped: Int
    ) {
        self.segmentsInserted = segmentsInserted
        self.viasInserted = viasInserted
        self.netsRouted = netsRouted
        self.skipped = skipped
    }
}

public struct SplicedResult: Sendable {
    public let pcbContent: String
    public let stats: SpliceStats

    public init(pcbContent: String, stats: SpliceStats) {
        self.pcbContent = pcbContent
        self.stats = stats
    }
}

public enum SegmentSplicerError: Error, LocalizedError, Equatable {
    case emptyPCB
    case missingPCBRoot
    case invalidPCB(String)
    case malformedPCBRoot

    public var errorDescription: String? {
        switch self {
        case .emptyPCB:
            return "PCB content is empty"
        case .missingPCBRoot:
            return "PCB content is missing the required (kicad_pcb ...) root"
        case .invalidPCB(let reason):
            return "PCB content is invalid: \(reason)"
        case .malformedPCBRoot:
            return "PCB root expression is malformed"
        }
    }
}

public struct SegmentSplicer: Sendable {
    private static let millimetersPerMicrometer = 0.001
    private static let defaultViaSize = 0.8
    private static let defaultViaDrill = 0.4
    private static let defaultViaLayers = "F.Cu B.Cu"

    public init() {}

    public func splice(
        specctraBoard: SpecctraBoard,
        into pcbContent: String
    ) throws -> SplicedResult {
        guard !pcbContent.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw SegmentSplicerError.emptyPCB
        }

        let board: PCBBoard
        do {
            board = try PCBParser.parse(pcbContent)
        } catch {
            throw SegmentSplicerError.invalidPCB(error.localizedDescription)
        }

        let netIDs = Dictionary(uniqueKeysWithValues: board.nets.map { ($0.name, $0.number) })
        let routeNetNames = routedNetNames(specctraBoard: specctraBoard)
        let matchedNetNames = Set(routeNetNames.filter { netIDs[$0] != nil })
        let skippedNetNames = Set(routeNetNames.filter { netIDs[$0] == nil })

        let segmentLines = specctraBoard.wiring.wires.flatMap { wire in
            emitSegments(for: wire, netID: netIDs[wire.netName])
        }
        let viaLines = specctraBoard.wiring.vias.compactMap { via in
            emitVia(for: via, netID: netIDs[via.netName])
        }
        let generated = segmentLines + viaLines
        guard !generated.isEmpty else {
            return SplicedResult(
                pcbContent: pcbContent,
                stats: SpliceStats(
                    segmentsInserted: 0,
                    viasInserted: 0,
                    netsRouted: matchedNetNames.count,
                    skipped: skippedNetNames.count
                )
            )
        }

        let output = try inserting(generated, into: pcbContent)
        do {
            _ = try PCBParser.parse(output)
        } catch {
            throw SegmentSplicerError.invalidPCB(error.localizedDescription)
        }

        return SplicedResult(
            pcbContent: output,
            stats: SpliceStats(
                segmentsInserted: segmentLines.count,
                viasInserted: viaLines.count,
                netsRouted: matchedNetNames.count,
                skipped: skippedNetNames.count
            )
        )
    }

    private func routedNetNames(specctraBoard: SpecctraBoard) -> [String] {
        var names = Set<String>()
        specctraBoard.wiring.wires.forEach { names.insert($0.netName) }
        specctraBoard.wiring.vias.forEach { names.insert($0.netName) }
        return Array(names)
    }

    private func emitSegments(for wire: SpecctraWire, netID: Int?) -> [String] {
        guard let netID, wire.points.count >= 2 else { return [] }
        return zip(wire.points, wire.points.dropFirst()).map { start, end in
            let startX = formatMillimeters(start.x)
            let startY = formatMillimeters(start.y)
            let endX = formatMillimeters(end.x)
            let endY = formatMillimeters(end.y)
            let width = formatMillimeters(wire.widthUm)
            let uuid = UUID().uuidString.lowercased()
            let layer = escapeAtom(wire.layer ?? "F.Cu")
            return "  (segment (start \(startX) \(startY)) (end \(endX) \(endY)) (width \(width)) (layer \"\(layer)\") (net \(netID)) (uuid \"\(uuid)\"))"
        }
    }

    private func emitVia(for via: SpecctraVia, netID: Int?) -> String? {
        guard let netID else { return nil }
        let x = formatMillimeters(via.position.x)
        let y = formatMillimeters(via.position.y)
        let uuid = UUID().uuidString.lowercased()
        return "  (via (at \(x) \(y)) (size \(format(Self.defaultViaSize))) (drill \(format(Self.defaultViaDrill))) (layers \"F.Cu\" \"B.Cu\") (net \(netID)) (uuid \"\(uuid)\"))"
    }

    private func inserting(_ lines: [String], into pcbContent: String) throws -> String {
        guard let closingIndex = pcbContent.lastIndex(of: ")") else {
            throw SegmentSplicerError.malformedPCBRoot
        }
        let insertion = lines.joined(separator: "\n") + "\n"
        return String(pcbContent[..<closingIndex]) + insertion + String(pcbContent[closingIndex...])
    }

    private func formatMillimeters(_ micrometers: Int) -> String {
        format(Double(micrometers) * Self.millimetersPerMicrometer)
    }

    private func format(_ value: Double) -> String {
        String(format: "%.6f", locale: Locale(identifier: "en_US_POSIX"), value)
            .trimmingCharacters(in: CharacterSet(charactersIn: "0"))
            .trimmingCharacters(in: CharacterSet(charactersIn: "."))
            .replacingOccurrences(of: "-0", with: "0")
    }

    private func escapeAtom(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }
}
