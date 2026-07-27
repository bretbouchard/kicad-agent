//
//  MergeEngineV2Tests.swift
//  VoltaTests
//
//  Phase 2 / Task 4 — Merge Engine v2
//
//  Tests priority-based field selection and provider ordering.
//

import XCTest
@testable import Volta
@testable import VoltaPCBCore

final class MergeEngineV2Tests: XCTestCase {

    /// Higher-priority provider's pricing wins when both return pricing.
    func test_priorityBasedPricingSelection() async {
        let compRegistry = ComponentProviderRegistry()
        let cadRegistry = CADModelProviderRegistry()

        // Register jlcparts first (lower priority)
        compRegistry.register(MockComponentProvider(
            name: "jlcparts", displayName: "JLC",
            capabilities: [.pricing],
            mockResults: [
                UnifiedComponent(
                    partNumber: "STM32F411RET6",
                    manufacturer: "ST",
                    description: "MCU",
                    sources: [ComponentSource(provider: "jlcparts", providerPartId: "1", lastUpdated: Date(), confidence: 0.5)],
                    pricing: [PricingData(unitPrice: 9.99, minOrderQty: 1, currency: "USD", distributor: "JLC", lastUpdated: Date())]
                )
            ],
            mockAvailability: .available
        ))
        // Digi-Key second (higher priority) — should win pricing
        compRegistry.register(MockComponentProvider(
            name: "digikey", displayName: "Digi-Key",
            capabilities: [.pricing],
            mockResults: [
                UnifiedComponent(
                    partNumber: "STM32F411RET6",
                    manufacturer: "STMicroelectronics",
                    description: "MCU 32BIT",
                    sources: [ComponentSource(provider: "digikey", providerPartId: "497-ND", lastUpdated: Date(), confidence: 0.95)],
                    pricing: [PricingData(unitPrice: 7.46, minOrderQty: 1, currency: "USD", distributor: "Digi-Key", lastUpdated: Date())]
                )
            ],
            mockAvailability: .available
        ))
        let exp = expectation(description: "registered")
        DispatchQueue.main.async { exp.fulfill() }
        await fulfillment(of: [exp], timeout: 1.0)

        let engine = MergeEngine(componentRegistry: compRegistry, cadRegistry: cadRegistry)
        let results = await engine.search(keyword: "STM32")

        XCTAssertEqual(results.count, 1)
        let comp = results.first!
        // Both distributors should be present (merged)
        XCTAssertEqual(comp.pricing?.count, 2)
        // Sources from both providers
        XCTAssertEqual(comp.sources.count, 2)
    }

    /// ProviderPriority rank ordering.
    func test_providerPriorityRanking() {
        let priority = ProviderPriority.default

        // Default order: digikey < octopart < mouser < easyeda2kicad < easyeda < jlcparts
        XCTAssertLessThan(priority.rank(for: "digikey"), priority.rank(for: "jlcparts"))
        XCTAssertLessThan(priority.rank(for: "digikey"), priority.rank(for: "mouser"))
        XCTAssertLessThan(priority.rank(for: "octopart"), priority.rank(for: "jlcparts"))

        // Unknown provider gets Int.max
        XCTAssertEqual(priority.rank(for: "unknown"), Int.max)
    }

    /// ProviderPriority comparison.
    func test_providerPriorityComparison() {
        let priority = ProviderPriority.default

        XCTAssertTrue(priority.isHigherPriority("digikey", than: "jlcparts"))
        XCTAssertTrue(priority.isHigherPriority("digikey", than: "mouser"))
        XCTAssertFalse(priority.isHigherPriority("jlcparts", than: "digikey"))
    }

    /// Custom priority order.
    func test_customPriorityOrder() {
        let priority = ProviderPriority(order: ["mouser", "digikey"])

        XCTAssertTrue(priority.isHigherPriority("mouser", than: "digikey"))
        XCTAssertFalse(priority.isHigherPriority("digikey", than: "mouser"))
    }

    /// Results sorted by provider priority.
    func test_resultsSortedByPriority() async {
        let compRegistry = ComponentProviderRegistry()
        let cadRegistry = CADModelProviderRegistry()

        compRegistry.register(MockComponentProvider(
            name: "jlcparts", displayName: "JLC",
            capabilities: [.pricing],
            mockResults: [
                UnifiedComponent(
                    partNumber: "STM32F407VGT6",
                    manufacturer: "ST",
                    description: "MCU from jlcparts",
                    sources: [ComponentSource(provider: "jlcparts", providerPartId: "j1", lastUpdated: Date(), confidence: 0.5)]
                )
            ],
            mockAvailability: .available
        ))
        compRegistry.register(MockComponentProvider(
            name: "digikey", displayName: "Digi-Key",
            capabilities: [.pricing],
            mockResults: [
                UnifiedComponent(
                    partNumber: "STM32F411RET6",
                    manufacturer: "ST",
                    description: "MCU from digikey",
                    sources: [ComponentSource(provider: "digikey", providerPartId: "d1", lastUpdated: Date(), confidence: 0.95)]
                )
            ],
            mockAvailability: .available
        ))
        let exp = expectation(description: "registered")
        DispatchQueue.main.async { exp.fulfill() }
        await fulfillment(of: [exp], timeout: 1.0)

        let engine = MergeEngine(componentRegistry: compRegistry, cadRegistry: cadRegistry)
        let results = await engine.search(keyword: "STM32")

        XCTAssertEqual(results.count, 2)
        // Digi-Key result should come first (higher priority)
        XCTAssertEqual(results[0].sources.first?.provider, "digikey")
        XCTAssertEqual(results[1].sources.first?.provider, "jlcparts")
    }
}
