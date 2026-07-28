//
//  EasyEdaSymbolConverterTests.swift
//  VoltaTests
//
//  Phase 4 / Task 6b — Real format conversion (P1 Council Gate 2 fix).
//
//  Tests for EasyEdaSymbolConverter: verify that parsed EasyEDA SVG
//  shapes become real KiCad symbol geometry (pins, rectangles, circles,
//  polylines), not stub envelopes.
//

import XCTest
@testable import Volta

final class EasyEdaSymbolConverterTests: XCTestCase {

    // MARK: - Pin parsing

    /// A pin with the standard EasyEDA encoding (`P~` prefix, `c_etype="P"`,
    /// `d` attribute containing the tilde-separated descriptor) must produce
    /// a KiCad pin S-expression with non-zero length and non-origin position.
    func test_pinEmitsRealKiCadPin() {
        let svg = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
          <path d="P~1~~100 50 200 50~1" c_etype="P"/>
        </svg>
        """
        let output = EasyEdaSymbolConverter().convert(svg: svg, partName: "C2040", symbolTitle: "Test Part")
        XCTAssertTrue(output.contains("(kicad_symbol_lib"))
        XCTAssertTrue(output.contains("(pin passive line"))
        // Real geometry: inner endpoint at (100,50) mil = (2.54, -1.27) mm,
        // outer endpoint at (200,50) mil = (5.08, -1.27) mm, length 2.54 mm.
        XCTAssertTrue(output.contains("2.5400"), "Pin inner X must convert to mm")
        XCTAssertTrue(output.contains("-1.2700"), "Pin Y must be Y-flipped (EasyEDA positive Y → KiCad negative Y)")
        XCTAssertTrue(output.contains("length 2.5400)"), "Pin length = (outer - inner) = 2.54 mm")
    }

    /// A pin with a name distinct from its number should emit both the
    /// name and the number strings in the KiCad output.
    func test_pinEmitsNameAndNumber() {
        let svg = """
        <svg><path d="P~3~~0 0 200 50~VCC" c_etype="P"/></svg>
        """
        let output = EasyEdaSymbolConverter().convert(svg: svg, partName: "IC1", symbolTitle: nil)
        XCTAssertTrue(output.contains("(name \"VCC\""))
        XCTAssertTrue(output.contains("(number \"3\""))
    }

    // MARK: - Rectangle parsing

    /// A rectangle with strokeWidth > 0 must produce a KiCad rectangle
    /// with non-origin coordinates (proves real geometry, not stubs).
    func test_rectangleEmitsKiCadRect() {
        let svg = """
        <svg><path d="R~-100~-200~0~0~100~200~#000000~1~0~none~" c_etype="R"/></svg>
        """
        let output = EasyEdaSymbolConverter().convert(svg: svg, partName: "R1", symbolTitle: nil)
        XCTAssertTrue(output.contains("(rectangle (start"))
        XCTAssertTrue(output.contains("(end"))
        // Real rectangle coordinates (-100 mil X, -200 mil Y) must appear.
        XCTAssertTrue(output.contains("-2.5400"), "Rectangle X must convert (negative -100 mil = -2.54 mm)")
    }

    // MARK: - Circle parsing

    func test_circleEmitsKiCadCircle() {
        let svg = """
        <svg><path d="C~500~500~100~#000000~1~0~none~" c_etype="C"/></svg>
        """
        let output = EasyEdaSymbolConverter().convert(svg: svg, partName: "D1", symbolTitle: nil)
        XCTAssertTrue(output.contains("(circle (center"))
        XCTAssertTrue(output.contains("(radius"))
        // cx=500 mil = 12.7 mm
        XCTAssertTrue(output.contains("12.7000"))
    }

    // MARK: - Polyline parsing

    func test_polylineEmitsKiCadPolyline() {
        let svg = """
        <svg><path d="PL~4~0 0 100 0 100 100 0 100~#000000~1~0~none~" c_etype="PL"/></svg>
        """
        let output = EasyEdaSymbolConverter().convert(svg: svg, partName: "L1", symbolTitle: nil)
        XCTAssertTrue(output.contains("(polyline (pts"))
    }

    // MARK: - Empty / malformed input

    /// Empty SVG must still emit a valid envelope (downstream validation
    /// requires `(kicad_symbol_lib` prefix even for empty symbols).
    func test_emptySvgEmitsEnvelope() {
        let output = EasyEdaSymbolConverter().convert(svg: "", partName: "EMPTY", symbolTitle: nil)
        XCTAssertTrue(output.contains("(kicad_symbol_lib"))
    }

    /// Malformed XML must not throw — parser falls through to empty
    /// shapes list, then the placeholder pin is emitted.
    func test_malformedSvgEmitsEnvelope() {
        let output = EasyEdaSymbolConverter().convert(svg: "<not really svg", partName: "BAD", symbolTitle: nil)
        XCTAssertTrue(output.contains("(kicad_symbol_lib"))
        XCTAssertTrue(output.contains("(pin passive line"))
    }

    /// SVG with no `c_etype` attributes must produce only the envelope
    /// + placeholder pin (no real geometry).
    func test_svgWithoutEtypeProducesPlaceholder() {
        let svg = """
        <svg><circle cx="50" cy="50" r="10" fill="black"/></svg>
        """
        let output = EasyEdaSymbolConverter().convert(svg: svg, partName: "X", symbolTitle: nil)
        XCTAssertTrue(output.contains("(kicad_symbol_lib"))
        // Should still have at least one pin (placeholder).
        XCTAssertTrue(output.contains("(pin passive line"))
    }

    // MARK: - Unit conversion

    /// 1000 mil must convert to 25.4 mm exactly (KiCad's standard unit).
    func test_unitConversionIsCorrect() {
        // Use a circle to inspect the conversion cleanly.
        let svg = """
        <svg><path d="C~1000~0~0~#000000~1~0~none~" c_etype="C"/></svg>
        """
        let output = EasyEdaSymbolConverter().convert(svg: svg, partName: "U", symbolTitle: nil)
        XCTAssertTrue(output.contains("25.4000"), "1000 mil must equal 25.4000 mm")
    }

    // MARK: - Y-axis flip

    /// EasyEDA Y grows downward; KiCad Y grows upward. A positive Y in
    /// EasyEDA must produce a negative Y in KiCad.
    func test_yAxisFlip() {
        let svg = """
        <svg><path d="C~0~500~0~#000000~1~0~none~" c_etype="C"/></svg>
        """
        let output = EasyEdaSymbolConverter().convert(svg: svg, partName: "Y", symbolTitle: nil)
        // EasyEDA Y=500 mil → KiCad Y=-12.7 mm.
        XCTAssertTrue(output.contains("-12.7000"), "EasyEDA positive Y must flip to negative in KiCad output")
    }
}