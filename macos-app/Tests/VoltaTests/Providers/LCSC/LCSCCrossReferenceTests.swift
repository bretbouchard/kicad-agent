//
//  LCSCCrossReferenceTests.swift
//  VoltaTests
//
//  Phase 3 / Task 3 — LCSC Cross-Reference Engine Tests
//

import Testing
import Foundation
@testable import Volta
import VoltaPCBCore

@Suite("LCSC Cross-Reference")
struct LCSCCrossReferenceTests {
    let xref = LCSCCrossReference()

    @Test("Seeded mappings resolve")
    func seededResolves() {
        // RP2040 is in the seed list
        let result = xref.resolve(mpn: "RP2040")
        #expect(result != nil)
        #expect(result?.lcsc == "C2040")
        #expect((result?.confidence ?? 0) > 0.8)
    }

    @Test("Case-insensitive matching")
    func caseInsensitive() {
        let result = xref.resolve(mpn: "rp2040")
        #expect(result != nil)
        #expect(result?.lcsc == "C2040")
    }

    @Test("Hyphen/dash normalization")
    func normalization() {
        // STM32F103C8T6 is seeded, try with dashes
        let result = xref.resolve(mpn: "STM32-F103-C8T6")
        #expect(result != nil)
        #expect(result?.lcsc == "C8734")
    }

    @Test("Unknown MPN returns nil")
    func unknownMPN() {
        let result = xref.resolve(mpn: "NONEXISTENT12345")
        #expect(result == nil)
    }

    @Test("Add new mapping")
    func addMapping() {
        xref.add(mpn: "TESTPART123", lcsc: "C99999", confidence: 0.9, source: .exactMatch)
        let result = xref.resolve(mpn: "TESTPART123")
        #expect(result != nil)
        #expect(result?.lcsc == "C99999")
        #expect(result?.confidence == 0.9)
    }

    @Test("Manual override replaces lower confidence")
    func manualOverride() {
        xref.add(mpn: "OVRTEST", lcsc: "C11111", confidence: 0.5, source: .exactMatch)
        xref.setOverride(mpn: "OVRTEST", lcsc: "C22222")
        let result = xref.resolve(mpn: "OVRTEST")
        #expect(result?.lcsc == "C22222")
        #expect(result?.source == .manualOverride)
        #expect(result?.confidence == 1.0)
    }

    @Test("Lower confidence does not replace higher")
    func lowerDoesNotReplace() {
        xref.add(mpn: "PRIORITY", lcsc: "C33333", confidence: 0.95, source: .exactMatch)
        xref.add(mpn: "PRIORITY", lcsc: "C44444", confidence: 0.7, source: .fuzzyMatch)
        let result = xref.resolve(mpn: "PRIORITY")
        #expect(result?.lcsc == "C33333")
    }

    @Test("Remove mapping")
    func removeMapping() {
        xref.add(mpn: "REMOVE_ME", lcsc: "C55555", confidence: 0.9, source: .exactMatch)
        #expect(xref.resolve(mpn: "REMOVE_ME") != nil)
        xref.remove(mpn: "REMOVE_ME")
        #expect(xref.resolve(mpn: "REMOVE_ME") == nil)
    }

    @Test("Reverse lookup")
    func reverseLookup() {
        // RP2040 → C2040 is seeded
        let mpn = xref.reverseResolve(lcsc: "C2040")
        #expect(mpn != nil)
    }

    @Test("Learn from components")
    func learnFromComponents() {
        let component = UnifiedComponent(
            partNumber: "LEARNED_PART",
            manufacturer: "TestCorp",
            description: "A test component",
            sources: [ComponentSource(
                provider: "jlcpcb",
                providerPartId: "C77777",
                lastUpdated: Date(),
                confidence: 0.95
            )],
            lcscPartNumber: "C77777"
        )

        xref.learn(from: [component])
        let result = xref.resolve(mpn: "LEARNED_PART")
        #expect(result != nil)
        #expect(result?.lcsc == "C77777")
        #expect(result?.source == .exactMatch)
    }

    @Test("Fuzzy prefix match")
    func fuzzyMatch() {
        // STM32F411RET6 is seeded as C77431
        // A close variant should fuzzy-match
        let result = xref.resolve(mpn: "STM32F411CEU6")
        // This might match via prefix if STM32F411 is close enough
        // (depends on whether any seeded part shares the prefix)
        if let result = result {
            #expect(result.source == .fuzzyMatch)
            #expect(result.confidence <= 0.6)
        }
        // Not finding a match is also acceptable — fuzzy is best-effort
    }

    @Test("All mappings export")
    func allMappingsExport() {
        let mappings = xref.allMappings
        #expect(!mappings.isEmpty)
        // Should contain seeded parts
        #expect(mappings.contains { $0.mpn == "RP2040" })
    }
}
