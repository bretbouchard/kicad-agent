//
//  QualityTestingTests.swift
//  KiCadAgentTests
//
//  Phase 191 + 192 + 193 + 194 + 195 — Track H Quality first half
//

import Testing
import Foundation
import SwiftUI
@testable import KiCadAgent

@Suite("Quality Track H (191-195)", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil))
struct QualityTestingTests {

    // MARK: - Phase 191 — swift-testing Framework

    @Test("TestRegistry lists all known test files", .tags(.smoke))
    func registryListsTests() {
        #expect(TestRegistry.allTestFiles.contains("LiquidGlassShellTests"))
        #expect(TestRegistry.allTestFiles.contains("InlineRenderingTests"))
        #expect(TestRegistry.allTestFiles.count >= 25)
    }

    @Test("CoverageGate minimumCoverage is 0.80")
    func coverageGateMinimum() {
        #expect(CoverageGate.minimumCoverage == 0.80)
    }

    @Test("CoverageGate per-layer minimums include Models at 0.90")
    func perLayerMinimums() {
        #expect(CoverageGate.perLayerMinimums["Models"] == 0.90)
        #expect(CoverageGate.perLayerMinimums["Governance"] == 0.95)
        #expect(CoverageGate.perLayerMinimums["UI"] == 0.70)
    }

    // MARK: - Phase 192 — Snapshot Testing (4-variant)

    @Test("SnapshotAssertions.assert4Variants passes for simple view", .tags(.snapshot, .a11y))
    func snapshot4Variants() {
        SnapshotAssertions.assert4Variants(Text("Hello"))
    }

    @Test("SnapshotAssertions.assertTrait passes with name", .tags(.snapshot))
    func snapshotTrait() {
        SnapshotAssertions.assertTrait(Text("test"), trait: "light-mode")
    }

    @Test("SnapshotAssertions works with complex view", .tags(.snapshot, .a11y))
    func snapshotComplexView() {
        let view = VStack {
            Text("Title").font(.title)
            Text("Body").font(.body)
            Button("Action") {}
        }
        SnapshotAssertions.assert4Variants(view)
    }

    // MARK: - Phase 193 — Property-Based Testing

    @Test("PRNG produces deterministic sequence from fixed seed", .tags(.property))
    func prngDeterministic() {
        var rng1 = PRNG(seed: 0xCAFE_BABE)
        var rng2 = PRNG(seed: 0xCAFE_BABE)
        for _ in 0..<10 {
            #expect(rng1.next() == rng2.next())
        }
    }

    @Test("PRNG.int stays within range", .tags(.property))
    func prngInRange() {
        PropertyTesting.check("int(in: 5...10) returns 5-10", iterations: 200) { rng in
            let v = rng.int(in: 5...10)
            return (5...10).contains(v)
        }
    }

    @Test("PRNG.bool returns roughly 50/50 distribution", .tags(.property))
    func prngBoolDistribution() {
        var rng = PRNG(seed: 0xDEAD_BEEF)
        var trues = 0
        let total = 1000
        for _ in 0..<total {
            if rng.bool() { trues += 1 }
        }
        // Allow ±10% deviation.
        #expect(trues > 400 && trues < 600)
    }

    @Test("PRNG.string produces exact length", .tags(.property))
    func prngStringLength() {
        var rng = PRNG(seed: 0x1234)
        for length in [1, 5, 100, 1000] {
            let s = rng.string(length: length)
            #expect(s.count == length)
        }
    }

    @Test("Property testing can verify SpecValidator rejects long inputs", .tags(.property))
    func propertySpecValidator() {
        PropertyTesting.check("SpecValidator rejects >1000 chars", iterations: 50) { rng in
            let length = rng.int(in: 1001...5000)
            let text = String(repeating: "a", count: length)
            return SpecValidator.isWithinLength(text) == false
        }
    }

    @Test("Property testing can verify SpecValidator accepts short inputs", .tags(.property))
    func propertySpecValidatorAccepts() {
        PropertyTesting.check("SpecValidator accepts <=1000 chars", iterations: 50) { rng in
            let length = rng.int(in: 0...1000)
            let text = String(repeating: "a", count: length)
            return SpecValidator.isWithinLength(text)
        }
    }

    // MARK: - Phase 194 — Mutation Testing

    @Test("MutationTesting.assertIdempotent catches non-idempotent transforms", .tags(.mutation))
    func mutationIdempotent() {
        MutationTesting.assertIdempotent("uppercase", input: "hello", transform: { $0.uppercased() })
    }

    @Test("MutationTesting.report computes mutation score", .tags(.mutation))
    func mutationReport() {
        let report = MutationTesting.MutationReport(totalMutants: 100, killed: 95, survived: 5, timedOut: 0)
        #expect(report.mutationScore == 0.95)
        #expect(report.passesGate == true)
    }

    @Test("MutationTesting.report fails gate below 0.90", .tags(.mutation))
    func mutationReportFails() {
        let report = MutationTesting.MutationReport(totalMutants: 100, killed: 80, survived: 20, timedOut: 0)
        #expect(report.mutationScore == 0.80)
        #expect(report.passesGate == false)
    }

    @Test("HighCoveragePatterns round-trip works for Codable structs", .tags(.mutation))
    func roundTripCodable() throws {
        struct Point: Codable, Equatable { let x, y: Int }
        let p = Point(x: 3, y: 4)
        try HighCoveragePatterns.assertRoundTrip(p)
    }

    @Test("HighCoveragePatterns boundary checks value in range", .tags(.mutation))
    func boundaryCheck() {
        HighCoveragePatterns.assertBoundary(50, min: 0, max: 100)
    }

    // MARK: - Phase 195 — Accessibility Testing

    @Test("AccessibilityAssertions.assertAccessible passes for labeled view", .tags(.a11y))
    func a11yLabeled() {
        AccessibilityAssertions.assertAccessible(
            Button("Hello") {},
            label: "Greeting button",
            hint: "Tap to say hi"
        )
    }

    @Test("AccessibilityAssertions.assertDynamicTypeScales passes", .tags(.a11y))
    func a11yDynamicType() {
        AccessibilityAssertions.assertDynamicTypeScales(Text("Test"))
    }

    @Test("AccessibilityAssertions.assertReducePrefsRespected passes", .tags(.a11y))
    func a11yReducePrefs() {
        AccessibilityAssertions.assertReducePrefsRespected(Text("Test"))
    }

    @Test("AccessibilityReport computes coverage", .tags(.a11y))
    func a11yReportCoverage() {
        let report = AccessibilityReport(total: 10, labels: 10, hints: 8, traits: 7)
        #expect(report.labelCoverage == 1.0)
        #expect(report.passesA11Y01 == true)
    }

    @Test("AccessibilityReport fails A11Y-01 when labels missing", .tags(.a11y))
    func a11yReportFails() {
        let report = AccessibilityReport(total: 10, labels: 9, hints: 5, traits: 5)
        #expect(report.passesA11Y01 == false)
    }
}
