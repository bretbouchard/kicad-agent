//
//  UnifiedComponentTests.swift
//  VoltaTests
//
//  Phase 1 / Task 0 — VoltaPCBCore Foundation
//
//  Tests for the vendor-neutral data model surface introduced in Task 0:
//    - UnifiedComponent JSON round-trip (Codable correctness)
//    - UnifiedComponent minimal-init defaults (Optional semantics)
//    - ProviderAvailability.isAvailable switch coverage
//    - CADModelFormat CaseIterable ordering
//
//  These are pure value-type tests — no provider instances, no network,
//  no async. They lock the model contract before Phase 1 providers arrive.
//

import XCTest
@testable import VoltaPCBCore

final class UnifiedComponentTests: XCTestCase {

    func testUnifiedComponent_encodingDecoding_roundTrip() throws {
        let component = UnifiedComponent(
            partNumber: "STM32F411RET6",
            manufacturer: "STMicroelectronics",
            description: "Mainstream ARM Cortex-M4 MCU",
            sources: [
                ComponentSource(
                    provider: "digikey",
                    providerPartId: "497-11924-ND",
                    lastUpdated: Date(timeIntervalSince1970: 1750000000),
                    confidence: 0.95
                )
            ],
            pricing: [
                PricingData(
                    unitPrice: 4.63,
                    minOrderQty: 1,
                    tieredPricing: [
                        PricingTier(minQty: 1, unitPrice: 4.63),
                        PricingTier(minQty: 10, unitPrice: 4.17),
                        PricingTier(minQty: 25, unitPrice: 3.71)
                    ],
                    currency: "USD",
                    distributor: "Digi-Key",
                    lastUpdated: Date(timeIntervalSince1970: 1750000000)
                )
            ],
            stock: [
                StockData(
                    quantityAvailable: 4521,
                    distributor: "Digi-Key",
                    leadTime: "immediate",
                    lastUpdated: Date(timeIntervalSince1970: 1750000000)
                )
            ],
            specs: [
                "Core": "ARM Cortex-M4",
                "Flash": "512KB",
                "RAM": "128KB",
                "Speed": "100MHz"
            ],
            datasheetURL: URL(string: "https://www.st.com/resource/en/datasheet/stm32f411re.pdf"),
            lcscPartNumber: "C2040",
            category: "Embedded Processors & Controllers"
        )

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(component)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decoded = try decoder.decode(UnifiedComponent.self, from: data)

        XCTAssertEqual(decoded.partNumber, component.partNumber)
        XCTAssertEqual(decoded.manufacturer, component.manufacturer)
        XCTAssertEqual(decoded.sources.count, 1)
        XCTAssertEqual(decoded.sources.first?.provider, "digikey")
        XCTAssertEqual(decoded.pricing?.first?.unitPrice, 4.63)
        XCTAssertEqual(decoded.pricing?.first?.tieredPricing?.count, 3)
        XCTAssertEqual(decoded.stock?.first?.quantityAvailable, 4521)
        XCTAssertEqual(decoded.specs?["Core"], "ARM Cortex-M4")
        XCTAssertEqual(decoded.lcscPartNumber, "C2040")
        XCTAssertNotNil(decoded.datasheetURL)
    }

    func testUnifiedComponent_minimalInit_hasNoOptionalData() {
        let component = UnifiedComponent(
            partNumber: "RC0402FR-0710KL",
            manufacturer: "Yageo",
            description: "10kΩ resistor"
        )

        XCTAssertEqual(component.partNumber, "RC0402FR-0710KL")
        XCTAssertTrue(component.sources.isEmpty)
        XCTAssertNil(component.pricing)
        XCTAssertNil(component.stock)
        XCTAssertNil(component.specs)
        XCTAssertNil(component.cadModels)
        XCTAssertNil(component.datasheetURL)
        XCTAssertNil(component.lcscPartNumber)
        XCTAssertNil(component.category)
    }

    func testProviderAvailability_isAvailable_onlyTrueForAvailable() {
        XCTAssertTrue(ProviderAvailability.available.isAvailable)
        XCTAssertFalse(ProviderAvailability.requiresAuth(reason: "no key").isAvailable)
        XCTAssertFalse(ProviderAvailability.unavailable(reason: "network").isAvailable)
        XCTAssertFalse(ProviderAvailability.offlineCacheOnly(reason: "stale").isAvailable)
    }

    func testCADModelFormat_allCases() {
        XCTAssertEqual(CADModelFormat.allCases.count, 4)
        XCTAssertEqual(CADModelFormat.kicadMod.rawValue, "kicadMod")
        XCTAssertEqual(CADModelFormat.kicadSym.rawValue, "kicadSym")
        XCTAssertEqual(CADModelFormat.wrl.rawValue, "wrl")
        XCTAssertEqual(CADModelFormat.step.rawValue, "step")
    }
}
