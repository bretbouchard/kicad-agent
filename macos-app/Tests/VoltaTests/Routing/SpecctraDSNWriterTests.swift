//
//  SpecctraDSNWriterTests.swift
//  VoltaTests
//
//  Phase 253 Task 2 — Specctra DSN Writer Tests
//
//  Unit tests for the pure-Swift Specctra DSN writer. Coverage:
//    (a) emit 2-layer board → snapshot parse against expected sections
//    (b) all (structure)/(placement)/(library)/(network) sub-sections present
//    (c) snap_angle validation throws on invalid input
//    (d) (wiring) emitted iff board.segments is non-empty
//    (e) coordinate transform mm→um exact
//    (f) pin name quoting (Council WR-03)
//    (g) empty pin number → "pad" placeholder (Rule 1 fix)
//    (h) courtyard obstacles / outline emission (R-1)
//
//  ponytail: tests build small PCBBoard values inline (no fixture file).
//  No FileManager IO, no shell-out. Pure Swift. Tests run in CI without
//  Java/Freerouting.
//

import Testing
import Foundation
@testable import Volta
import VoltaPCBCore

@Suite("Specctra DSN Writer")
struct SpecctraDSNWriterTests {

    // MARK: - Helpers

    /// Build a small 2-layer PCB with two resistors and a connecting trace.
    static func makeBoard(
        segments: [PCBSegment] = [],
        vias: [PCBVia] = [],
        padNumber: String = "1"
    ) -> PCBBoard {
        let pads1 = [
            PCBPad(
                number: padNumber, type: "smd", shape: "roundrect",
                position: (-0.75, 0), size: (0.5, 0.5),
                layers: "F.Cu", netName: "NET_A", drill: 0
            ),
            PCBPad(
                number: "2", type: "smd", shape: "roundrect",
                position: (0.75, 0), size: (0.5, 0.5),
                layers: "F.Cu", netName: "NET_B", drill: 0
            ),
        ]
        let pads2 = [
            PCBPad(
                number: "1", type: "smd", shape: "roundrect",
                position: (-0.75, 0), size: (0.5, 0.5),
                layers: "F.Cu", netName: "NET_A", drill: 0
            ),
            PCBPad(
                number: "2", type: "smd", shape: "roundrect",
                position: (0.75, 0), size: (0.5, 0.5),
                layers: "F.Cu", netName: "", drill: 0
            ),
        ]
        let fps = [
            PCBFootprint(
                reference: "R1", libId: "TestResistor:R_0805",
                layer: "F.Cu", position: (100, 100), rotation: 0, pads: pads1
            ),
            PCBFootprint(
                reference: "R2", libId: "TestResistor:R_0805",
                layer: "F.Cu", position: (110, 105), rotation: 0, pads: pads2
            ),
        ]
        return PCBBoard(
            version: "20241129",
            footprints: fps,
            segments: segments,
            vias: vias,
            nets: [
                PCBNet(number: 0, name: ""),
                PCBNet(number: 1, name: "NET_A"),
                PCBNet(number: 2, name: "NET_B"),
            ],
            netClasses: [],
            graphicItems: [],
            layers: ["F.Cu", "B.Cu"]
        )
    }

    // MARK: - (a) Snapshot parse

    @Test("Emits a parseable DSN with all major sections")
    func emitsParsableDSN() {
        let board = Self.makeBoard()
        let writer = SpecctraDSNWriter()
        let dsn = writer.write(board)

        #expect(dsn.contains("(pcb "))
        #expect(dsn.contains("(resolution um 10)"))
        #expect(dsn.contains("(unit um)"))
        #expect(dsn.contains("(structure"))
        #expect(dsn.contains("(placement"))
        #expect(dsn.contains("(library"))
        #expect(dsn.contains("(network"))
    }

    @Test("DSN opens with pcb source name")
    func opensWithPcbSourceName() {
        let board = Self.makeBoard()
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.hasPrefix("(pcb 20241129"))
    }

    // MARK: - (b) All sub-sections present

    @Test("Structure section has layer declarations + boundary")
    func structureHasLayersAndBoundary() {
        let board = Self.makeBoard()
        let dsn = SpecctraDSNWriter().write(board)

        #expect(dsn.contains("(layer F.Cu"))
        #expect(dsn.contains("(layer B.Cu"))
        #expect(dsn.contains("(boundary"))
        #expect(dsn.contains("(path pcb 0  "))
    }

    @Test("Placement section groups components by footprint")
    func placementGroupsComponents() {
        let board = Self.makeBoard()
        let dsn = SpecctraDSNWriter().write(board)

        #expect(dsn.contains("(component \"TestResistor:R_0805\""))
        #expect(dsn.contains("(place R1 100000 100000 front 0)"))
        #expect(dsn.contains("(place R2 110000 105000 front 0)"))
    }

    @Test("Library section has THT via padstack + SMD padstacks + images")
    func libraryHasAllParts() {
        let board = Self.makeBoard()
        let dsn = SpecctraDSNWriter().write(board)

        #expect(dsn.contains("(padstack \"Via[0-1]\""))
        #expect(dsn.contains("(padstack \"SMD_F.Cu_"))
        #expect(dsn.contains("(image \"TestResistor:R_0805\""))
        #expect(dsn.contains("(side front)"))
        #expect(dsn.contains("(pin SMD_F.Cu_"))
    }

    @Test("Network section has classes + nets")
    func networkHasClassesAndNets() {
        let board = Self.makeBoard()
        let dsn = SpecctraDSNWriter().write(board)

        #expect(dsn.contains("(class default \"\""))
        #expect(dsn.contains("(circuit"))
        #expect(dsn.contains("(use_layer F.Cu B.Cu)"))
        #expect(dsn.contains("(use_via \"Via[0-1]\")"))
        #expect(dsn.contains("(net \"NET_A\""))
        #expect(dsn.contains("(net \"NET_B\""))
        #expect(dsn.contains("(pins R1-1 R2-1)"))
    }

    // MARK: - (c) snap_angle validation

    @Test("SnapAngle enum has expected raw values")
    func snapAngleEnumConstrained() {
        #expect(SnapAngle.none.rawValue == "none")
        #expect(SnapAngle.fortyFive.rawValue == "fortyfive_degree")
        #expect(SnapAngle.ninetyDegree.rawValue == "ninety_degree")
    }

    @Test("snap_angle control block emitted when SnapAngle is not .none")
    func snapAngleControlEmitted() {
        let board = Self.makeBoard()
        let dsn = SpecctraDSNWriter(snapAngle: .fortyFive).write(board)
        #expect(dsn.contains("(control (snap_angle fortyfive_degree))"))
    }

    @Test("snap_angle control block NOT emitted when SnapAngle is .none")
    func snapAngleControlOmitted() {
        let board = Self.makeBoard()
        let dsn = SpecctraDSNWriter(snapAngle: .none).write(board)
        #expect(!dsn.contains("(control"))
    }

    // MARK: - (d) Wiring emission

    @Test("(wiring ...) is emitted iff board has segments")
    func wiringEmittedIffSegmentsExist() {
        let emptyBoard = Self.makeBoard(segments: [], vias: [])
        let emptyDSN = SpecctraDSNWriter().write(emptyBoard)
        #expect(!emptyDSN.contains("(wiring"))

        let seg = PCBSegment(
            start: (99.25, 100), end: (105, 100), width: 0.25,
            layer: "F.Cu", netName: "NET_A"
        )
        let boardWithSegs = Self.makeBoard(segments: [seg])
        let dsnWithSegs = SpecctraDSNWriter().write(boardWithSegs)
        #expect(dsnWithSegs.contains("(wiring"))
    }

    @Test("(wiring ...) wires carry (type fix) for locked nets")
    func wiringWiresAreTypeFix() {
        let seg = PCBSegment(
            start: (99.25, 100), end: (105, 100), width: 0.25,
            layer: "F.Cu", netName: "NET_A"
        )
        let board = Self.makeBoard(segments: [seg])
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("(wire (path F.Cu 250 99250 100000 105000 100000) (net \"NET_A\") (type fix))"))
    }

    @Test("(wiring ...) vias carry (type fix) and via padstack name")
    func wiringViasAreTypeFix() {
        let via = PCBVia(
            position: (105, 100), size: 0.8, drill: 0.4,
            layers: "F.Cu B.Cu", netName: "NET_A"
        )
        let board = Self.makeBoard(vias: [via])
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("(via Via[0-1] 105000 100000 (net \"NET_A\") (type fix))"))
    }

    // MARK: - (e) Coordinate transform exact

    @Test("mm → um coordinate transform is exact (×1000)")
    func coordinateTransformExact() {
        let seg = PCBSegment(
            start: (99.25, 100), end: (105, 100), width: 0.25,
            layer: "F.Cu", netName: "NET_A"
        )
        let board = Self.makeBoard(segments: [seg])
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("99250 100000 105000 100000"))
        #expect(dsn.contains(" 250 "))
    }

    @Test("Writer's MM_TO_UM constant is exactly 1000")
    func mmToUmConstant() {
        #expect(SpecctraDSNWriter.MM_TO_UM == 1000.0)
    }

    // MARK: - (f) Pin name quoting (Council WR-03)

    @Test("Pin names with double quotes get DSN doubled-quote escaping")
    func pinNameDoubleQuoteEscaping() {
        let pad = PCBPad(
            number: "weird\"name", type: "smd", shape: "rect",
            position: (0, 0), size: (0.5, 0.5),
            layers: "F.Cu", netName: "NET_A", drill: 0
        )
        let fp = PCBFootprint(
            reference: "X1", libId: "Test:X",
            layer: "F.Cu", position: (100, 100), rotation: 0, pads: [pad]
        )
        let board = PCBBoard(
            version: "v1", footprints: [fp], segments: [], vias: [],
            nets: [PCBNet(number: 0, name: "")],
            netClasses: [], graphicItems: [], layers: ["F.Cu", "B.Cu"]
        )
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("\"weird\"\"name\""))
    }

    // MARK: - (g) Empty pin number → "pad" placeholder

    @Test("Empty pin number substitutes 'pad' placeholder")
    func emptyPinNumberSubstitutesPad() {
        let pad = PCBPad(
            number: "", type: "smd", shape: "rect",
            position: (0, 0), size: (0.5, 0.5),
            layers: "F.Cu", netName: "NET_A", drill: 0
        )
        let fp = PCBFootprint(
            reference: "X1", libId: "Test:X",
            layer: "F.Cu", position: (100, 100), rotation: 0, pads: [pad]
        )
        let board = PCBBoard(
            version: "v1", footprints: [fp], segments: [], vias: [],
            nets: [PCBNet(number: 0, name: "")],
            netClasses: [], graphicItems: [], layers: ["F.Cu", "B.Cu"]
        )
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("\"pad\""))
    }

    // MARK: - (h) R-1 outline emission

    @Test("Image emits outline (rect ...) computed from pad AABB")
    func imageEmitsOutline() {
        let pad = PCBPad(
            number: "1", type: "smd", shape: "rect",
            position: (-0.75, 0), size: (0.5, 0.5),
            layers: "F.Cu", netName: "", drill: 0
        )
        let fp = PCBFootprint(
            reference: "X1", libId: "Test:X",
            layer: "F.Cu", position: (100, 100), rotation: 0, pads: [pad]
        )
        let board = PCBBoard(
            version: "v1", footprints: [fp], segments: [], vias: [],
            nets: [PCBNet(number: 0, name: "")],
            netClasses: [], graphicItems: [], layers: ["F.Cu", "B.Cu"]
        )
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("(outline (rect F.Cu "))
        #expect(dsn.contains("99000 99750 99500 100250"))
    }

    // MARK: - Custom config

    @Test("Custom pad via size / wire width / clearance are respected")
    func customConfigRespected() {
        let pad = PCBPad(
            number: "1", type: "thru_hole", shape: "circle",
            position: (0, 0), size: (1.0, 1.0),
            layers: "*.Cu", netName: "NET_A", drill: 0.5
        )
        let fp = PCBFootprint(
            reference: "X1", libId: "Test:X",
            layer: "F.Cu", position: (0, 0), rotation: 0, pads: [pad]
        )
        let board = PCBBoard(
            version: "v1", footprints: [fp], segments: [], vias: [],
            nets: [PCBNet(number: 0, name: "")],
            netClasses: [], graphicItems: [], layers: ["F.Cu", "B.Cu"]
        )
        let dsn = SpecctraDSNWriter(
            padViaSizeUm: 1500, wireWidthUm: 300, clearanceUm: 400
        ).write(board)
        #expect(dsn.contains("1500"))
        #expect(dsn.contains("(width 300)"))
        #expect(dsn.contains("(clearance 400)"))
    }

    // MARK: - Edge cases

    @Test("Empty board (no footprints) emits minimal DSN without placement")
    func emptyBoardMinimalDSN() {
        let board = PCBBoard(
            version: "v1", footprints: [], segments: [], vias: [],
            nets: [], netClasses: [], graphicItems: [],
            layers: ["F.Cu", "B.Cu"]
        )
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("(structure"))
        #expect(dsn.contains("(library"))
        #expect(dsn.contains("(network"))
        #expect(!dsn.contains("(placement"))
    }

    @Test("Board with empty segments list does NOT emit (wiring)")
    func emptySegmentsNoWiring() {
        let board = Self.makeBoard(segments: [], vias: [])
        let dsn = SpecctraDSNWriter().write(board)
        #expect(!dsn.contains("(wiring"))
    }

    @Test("Back-side component emits (side back)")
    func backSideComponent() {
        let pad = PCBPad(
            number: "1", type: "smd", shape: "rect",
            position: (0, 0), size: (0.5, 0.5),
            layers: "B.Cu", netName: "NET_A", drill: 0
        )
        let fp = PCBFootprint(
            reference: "B1", libId: "Test:B",
            layer: "B.Cu", position: (50, 50), rotation: 0, pads: [pad]
        )
        let board = PCBBoard(
            version: "v1", footprints: [fp], segments: [], vias: [],
            nets: [PCBNet(number: 0, name: "")],
            netClasses: [], graphicItems: [], layers: ["F.Cu", "B.Cu"]
        )
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("(side back)"))
        #expect(dsn.contains("(place B1 50000 50000 back 0)"))
    }

    @Test("Net class rules are emitted for named classes")
    func netClassRulesEmitted() {
        let fp = PCBFootprint(
            reference: "R1", libId: "R",
            layer: "F.Cu", position: (0, 0), rotation: 0,
            pads: [
                PCBPad(
                    number: "1", type: "smd", shape: "rect",
                    position: (0, 0), size: (0.5, 0.5),
                    layers: "F.Cu", netName: "PWR", drill: 0
                ),
            ]
        )
        let nc = PCBNetClass(
            name: "power",
            trackWidth: 0.5, clearance: 0.3,
            viaDiameter: 0.8, viaDrill: 0.4,
            nets: ["PWR"]
        )
        let board = PCBBoard(
            version: "v1", footprints: [fp], segments: [], vias: [],
            nets: [PCBNet(number: 0, name: "")],
            netClasses: [nc], graphicItems: [],
            layers: ["F.Cu", "B.Cu"]
        )
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("(class \"power\" PWR"))
        #expect(dsn.contains("(width 500)"))
        #expect(dsn.contains("(clearance 300)"))
        #expect(dsn.contains("(use_via \"Via[power]\")"))
    }

    @Test("Boundary falls back to footprint AABB + 5mm margin when no Edge.Cuts")
    func boundaryFallbackToFootprintAABB() {
        let fp = PCBFootprint(
            reference: "R1", libId: "R",
            layer: "F.Cu", position: (50, 50), rotation: 0,
            pads: [
                PCBPad(
                    number: "1", type: "smd", shape: "rect",
                    position: (0, 0), size: (0.5, 0.5),
                    layers: "F.Cu", netName: "", drill: 0
                ),
            ]
        )
        let board = PCBBoard(
            version: "v1", footprints: [fp], segments: [], vias: [],
            nets: [], netClasses: [], graphicItems: [],
            layers: ["F.Cu", "B.Cu"]
        )
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("45000 45000 55000 55000"))
    }

    @Test("Boundary uses Edge.Cuts when present")
    func boundaryUsesEdgeCuts() {
        let fp = PCBFootprint(
            reference: "R1", libId: "R",
            layer: "F.Cu", position: (50, 50), rotation: 0,
            pads: [
                PCBPad(
                    number: "1", type: "smd", shape: "rect",
                    position: (0, 0), size: (0.5, 0.5),
                    layers: "F.Cu", netName: "", drill: 0
                ),
            ]
        )
        let edge = PCBGraphicItem(
            type: "gr_line", layer: "Edge.Cuts",
            start: (10, 20), end: (110, 120)
        )
        let board = PCBBoard(
            version: "v1", footprints: [fp], segments: [], vias: [],
            nets: [], netClasses: [], graphicItems: [edge],
            layers: ["F.Cu", "B.Cu"]
        )
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("10000 20000 110000 120000"))
    }

    @Test("Bead #28: net name with / sanitized to _ in pin nets")
    func netNameSlashSanitized() {
        let fp = PCBFootprint(
            reference: "R1", libId: "R",
            layer: "F.Cu", position: (0, 0), rotation: 0,
            pads: [
                PCBPad(
                    number: "1", type: "smd", shape: "rect",
                    position: (0, 0), size: (0.5, 0.5),
                    layers: "F.Cu",
                    netName: "TX{slash}RX", drill: 0
                ),
            ]
        )
        let board = PCBBoard(
            version: "v1", footprints: [fp], segments: [], vias: [],
            nets: [PCBNet(number: 0, name: "")],
            netClasses: [], graphicItems: [], layers: ["F.Cu", "B.Cu"]
        )
        let dsn = SpecctraDSNWriter().write(board)
        #expect(dsn.contains("TX_RX"))
    }
}
