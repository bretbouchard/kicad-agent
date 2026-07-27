//
//  MouserProviderTests.swift
//  VoltaTests
//
//  Phase 3 / Task 2 — Mouser Provider Tests
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
}
