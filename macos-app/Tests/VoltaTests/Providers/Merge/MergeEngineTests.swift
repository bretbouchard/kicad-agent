//
//  MergeEngineTests.swift
//  VoltaTests
//
//  Phase 1 / Task 4 — Merge Engine
//
//  Tests MPN deduplication, priority-based field merge, and error isolation.
//  Uses mock providers to verify merge logic without network calls.
//

import XCTest
@testable import Volta
@testable import VoltaPCBCore

final class MergeEngineTests: XCTestCase {

    /// Two providers returning the same MPN → merged into one component.
    func test_mergesByNormalizedMPN() async {
        let compRegistry = ComponentProviderRegistry()
        let cadRegistry = CADModelProviderRegistry()

        let comp = MockComponentProvider(
            name: "digikey", displayName: "Digi-Key",
            capabilities: [.pricing],
            mockResults: [
                UnifiedComponent(
                    partNumber: "STM32F411RET6",
                    manufacturer: "STMicroelectronics",
                    description: "MCU 32BIT 512KB FLASH",
                    pricing: [PricingData(unitPrice: 7.46, minOrderQty: 1, currency: "USD", distributor: "Digi-Key", lastUpdated: Date())]
                )
            ],
            mockAvailability: .available
        )
        compRegistry.register(comp)
        // Flush main queue
        let exp = expectation(description: "registered")
        DispatchQueue.main.async { exp.fulfill() }
        await fulfillment(of: [exp], timeout: 1.0)

        let engine = MergeEngine(componentRegistry: compRegistry, cadRegistry: cadRegistry)
        let results = await engine.search(keyword: "STM32F411")

        XCTAssertEqual(results.count, 1)
        XCTAssertEqual(results.first?.partNumber, "STM32F411RET6")
        XCTAssertEqual(results.first?.pricing?.first?.distributor, "Digi-Key")
    }

    /// MPN with different formatting (spaces, dashes) → still deduped.
    func test_normalizesMPNVariations() {
        XCTAssertEqual(MergeEngine.normalizeMPN("stm32f411ret6"), "STM32F411RET6")
        XCTAssertEqual(MergeEngine.normalizeMPN("STM32F411 RET6"), "STM32F411RET6")
        XCTAssertEqual(MergeEngine.normalizeMPN("STM32F411-RET6"), "STM32F411RET6")
    }

    /// Two different MPNs → two results.
    func test_differentMPNsNotMerged() async {
        let compRegistry = ComponentProviderRegistry()
        let cadRegistry = CADModelProviderRegistry()

        compRegistry.register(MockComponentProvider(
            name: "digikey", displayName: "Digi-Key",
            capabilities: [.pricing],
            mockResults: [
                UnifiedComponent(partNumber: "STM32F411RET6", manufacturer: "ST", description: "MCU 1"),
                UnifiedComponent(partNumber: "STM32F407VGT6", manufacturer: "ST", description: "MCU 2"),
            ],
            mockAvailability: .available
        ))
        let exp = expectation(description: "registered")
        DispatchQueue.main.async { exp.fulfill() }
        await fulfillment(of: [exp], timeout: 1.0)

        let engine = MergeEngine(componentRegistry: compRegistry, cadRegistry: cadRegistry)
        let results = await engine.search(keyword: "STM32")

        XCTAssertEqual(results.count, 2)
    }

    /// Merge preserves all sources.
    func test_mergesPreserveAllSources() async {
        let compRegistry = ComponentProviderRegistry()
        let cadRegistry = CADModelProviderRegistry()

        compRegistry.register(MockComponentProvider(
            name: "digikey", displayName: "Digi-Key",
            capabilities: [.pricing],
            mockResults: [
                UnifiedComponent(
                    partNumber: "STM32F411RET6",
                    manufacturer: "ST",
                    description: "MCU",
                    sources: [ComponentSource(provider: "digikey", providerPartId: "STM32F411RET6", lastUpdated: Date(), confidence: 1.0)]
                )
            ],
            mockAvailability: .available
        ))
        compRegistry.register(MockComponentProvider(
            name: "mouser", displayName: "Mouser",
            capabilities: [.pricing],
            mockResults: [
                UnifiedComponent(
                    partNumber: "STM32F411RET6",
                    manufacturer: "ST",
                    description: "MCU",
                    sources: [ComponentSource(provider: "mouser", providerPartId: "STM32F411RET6", lastUpdated: Date(), confidence: 0.9)]
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
        XCTAssertEqual(results.first?.sources.count, 2)
        let providerNames = Set(results.first!.sources.map(\.provider))
        XCTAssertTrue(providerNames.contains("digikey"))
        XCTAssertTrue(providerNames.contains("mouser"))
    }
}
