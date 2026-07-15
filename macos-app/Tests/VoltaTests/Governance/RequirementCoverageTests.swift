//
//  RequirementCoverageTests.swift
//  VoltaTests
//
//  Phase 169 — Obdurate Runtime
//

import Testing
import Foundation
@testable import Volta

@Suite("RequirementCoverage")
struct RequirementCoverageTests {

    @Test("Coverage report references all catalog ops")
    func reportTotalOps() {
        let report = RequirementCoverage.report()
        #expect(report.totalOps == IntentGate.catalog.count)
    }

    @Test("Each catalog op is mapped to a requirement")
    func everyOpMapped() {
        let report = RequirementCoverage.report()
        let totalMapped = report.byRequirement.values.flatMap { $0 }.count
        #expect(totalMapped == IntentGate.catalog.count)
        #expect(report.orphanedOps.isEmpty)
    }

    @Test("Catalog covers the declared GOV requirements it ships with")
    func govsCovered() {
        let report = RequirementCoverage.report()
        // Phase 169 catalog covers GOV-01, GOV-02, GOV-11.
        #expect(report.byRequirement["GOV-01"]?.isEmpty == false)
        #expect(report.byRequirement["GOV-02"]?.isEmpty == false)
        #expect(report.byRequirement["GOV-11"]?.isEmpty == false)
    }

    @Test("Coverage percentage is positive")
    func coveragePositive() {
        let report = RequirementCoverage.report()
        #expect(report.requirementCoveragePct > 0)
    }

    @Test("Render produces a non-empty text report")
    func renderNonEmpty() {
        let report = RequirementCoverage.report()
        let text = report.render()
        #expect(text.contains("Requirement Coverage Report"))
        #expect(text.contains("GOV-01"))
    }

    @Test("declaredRequirements includes all GOV IDs")
    func declaredRequirementsComplete() {
        // Phase 169 ships GOV-01 through GOV-11.
        for i in 1...11 {
            let id = "GOV-\(String(format: "%02d", i))"
            #expect(RequirementCoverage.declaredRequirements.contains(id), "Missing \(id)")
        }
    }
}
