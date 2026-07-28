//
//  RoutingProviderRegistryTests.swift
//  VoltaTests
//
//  Phase 253 Task 1 — Routing Provider Registry Tests
//
//  Locks the RoutingProviderRegistry contract:
//    - register() adds providers, dedup by name
//    - unregister() removes by name
//    - provider(named:) returns the registered provider by name
//    - probeAvailability() populates the availability cache without
//      blocking forever if a provider hangs
//
//  Mirrors the ComponentProviderRegistryTests shape. MockRoutingProvider
//  lives next door; the registry lives in Volta so we @testable import both.
//

import XCTest
@testable import Volta
@testable import VoltaPCBCore

final class RoutingProviderRegistryTests: XCTestCase {

    func test_register_addsProvider() {
        let registry = RoutingProviderRegistry()
        let provider = MockRoutingProvider(
            name: "mock",
            displayName: "Mock Router"
        )
        registry.register(provider)
        let exp = expectation(description: "provider registered")
        DispatchQueue.main.async { exp.fulfill() }
        wait(for: [exp], timeout: 1.0)
        XCTAssertEqual(registry.providers.count, 1)
        XCTAssertEqual(registry.providers.first?.name, "mock")
    }

    func test_register_dedupByName() {
        let registry = RoutingProviderRegistry()
        registry.register(MockRoutingProvider(name: "freerouting", displayName: "Freerouting"))
        registry.register(MockRoutingProvider(name: "freerouting", displayName: "Freerouting Duplicate"))
        let exp = expectation(description: "dedup")
        DispatchQueue.main.async { exp.fulfill() }
        wait(for: [exp], timeout: 1.0)
        XCTAssertEqual(registry.providers.count, 1)
        XCTAssertEqual(registry.providers.first?.displayName, "Freerouting")
    }

    func test_unregister_removesProvider() {
        let registry = RoutingProviderRegistry()
        registry.register(MockRoutingProvider(name: "mock", displayName: "Mock"))
        let exp1 = expectation(description: "registered")
        DispatchQueue.main.async { exp1.fulfill() }
        wait(for: [exp1], timeout: 1.0)

        registry.unregister(name: "mock")
        let exp2 = expectation(description: "unregistered")
        DispatchQueue.main.async { exp2.fulfill() }
        wait(for: [exp2], timeout: 1.0)
        XCTAssertEqual(registry.providers.count, 0)
    }

    func test_provider_named_lookup() {
        let registry = RoutingProviderRegistry()
        let freerouting = MockRoutingProvider(name: "freerouting", displayName: "Freerouting")
        let kicad = MockRoutingProvider(name: "kicad-native", displayName: "KiCad Native")
        registry.register(freerouting)
        registry.register(kicad)
        let exp = expectation(description: "registered")
        DispatchQueue.main.async { exp.fulfill() }
        wait(for: [exp], timeout: 1.0)

        let resolved = registry.provider(named: "kicad-native")
        XCTAssertNotNil(resolved)
        XCTAssertEqual(resolved?.displayName, "KiCad Native")

        XCTAssertNil(registry.provider(named: "missing"))
    }

    func test_probeAvailability_populatesCacheForAvailableProvider() async {
        let registry = RoutingProviderRegistry()
        registry.register(MockRoutingProvider(
            name: "available",
            displayName: "Available Router",
            mockAvailability: .available
        ))
        let exp = expectation(description: "registered")
        DispatchQueue.main.async { exp.fulfill() }
        await fulfillment(of: [exp], timeout: 1.0)

        await registry.probeAvailability()
        let cached = registry.lastKnownAvailability(for: "available")
        XCTAssertEqual(cached, .available)
        XCTAssertEqual(registry.availableProviders.count, 1)
    }

    func test_probeAvailability_marksUnavailableProvider() async {
        let registry = RoutingProviderRegistry()
        registry.register(MockRoutingProvider(
            name: "needs-auth",
            displayName: "Needs Auth",
            mockAvailability: .requiresAuth(reason: "No API key")
        ))
        let exp = expectation(description: "registered")
        DispatchQueue.main.async { exp.fulfill() }
        await fulfillment(of: [exp], timeout: 1.0)

        await registry.probeAvailability()
        let cached = registry.lastKnownAvailability(for: "needs-auth")
        XCTAssertEqual(cached, .requiresAuth(reason: "No API key"))
        XCTAssertEqual(registry.availableProviders.count, 0)
    }

    func test_lastKnownAvailability_returnsNilBeforeProbe() {
        let registry = RoutingProviderRegistry()
        registry.register(MockRoutingProvider(name: "mock", displayName: "Mock"))
        let exp = expectation(description: "registered")
        DispatchQueue.main.async { exp.fulfill() }
        wait(for: [exp], timeout: 1.0)

        // No probe yet → cache miss
        XCTAssertNil(registry.lastKnownAvailability(for: "mock"))
    }

    func test_unregister_clearsAvailabilityCache() async {
        let registry = RoutingProviderRegistry()
        registry.register(MockRoutingProvider(name: "mock", displayName: "Mock"))
        let exp1 = expectation(description: "registered")
        DispatchQueue.main.async { exp1.fulfill() }
        await fulfillment(of: [exp1], timeout: 1.0)

        await registry.probeAvailability()
        XCTAssertNotNil(registry.lastKnownAvailability(for: "mock"))

        registry.unregister(name: "mock")
        let exp2 = expectation(description: "unregistered")
        DispatchQueue.main.async { exp2.fulfill() }
        await fulfillment(of: [exp2], timeout: 1.0)

        XCTAssertNil(registry.lastKnownAvailability(for: "mock"))
    }
}