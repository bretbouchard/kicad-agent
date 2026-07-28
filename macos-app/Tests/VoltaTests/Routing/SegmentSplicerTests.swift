//
//  SegmentSplicerTests.swift
//  VoltaTests
//
//  Phase 253 Task 2 — Specctra-to-KiCad route splicing tests
//

import Foundation
import Testing
@testable import Volta

@Suite("Segment Splicer")
struct SegmentSplicerTests {

    private static let pcb = """
    (kicad_pcb (version 20240108) (generator pcbnew)
      (general (thickness 1.6))
      (paper "A4")
      (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen") (44 "Edge.Cuts" user))
      (setup (pad_to_mask_clearance 0))
      (net 0 "")
      (net 1 "NET_A")
      (net 2 "NET_B")
    )
    """

    private static let routedBoard = SpecctraBoard(
        placements: [],
        images: [],
        network: SpecctraNetwork(
            netNames: ["NET_A", "MISSING"],
            padstackByNet: [:]
        ),
        wiring: SpecctraWiring(
            wires: [
                SpecctraWire(
                    netName: "NET_A",
                    points: [(1000, 2000), (3000, 4000), (5000, 6000)],
                    widthUm: 250,
                    type: .route,
                    layer: "F.Cu"
                ),
                SpecctraWire(
                    netName: "MISSING",
                    points: [(1, 2), (3, 4)],
                    widthUm: 250,
                    type: .route,
                    layer: "B.Cu"
                )
            ],
            vias: [
                SpecctraVia(
                    netName: "NET_A",
                    position: (5000, 6000),
                    padstack: "Via[0-1]"
                ),
                SpecctraVia(
                    netName: "MISSING",
                    position: (10, 20),
                    padstack: "Via[0-1]"
                )
            ]
        )
    )

    @Test("Converts a polyline into adjacent KiCad segments")
    func convertsPolyline() throws {
        let result = try SegmentSplicer().splice(
            specctraBoard: Self.routedBoard,
            into: Self.pcb
        )
        let parsed = try PCBParser.parse(result.pcbContent)

        #expect(parsed.segments.count == 2)
        #expect(parsed.segments[0].start.x == 1.0)
        #expect(parsed.segments[0].start.y == 2.0)
        #expect(parsed.segments[0].end.x == 3.0)
        #expect(parsed.segments[0].end.y == 4.0)
        #expect(parsed.segments[1].start.x == 3.0)
        #expect(parsed.segments[1].end.y == 6.0)
        #expect(parsed.segments.allSatisfy { $0.width == 0.25 && $0.layer == "F.Cu" })
    }

    @Test("Maps routed net names to numeric KiCad net IDs")
    func mapsNetNames() throws {
        let result = try SegmentSplicer().splice(
            specctraBoard: Self.routedBoard,
            into: Self.pcb
        )
        let parsed = try PCBParser.parse(result.pcbContent)

        #expect(parsed.segments.allSatisfy { $0.netName == "NET_A" })
        #expect(result.pcbContent.contains("(net 1)"))
        #expect(!result.pcbContent.contains("(net \"NET_A\")"))
    }

    @Test("Skips DSN nets absent from the PCB")
    func skipsUnknownNets() throws {
        let result = try SegmentSplicer().splice(
            specctraBoard: Self.routedBoard,
            into: Self.pcb
        )

        #expect(result.stats.segmentsInserted == 2)
        #expect(result.stats.viasInserted == 1)
        #expect(result.stats.netsRouted == 1)
        #expect(result.stats.skipped == 1)
    }

    @Test("Inserts vias with default two-layer geometry")
    func insertsViaGeometry() throws {
        let result = try SegmentSplicer().splice(
            specctraBoard: Self.routedBoard,
            into: Self.pcb
        )
        let parsed = try PCBParser.parse(result.pcbContent)
        let via = try #require(parsed.vias.first)

        #expect(via.position.x == 5.0)
        #expect(via.position.y == 6.0)
        #expect(via.size == 0.8)
        #expect(via.drill == 0.4)
        #expect(via.layers == "F.Cu B.Cu")
        #expect(via.netName == "NET_A")
    }

    @Test("Preserves root ordering and reparses the complete result")
    func reparsesAndAppendsBeforeRootClose() throws {
        let marker = "(setup (pad_to_mask_clearance 0))"
        let result = try SegmentSplicer().splice(
            specctraBoard: Self.routedBoard,
            into: Self.pcb
        )

        #expect(result.pcbContent.contains(marker))
        #expect(result.pcbContent.range(of: marker)!.lowerBound < result.pcbContent.range(of: "(segment")!.lowerBound)
        #expect(result.pcbContent.last == ")")
        _ = try PCBParser.parse(result.pcbContent)
    }

    @Test("Does not emit output for an empty route result")
    func emptyResult() throws {
        let empty = SpecctraBoard.empty
        let result = try SegmentSplicer().splice(specctraBoard: empty, into: Self.pcb)

        #expect(result.pcbContent == Self.pcb)
        #expect(result.stats == SpliceStats(segmentsInserted: 0, viasInserted: 0, netsRouted: 0, skipped: 0))
    }
}
