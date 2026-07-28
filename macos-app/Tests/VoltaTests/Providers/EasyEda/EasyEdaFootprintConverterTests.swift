//
//  EasyEdaFootprintConverterTests.swift
//  VoltaTests
//
//  Phase 4 / Task 6b — Real format conversion (P1 Council Gate 2 fix).
//
//  Tests for EasyEdaFootprintConverter: verify that parsed EasyEDA JSON
//  shapes become real KiCad footprint geometry (pads, lines, circles,
//  arcs), not stub envelopes.
//

import XCTest
@testable import Volta

final class EasyEdaFootprintConverterTests: XCTestCase {

    // MARK: - SMD pad parsing

    /// An SMD pad with width != height must emit a real KiCad `pad` line
    /// with non-zero size and non-origin coordinates.
    func test_smdPadEmitsRealKiCadPad() {
        let json = """
        {"shape":[{"shape":"PAD","x":100,"y":50,"width":200,"height":300,"layerId":1,"number":"1"}]}
        """
        let payload = EasyEdaFootprint(uuid: "F1", data: json, title: "Test")
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "C2040")
        XCTAssertTrue(output.contains("(module"), "Must start with (module")
        XCTAssertTrue(output.contains("(pad 1 smd"))
        // 100 eex (10 mil) = 100 × 0.254 mm = 25.4 mm
        XCTAssertTrue(output.contains("25.4000"), "Pad X must be converted (100 eex = 25.4 mm)")
        // 200 eex wide = 50.8 mm
        XCTAssertTrue(output.contains("50.8000"))
        // 300 eex tall = 76.2 mm
        XCTAssertTrue(output.contains("76.2000"))
    }

    /// A thru_hole pad with non-zero holeRadius must emit a `drill`
    /// clause in the KiCad output.
    func test_thruHolePadEmitsDrill() {
        let json = """
        {"shape":[{"shape":"PAD","x":0,"y":0,"width":150,"height":150,"layerId":1,"number":"1","holeRadius":30}]}
        """
        let payload = EasyEdaFootprint(uuid: "F2", data: json, title: nil)
        let output = EasyEdaFootprintConverter().convert(footprint: payload, partName: "PIN")
        XCTAssertTrue(output.contains("(pad 1 thru_hole"))
        XCTAssertTrue(output.contains("(drill"))
        XCTAssertTrue(output.contains("15.2400"), "Drill 60 eex = 15.24 mm")
    }

    // MARK: - Track parsing

    func test_trackEmitsFpLine() {
        let json = """
        {"shape":[{"shape":"TRACK","points":[0,0,100,0,100,100],"strokeWidth":10,"layerId":3}]}
        """
        let payload = EasyEdaFootprint(uuid: "F3", data: json, title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "L")
        XCTAssertTrue(output.contains("(fp_line"))
        XCTAssertTrue(output.contains("(layer F.SilkS)"))
    }

    // MARK: - Outline parsing

    func test_rectEmitsFourLines() {
        let json = """
        {"shape":[{"shape":"RECT","x":0,"y":0,"width":100,"height":100,"strokeWidth":10,"layerId":3}]}
        """
        let payload = EasyEdaFootprint(uuid: "F4", data: json, title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "R")
        let lineCount = output.components(separatedBy: "(fp_line").count - 1
        XCTAssertEqual(lineCount, 4, "Rectangle must emit 4 fp_line edges")
    }

    func test_circleEmitsFpCircle() {
        let json = """
        {"shape":[{"shape":"CIRCLE","cx":500,"cy":500,"radius":100,"strokeWidth":10,"layerId":3}]}
        """
        let payload = EasyEdaFootprint(uuid: "F5", data: json, title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "C")
        XCTAssertTrue(output.contains("(fp_circle"))
        XCTAssertTrue(output.contains("(center"))
        XCTAssertTrue(output.contains("127.0000"), "Center 500 eex = 127.0 mm")
    }

    func test_arcEmitsFpArc() {
        let json = """
        {"shape":[{"shape":"ARC","path":"M 0 0 A 50 50 0 0 1 100 0","strokeWidth":10,"layerId":3}]}
        """
        let payload = EasyEdaFootprint(uuid: "F6", data: json, title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "A")
        XCTAssertTrue(output.contains("(fp_arc"))
    }

    // MARK: - Empty / malformed

    /// An empty payload must still emit a valid `(module ... )` envelope.
    func test_emptyDataEmitsEnvelope() {
        let payload = EasyEdaFootprint(uuid: "F7", data: nil, title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "E")
        XCTAssertTrue(output.contains("(module"))
    }

    /// Malformed JSON must not throw; falls back to envelope-only output.
    func test_malformedJsonEmitsEnvelope() {
        let payload = EasyEdaFootprint(uuid: "F8", data: "{not json", title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "BAD")
        XCTAssertTrue(output.contains("(module"))
    }

    // MARK: - Multiple shapes

    /// Multiple shapes must all be rendered, not just the first.
    func test_multipleShapesAllRender() {
        let json = """
        {"shape":[
          {"shape":"PAD","x":0,"y":0,"width":50,"height":50,"layerId":1,"number":"1"},
          {"shape":"PAD","x":200,"y":0,"width":50,"height":50,"layerId":1,"number":"2"},
          {"shape":"CIRCLE","cx":100,"cy":200,"radius":50,"strokeWidth":10,"layerId":3}
        ]}
        """
        let payload = EasyEdaFootprint(uuid: "F9", data: json, title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "M")
        XCTAssertTrue(output.contains("(pad 1 smd"))
        XCTAssertTrue(output.contains("(pad 2 smd"))
        XCTAssertTrue(output.contains("(fp_circle"))
    }

    // MARK: - Unit conversion

    /// 1000 eex = 10000 mil = 254.0 mm.
    func test_unitConversionIsCorrect() {
        let json = """
        {"shape":[{"shape":"PAD","x":1000,"y":0,"width":0,"height":0,"layerId":1,"number":"1"}]}
        """
        let payload = EasyEdaFootprint(uuid: "F10", data: json, title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "U")
        XCTAssertTrue(output.contains("254.0000"))
    }

    // MARK: - Y-axis flip

    /// EasyEDA positive Y must become KiCad negative Y.
    func test_yAxisFlip() {
        let json = """
        {"shape":[{"shape":"PAD","x":0,"y":500,"width":0,"height":0,"layerId":1,"number":"1"}]}
        """
        let payload = EasyEdaFootprint(uuid: "F11", data: json, title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "Y")
        XCTAssertTrue(output.contains("-127.0000"), "EasyEDA positive Y must flip to negative in KiCad output")
    }

    // MARK: - Via + Hole

    func test_viaEmitsThruHolePad() {
        let json = """
        {"shape":[{"shape":"VIA","centerX":100,"centerY":100,"diameter":60,"drill":30}]}
        """
        let payload = EasyEdaFootprint(uuid: "F12", data: json, title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "V")
        XCTAssertTrue(output.contains("(pad"))
        XCTAssertTrue(output.contains("thru_hole"))
    }

    func test_holeEmitsPad() {
        let json = """
        {"shape":[{"shape":"HOLE","centerX":0,"centerY":0,"radius":25}]}
        """
        let payload = EasyEdaFootprint(uuid: "F13", data: json, title: nil)
        let output = try EasyEdaFootprintConverter().convert(footprint: payload, partName: "H")
        XCTAssertTrue(output.contains("(pad"))
    }
}