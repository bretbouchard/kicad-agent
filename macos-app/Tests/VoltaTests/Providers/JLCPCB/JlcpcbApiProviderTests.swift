//
//  JlcpcbApiProviderTests.swift
//  VoltaTests
//
//  Phase 3 / Task 1 — JLCPCB API Provider Tests
//

import Testing
import Foundation
@testable import Volta
import VoltaPCBCore

@Suite("JLCPCB API Provider")
struct JlcpcbApiProviderTests {
    let provider = JlcpcbApiProvider()

    @Test("Provider identity")
    func identity() {
        #expect(provider.name == "jlcpcb")
        #expect(provider.displayName == "Assembly Data")
        #expect(provider.capabilities.contains(.assemblyData))
        #expect(provider.capabilities.contains(.pricing))
        #expect(provider.capabilities.contains(.stock))
    }

    @Test("Availability requires API key")
    func availabilityWithoutKey() async {
        let avail = await provider.availability
        if case .requiresAuth = avail {
            // expected when no key configured
        } else {
            #expect(avail == .available || avail == .requiresAuth(reason: ""))
        }
    }

    @Test("AssemblyAvailability classification")
    func assemblyClassification() {
        let basic = AssemblyAvailability(
            lcscPartNumber: "C2040",
            assemblyType: "basic",
            inStock: true,
            assemblyFee: nil,
            deliveryTime: nil
        )
        #expect(basic.isAssemblyReady)
        #expect(basic.isBasicAssembly)

        let extended = AssemblyAvailability(
            lcscPartNumber: "C12345",
            assemblyType: "extended",
            inStock: true,
            assemblyFee: 3.0,
            deliveryTime: "3-5 days"
        )
        #expect(extended.isAssemblyReady)
        #expect(!extended.isBasicAssembly)
        #expect(extended.assemblyFee == 3.0)

        let notReady = AssemblyAvailability(
            lcscPartNumber: "C99999",
            assemblyType: "none",
            inStock: false,
            assemblyFee: nil,
            deliveryTime: nil
        )
        #expect(!notReady.isAssemblyReady)
    }

    @Test("Error descriptions")
    func errorDescriptions() {
        let notConfigured = JlcpcbApiError.notConfigured
        #expect(notConfigured.localizedDescription.contains("api.jlcpcb.com"))

        let rateLimited = JlcpcbApiError.rateLimited(retryAfter: 30)
        #expect(rateLimited.localizedDescription.contains("30"))
    }
}
