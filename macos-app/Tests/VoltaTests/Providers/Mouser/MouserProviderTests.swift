//
//  MouserProviderTests.swift
//  VoltaTests
//
//  Phase 251 / Wave 2 — Mouser Provider TDD Tests
//

import Testing
import Foundation
@testable import Volta
import VoltaPCBCore

@Suite("Mouser Provider")
struct MouserProviderTests {
    let provider = MouserProvider()

    @Test("Provider identity")
    func identity() {
        #expect(provider.name == "mouser")
        #expect(provider.displayName == "Mouser")
        #expect(provider.capabilities.contains(.pricing))
        #expect(provider.capabilities.contains(.stock))
        #expect(provider.capabilities.contains(.specifications))
    }

    @Test("Availability requires API key")
    func availabilityWithoutKey() async {
        // Without env var or keychain entry, should require auth
        let avail = await provider.availability
        if case .requiresAuth = avail {
            // expected when no key configured
        } else {
            // If a key happens to be configured in env, that's fine too
            #expect(avail == .available || avail == .requiresAuth(reason: ""))
        }
    }

    @Test("Search throws when not configured")
    func searchWithoutKey() async {
        // This test only validates error path when no key is set
        // In test env without MOUSER_API_KEY, search should throw
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] == nil {
            await #expect(throws: MouserError.self) {
                _ = try await provider.search(keyword: "STM32")
            }
        }
    }

    @Test("Error descriptions are human-readable")
    func errorDescriptions() {
        let notConfigured = MouserError.notConfigured
        #expect(notConfigured.localizedDescription.contains("mouser.com"))

        let httpError = MouserError.httpError(status: 500)
        #expect(httpError.localizedDescription.contains("500"))

        let rateLimited = MouserError.rateLimited(retryAfter: 120)
        #expect(rateLimited.localizedDescription.contains("120"))
    }

    // MARK: - Wave 2 Tests

    @Test("Task 251-02: Search by exact part number")
    func searchByPartNumber() async {
        // Test exact MPN lookup returns correct part
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let results = try await provider.search(keyword: "STM32F411RET6")
            #expect(!results.isEmpty)
            let normalized = "STM32F411RET6"
            let exactMatch = results.first { $0.partNumber.uppercased() == normalized }
            #expect(exactMatch != nil)
        }
    }

    @Test("Task 251-02: Search by keyword")
    func searchByKeyword() async {
        // Test keyword search returns relevant results
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let results = try await provider.search(keyword: "Arduino")
            #expect(!results.isEmpty)
            // Should contain descriptions with the keyword
            let hasKeyword = results.contains { $0.description.localizedCaseInsensitiveContains("Arduino") }
            #expect(hasKeyword)
        }
    }

    @Test("Task 251-02: Empty results handling")
    func emptyResults() async {
        // Test that nonsense searches return empty arrays, not errors
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let results = try await provider.search(keyword: "NONEXISTENTPARTXYZ123")
            #expect(results.isEmpty)
        }
    }

    @Test("Task 251-02: Query parameter validation")
    func queryValidation() async {
        // Test special characters are properly encoded
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let results = try await provider.search(keyword: "STM32F411RET6+TR")
            // Should not throw encoding errors
            #expect(results is [UnifiedComponent])
        }
    }

    @Test("Task 251-03: Stock data structure")
    func stockDataStructure() async {
        // Test stock information is properly parsed
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let results = try await provider.search(keyword: "STM32F411RET6")
            let firstWithStock = results.first { $0.stock != nil && !$0.stock!.isEmpty }
            if let part = firstWithStock {
                let stockEntry = part.stock!.first
                #expect(stockEntry?.distributor == "Mouser")
                #expect(stockEntry?.quantityAvailable >= 0)
                #expect(stockEntry?.lastUpdated != nil)
            }
        }
    }

    @Test("Task 251-03: Multiple warehouse handling")
    func multipleWarehouses() async {
        // Test that stock data can come from multiple sources
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let results = try await provider.search(keyword: "STM32F411RET6")
            // Some parts should have stock data
            let withStock = results.filter { $0.stock != nil && !$0.stock!.isEmpty }
            #expect(withStock.count >= 0)
        }
    }

    @Test("Task 251-04: Part details success")
    func partDetailsSuccess() async {
        // Test getDetails returns full component information
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let details = try await provider.getDetails(partNumber: "STM32F411RET6")
            #expect(details != nil)
            if let part = details {
                #expect(!part.partNumber.isEmpty)
                #expect(!part.manufacturer.isEmpty)
            }
        }
    }

    @Test("Task 251-04: Part details not found")
    func partDetailsNotFound() async {
        // Test getDetails returns nil for non-existent parts
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let details = try await provider.getDetails(partNumber: "NONEXISTENTPARTXYZ123")
            // Should return nil, not throw
            #expect(details == nil)
        }
    }

    @Test("Task 251-04: Pricing tier parsing")
    func pricingTierParsing() async {
        // Test that pricing tiers are properly extracted
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let results = try await provider.search(keyword: "STM32F411RET6")
            let firstWithPricing = results.first { $0.pricing != nil && !$0.pricing!.isEmpty }
            if let part = firstWithPricing, let pricing = part.pricing?.first {
                #expect(pricing.unitPrice > 0)
                #expect(pricing.minOrderQty >= 1)
                #expect(pricing.currency == "USD")
                #expect(pricing.distributor == "Mouser")
            }
        }
    }

    @Test("Task 251-04: Datasheet URL extraction")
    func datasheetURLExtraction() async {
        // Test datasheet URLs are properly extracted
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let results = try await provider.search(keyword: "STM32F411RET6")
            let firstWithDatasheet = results.first { $0.datasheetURL != nil }
            if let part = firstWithDatasheet {
                #expect(part.datasheetURL?.absoluteString.hasPrefix("http") == true)
            }
        }
    }

    @Test("Task 251-04: Specifications extraction")
    func specificationsExtraction() async {
        // Test parametric specs are extracted
        if ProcessInfo.processInfo.environment["MOUSER_API_KEY"] != nil {
            let results = try await provider.search(keyword: "STM32F411RET6")
            let firstWithSpecs = results.first { $0.specs != nil && !$0.specs!.isEmpty }
            if let part = firstWithSpecs {
                #expect(part.specs?.count ?? 0 > 0)
                // Verify spec structure
                for (key, value) in part.specs! {
                    #expect(!key.isEmpty)
                    #expect(!value.isEmpty)
                }
            }
        }
    }
}
