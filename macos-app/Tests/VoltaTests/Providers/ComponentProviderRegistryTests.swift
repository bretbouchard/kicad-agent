//
//  ComponentProviderRegistryTests.swift
//  VoltaTests
//
//  Phase 1 / Task 1 — Provider Registries
//
//  Locks the ComponentProviderRegistry contract:
//    - register() adds providers, dedup by name
//    - unregister() removes by name
//    - searchAll() fans out in parallel and merges results
//    - searchAll() isolates provider errors (one failure doesn't crash the rest)
//
//  Mock providers conform to ComponentDataProvider from VoltaPCBCore. The
//  registry lives in the Volta target so we @testable import both.
//

import XCTest
@testable import Volta
@testable import VoltaPCBCore

/// Mock component data provider for testing.
struct MockComponentProvider: ComponentDataProvider {
    let name: String
    let displayName: String
    let capabilities: Set<ProviderCapability>
    let mockResults: [UnifiedComponent]
    let mockAvailability: ProviderAvailability

    var availability: ProviderAvailability { mockAvailability }

    func search(keyword: String) async throws -> [UnifiedComponent] {
        mockResults.filter { $0.partNumber.contains(keyword) || $0.description.contains(keyword) }
    }

    func getDetails(partNumber: String) async throws -> UnifiedComponent? {
        mockResults.first { $0.partNumber == partNumber }
    }
}

final class ComponentProviderRegistryTests: XCTestCase {

    func test_register_addsProvider() {
        let registry = ComponentProviderRegistry()
        let provider = MockComponentProvider(
            name: "mock",
            displayName: "Mock",
            capabilities: [.pricing],
            mockResults: [],
            mockAvailability: .available
        )
        registry.register(provider)
        // Allow DispatchQueue.main.async to execute
        let exp = expectation(description: "provider registered")
        DispatchQueue.main.async { exp.fulfill() }
        wait(for: [exp], timeout: 1.0)
        XCTAssertEqual(registry.providers.count, 1)
    }

    func test_register_dedupByName() {
        let registry = ComponentProviderRegistry()
        let provider1 = MockComponentProvider(
            name: "digikey", displayName: "Digi-Key",
            capabilities: [.pricing], mockResults: [], mockAvailability: .available
        )
        let provider2 = MockComponentProvider(
            name: "digikey", displayName: "Digi-Key Duplicate",
            capabilities: [.pricing], mockResults: [], mockAvailability: .available
        )
        registry.register(provider1)
        registry.register(provider2)
        let exp = expectation(description: "dedup")
        DispatchQueue.main.async { exp.fulfill() }
        wait(for: [exp], timeout: 1.0)
        XCTAssertEqual(registry.providers.count, 1)
    }

    func test_unregister_removesProvider() {
        let registry = ComponentProviderRegistry()
        let provider = MockComponentProvider(
            name: "mock", displayName: "Mock",
            capabilities: [.pricing], mockResults: [], mockAvailability: .available
        )
        registry.register(provider)
        let exp1 = expectation(description: "registered")
        DispatchQueue.main.async { exp1.fulfill() }
        wait(for: [exp1], timeout: 1.0)

        registry.unregister(name: "mock")
        let exp2 = expectation(description: "unregistered")
        DispatchQueue.main.async { exp2.fulfill() }
        wait(for: [exp2], timeout: 1.0)
        XCTAssertEqual(registry.providers.count, 0)
    }

    func test_searchAll_returnsResultsFromAllProviders() async {
        let registry = ComponentProviderRegistry()
        let provider1 = MockComponentProvider(
            name: "p1", displayName: "Provider 1",
            capabilities: [.pricing],
            mockResults: [
                UnifiedComponent(partNumber: "STM32F411", manufacturer: "ST", description: "MCU"),
            ],
            mockAvailability: .available
        )
        let provider2 = MockComponentProvider(
            name: "p2", displayName: "Provider 2",
            capabilities: [.pricing],
            mockResults: [
                UnifiedComponent(partNumber: "STM32F407", manufacturer: "ST", description: "MCU"),
            ],
            mockAvailability: .available
        )
        registry.register(provider1)
        registry.register(provider2)
        let exp = expectation(description: "registered")
        DispatchQueue.main.async { exp.fulfill() }
        await fulfillment(of: [exp], timeout: 1.0)

        let results = await registry.searchAll(keyword: "STM32")
        XCTAssertEqual(results.count, 2)
    }

    func test_searchAll_isolatesProviderErrors() async {
        struct FailingProvider: ComponentDataProvider {
            let name = "failing"
            let displayName = "Failing"
            let capabilities: Set<ProviderCapability> = []
            let availability: ProviderAvailability = .available
            func search(keyword: String) async throws -> [UnifiedComponent] {
                throw URLError(.badServerResponse)
            }
            func getDetails(partNumber: String) async throws -> UnifiedComponent? { nil }
        }

        let registry = ComponentProviderRegistry()
        registry.register(FailingProvider())
        registry.register(MockComponentProvider(
            name: "good", displayName: "Good",
            capabilities: [.pricing],
            mockResults: [UnifiedComponent(partNumber: "OK", manufacturer: "X", description: "works")],
            mockAvailability: .available
        ))
        let exp = expectation(description: "registered")
        DispatchQueue.main.async { exp.fulfill() }
        await fulfillment(of: [exp], timeout: 1.0)

        let results = await registry.searchAll(keyword: "OK")
        // Failing provider should not crash the search — good provider's results still arrive
        XCTAssertEqual(results.count, 1)
        XCTAssertEqual(results.first?.partNumber, "OK")
    }
}
