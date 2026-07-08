//
//  FindingResolutionTests.swift
//  KiCadAgentTests
//
//  Phase 169 — Obdurate Runtime
//

import Testing
import Foundation
@testable import KiCadAgent

@Suite("FindingResolution")
struct FindingResolutionTests {

    @Test("IMPLEMENTED with evidence tracks successfully")
    func implementedWithEvidence() throws {
        let tracker = FindingResolutionTracker()
        let r = try tracker.track(
            findingId: "T-169-01",
            state: .implemented,
            severity: .low,
            evidence: "abc1234"
        )
        #expect(r.state == .implemented)
        #expect(tracker.get("T-169-01") != nil)
    }

    @Test("P0 cannot DEFER")
    func p0CannotDefer() {
        let tracker = FindingResolutionTracker()
        #expect(throws: ResolutionValidationError.self) {
            try tracker.track(
                findingId: "P0-01",
                state: .deferredToNamedTarget,
                severity: .critical,
                triggerCondition: "Phase 200"
            )
        }
    }

    @Test("P1 cannot SUPERSEDE without production-hardened evidence")
    func p1CannotSupersede() {
        let tracker = FindingResolutionTracker()
        #expect(throws: ResolutionValidationError.self) {
            try tracker.track(
                findingId: "P1-02",
                state: .supersededByAlternative,
                severity: .high
                // missing alternativeName + autoPromoteTrigger
            )
        }
    }

    @Test("P3 can DEFER with trigger")
    func p3CanDefer() throws {
        let tracker = FindingResolutionTracker()
        try tracker.track(
            findingId: "P3-03",
            state: .deferredToNamedTarget,
            severity: .low,
            triggerCondition: "Phase 200"
        )
        #expect(tracker.get("P3-03")?.state == .deferredToNamedTarget)
    }

    @Test("ADDED_AS_PHASE requires phaseTarget")
    func addedAsPhaseRequiresTarget() {
        let tracker = FindingResolutionTracker()
        #expect(throws: ResolutionValidationError.self) {
            try tracker.track(
                findingId: "T-169-02",
                state: .addedAsPhase,
                severity: .medium
            )
        }
    }

    @Test("IMPLEMENTED requires evidence")
    func implementedRequiresEvidence() {
        let tracker = FindingResolutionTracker()
        #expect(throws: ResolutionValidationError.self) {
            try tracker.track(
                findingId: "T-169-03",
                state: .implemented,
                severity: .medium
            )
        }
    }

    @Test("summary() counts states")
    func summary() throws {
        let tracker = FindingResolutionTracker()
        try tracker.track(findingId: "a", state: .implemented,
                          severity: .low, evidence: "x")
        try tracker.track(findingId: "b", state: .implemented,
                          severity: .low, evidence: "y")
        try tracker.track(findingId: "c", state: .addedAsPhase,
                          severity: .medium, phaseTarget: "Phase 169")
        let s = tracker.summary()
        #expect(s[.implemented] == 2)
        #expect(s[.addedAsPhase] == 1)
    }

    @Test("isValidCombination predicate")
    func isValidCombination() {
        #expect(FindingResolutionTracker.isValidCombination(
            severity: .low, state: .deferredToNamedTarget) == true)
        #expect(FindingResolutionTracker.isValidCombination(
            severity: .critical, state: .deferredToNamedTarget) == false)
        #expect(FindingResolutionTracker.isValidCombination(
            severity: .high, state: .supersededByAlternative) == false)
    }

    @Test("byState query filters correctly")
    func byState() throws {
        let tracker = FindingResolutionTracker()
        try tracker.track(findingId: "a", state: .implemented,
                          severity: .low, evidence: "x")
        try tracker.track(findingId: "b", state: .addedAsPhase,
                          severity: .medium, phaseTarget: "Phase 169")
        #expect(tracker.byState(.implemented).count == 1)
        #expect(tracker.byState(.addedAsPhase).count == 1)
    }

    @Test("SUPERSEDED with alternative name + trigger is valid for P3")
    func supersededValid() throws {
        let tracker = FindingResolutionTracker()
        try tracker.track(
            findingId: "P3-04",
            state: .supersededByAlternative,
            severity: .low,
            alternativeName: "Existing utility",
            autoPromoteTrigger: "2026-08-01T00:00:00Z"
        )
        #expect(tracker.get("P3-04")?.alternativeName == "Existing utility")
    }
}
