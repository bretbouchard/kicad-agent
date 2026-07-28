//
//  RoutingTypesTests.swift
//  VoltaTests
//
//  Phase 253 Task 1 — Routing Types Tests
//
//  Locks the Codable + Equatable contracts on the RoutingProvider
//  supporting types so future refactors don't quietly break JSON
//  persistence of RoutingRules or board summary equality.
//

import XCTest
@testable import VoltaPCBCore

final class RoutingTypesTests: XCTestCase {

    func test_routingRules_defaultValues() {
        let rules = RoutingRules()
        XCTAssertEqual(rules.layerCount, 2)
        XCTAssertEqual(rules.clearance, 0.2, accuracy: 0.001)
        XCTAssertEqual(rules.minTraceWidth, 0.15, accuracy: 0.001)
        XCTAssertEqual(rules.minViaSize, 0.4, accuracy: 0.001)
        XCTAssertEqual(rules.netClasses, [.signal, .power])
        XCTAssertEqual(rules.timeout, .seconds(600))
    }

    func test_routingRules_codableRoundTrip() throws {
        let original = RoutingRules(
            layerCount: 4,
            clearance: 0.25,
            minTraceWidth: 0.2,
            minViaSize: 0.6,
            netClasses: [.signal, .power, .analog],
            timeout: .seconds(120)
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(original)
        let decoded = try JSONDecoder().decode(RoutingRules.self, from: data)
        XCTAssertEqual(decoded, original)
    }

    func test_routingRules_equality() {
        let a = RoutingRules(layerCount: 4, clearance: 0.25, minTraceWidth: 0.2, minViaSize: 0.6, netClasses: [.signal], timeout: .seconds(60))
        let b = RoutingRules(layerCount: 4, clearance: 0.25, minTraceWidth: 0.2, minViaSize: 0.6, netClasses: [.signal], timeout: .seconds(60))
        XCTAssertEqual(a, b)

        let c = RoutingRules(layerCount: 6, clearance: 0.25, minTraceWidth: 0.2, minViaSize: 0.6, netClasses: [.signal], timeout: .seconds(60))
        XCTAssertNotEqual(a, c)
    }

    func test_pcbSummary_equality() {
        let a = PCBSummary(componentCount: 42, netCount: 60, layerCount: 2, boardSize: Size2D(width: 50, height: 30))
        let b = PCBSummary(componentCount: 42, netCount: 60, layerCount: 2, boardSize: Size2D(width: 50, height: 30))
        XCTAssertEqual(a, b)

        let c = PCBSummary(componentCount: 43, netCount: 60, layerCount: 2, boardSize: Size2D(width: 50, height: 30))
        XCTAssertNotEqual(a, c)
    }

    func test_size2D_codableRoundTrip() throws {
        let original = Size2D(width: 100.5, height: 75.25)
        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(Size2D.self, from: data)
        XCTAssertEqual(decoded, original)
    }

    func test_routingMetrics_codableRoundTrip() throws {
        let original = RoutingMetrics(
            wiresRouted: 142,
            viasPlaced: 18,
            unroutedNets: ["NET1", "NET2"],
            layers: 2
        )
        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(RoutingMetrics.self, from: data)
        XCTAssertEqual(decoded, original)
    }

    func test_routingCapability_setRoundTrip() {
        let caps: Set<RoutingCapability> = [.autoroute, .offline, .powerAware]
        XCTAssertEqual(caps.count, 3)
        XCTAssertTrue(caps.contains(.autoroute))
        XCTAssertFalse(caps.contains(.cloud))
    }

    func test_netClass_codableRoundTrip() throws {
        for nc in NetClass.allCases {
            let data = try JSONEncoder().encode(nc)
            let decoded = try JSONDecoder().decode(NetClass.self, from: data)
            XCTAssertEqual(decoded, nc)
        }
    }
}