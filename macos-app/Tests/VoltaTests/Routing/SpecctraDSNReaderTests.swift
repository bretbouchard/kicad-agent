//
//  SpecctraDSNReaderTests.swift
//  VoltaTests
//
//  Phase 253 Task 2 — Specctra DSN Reader Tests
//
//  Pure-Swift semantic parsing tests. No Java, Freerouting, filesystem IO,
//  or second tokenizer.
//

import Testing
@testable import Volta
import VoltaPCBCore

@Suite("Specctra DSN Reader")
struct SpecctraDSNReaderTests {

    private static let representativeDSN = """
    (pcb "reader_test"
      (placement
        (component "Device:R"
          (place R1 1000 2000 front 90)
        )
      )
      (library
        (image "Device:R"
          (side front)
          (pin SMD_F.Cu_500_500 R1-1 0 0)
          (pin SMD_F.Cu_500_500 R1-2 1000 0)
        )
      )
      (network
        (net "A""B" (pins R1-1))
        (net NET_UNQUOTED (pins R1-2) (use_via Via[0-1]))
      )
      (wiring
        (wire
          (path F.Cu 250 1000 2000 3000 4000 5000 6000)
          (net "A""B")
          (type route)
        )
        (wire
          (path B.Cu 300 -10 20 30 -40)
          (net NET_UNQUOTED)
          (type fix)
        )
        (via Via[0-1] 3000 4000 (net "A""B") (type route))
      )
    )
    """

    @Test("Parses placement and library semantics")
    func parsesPlacementAndLibrary() throws {
        let board = try SpecctraDSNReader().read(Self.representativeDSN)

        #expect(board.placements.count == 1)
        let placement = try #require(board.placements.first)
        #expect(placement.componentName == "Device:R")
        #expect(placement.reference == "R1")
        #expect(placement.xUm == 1000)
        #expect(placement.yUm == 2000)
        #expect(placement.side == "front")
        #expect(placement.rotation == 90)

        #expect(board.images.count == 1)
        let image = try #require(board.images.first)
        #expect(image.name == "Device:R")
        #expect(image.side == "front")
        #expect(image.padstacks == ["SMD_F.Cu_500_500", "SMD_F.Cu_500_500"])
    }

    @Test("Captures complete wire and via geometry")
    func capturesWiringGeometry() throws {
        let board = try SpecctraDSNReader().read(Self.representativeDSN)

        #expect(board.wiring.wires.count == 2)
        let first = board.wiring.wires[0]
        #expect(first.netName == "A\"B")
        #expect(first.layer == "F.Cu")
        #expect(first.widthUm == 250)
        #expect(first.type == .route)
        #expect(first.points.count == 3)
        #expect(first.points[0].x == 1000)
        #expect(first.points[0].y == 2000)
        #expect(first.points[2].x == 5000)
        #expect(first.points[2].y == 6000)

        let second = board.wiring.wires[1]
        #expect(second.netName == "NET_UNQUOTED")
        #expect(second.layer == "B.Cu")
        #expect(second.widthUm == 300)
        #expect(second.type == .fix)
        #expect(second.points[0].x == -10)
        #expect(second.points[1].y == -40)

        #expect(board.wiring.vias.count == 1)
        let via = board.wiring.vias[0]
        #expect(via.netName == "A\"B")
        #expect(via.padstack == "Via[0-1]")
        #expect(via.position.x == 3000)
        #expect(via.position.y == 4000)
    }

    @Test("Handles quoted, escaped, and unquoted net names")
    func handlesNetNameForms() throws {
        let board = try SpecctraDSNReader().read(Self.representativeDSN)

        #expect(board.network.netNames == ["A\"B", "NET_UNQUOTED"])
        #expect(board.network.padstackByNet["NET_UNQUOTED"] == "Via[0-1]")
        #expect(DSNConverter.stripQuotesAndUnescape("\"a\"\"b\"") == "a\"b")
        #expect(DSNConverter.stripQuotesAndUnescape("plain") == "plain")
    }

    @Test("Writer-reader round trip preserves segment and via geometry exactly")
    func writerReaderRoundTrip() throws {
        let segment = PCBSegment(
            start: (99.251, 100.002), end: (105.003, 101.004),
            width: 0.251, layer: "F.Cu", netName: "NET_A"
        )
        let via = PCBVia(
            position: (105.003, 101.004), size: 0.8, drill: 0.4,
            layers: "F.Cu B.Cu", netName: "NET_A"
        )
        let footprint = PCBFootprint(
            reference: "R1", libId: "Device:R",
            layer: "F.Cu", position: (100, 100), rotation: 0,
            pads: [
                PCBPad(
                    number: "1", type: "smd", shape: "rect",
                    position: (0, 0), size: (0.5, 0.5),
                    layers: "F.Cu", netName: "NET_A", drill: 0
                ),
            ]
        )
        let source = PCBBoard(
            version: "20241129", footprints: [footprint],
            segments: [segment], vias: [via],
            nets: [PCBNet(number: 1, name: "NET_A")],
            netClasses: [], graphicItems: [], layers: ["F.Cu", "B.Cu"]
        )

        let dsn = SpecctraDSNWriter().write(source)
        let parsed = try SpecctraDSNReader().read(dsn)

        #expect(parsed.wiring.wires.count == 1)
        let parsedSegment = parsed.wiring.wires[0]
        #expect(abs(parsedSegment.points[0].x - 99_251) <= 1)
        #expect(abs(parsedSegment.points[0].y - 100_002) <= 1)
        #expect(abs(parsedSegment.points[1].x - 105_003) <= 1)
        #expect(abs(parsedSegment.points[1].y - 101_004) <= 1)
        #expect(parsedSegment.widthUm == 251)
        #expect(parsedSegment.netName == "NET_A")

        #expect(parsed.wiring.vias.count == 1)
        let parsedVia = parsed.wiring.vias[0]
        #expect(abs(parsedVia.position.x - 105_003) <= 1)
        #expect(abs(parsedVia.position.y - 101_004) <= 1)
        #expect(parsedVia.netName == "NET_A")
    }

    @Test("Rejects empty and structurally invalid input")
    func rejectsInvalidInput() {
        #expect(throws: DSNError.self) {
            _ = try SpecctraDSNReader().read("")
        }
        #expect(throws: DSNError.self) {
            _ = try SpecctraDSNReader().read("(pcb broken")
        }
    }
}
