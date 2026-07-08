//
//  WorkflowStateMachineTests.swift
//  KiCadAgentTests
//
//  Phase 169 — Obdurate Runtime
//
//  Tests all valid transitions, rejects invalid transitions and guard
//  failures. Mirrors bureaucracy.md §1 transition table.
//

import Testing
import Foundation
@testable import KiCadAgent

@Suite("WorkflowStateMachine")
struct WorkflowStateMachineTests {

    // MARK: - Valid transitions

    @Test("Initial state is questioning")
    func initialState() {
        let m = WorkflowStateMachine()
        #expect(m.state == .questioning)
    }

    @Test("Valid forward transitions succeed")
    func validForwardPath() throws {
        let m = WorkflowStateMachine()
        try m.transition(.questionToSpec)
        #expect(m.state == .specGenerated)
        try m.transition(.specToRoadmap)
        #expect(m.state == .roadmapApproved)
        try m.transition(.reviewToExecute, planApproved: true)
        #expect(m.state == .executing)
        try m.transition(.executeToVerifying)
        #expect(m.state == .verifying)
        try m.transition(.verifyingToComplete, verificationPassed: true)
        #expect(m.state == .complete)
    }

    @Test("reset() returns to questioning from anywhere")
    func resetWorks() throws {
        let m = WorkflowStateMachine()
        m.forceState(.complete)
        try m.transition(.reset)
        #expect(m.state == .questioning)
        #expect(m.planApproved == false)
        #expect(m.verificationPassed == false)
    }

    @Test("verifyingBackToExecute clears verificationPassed")
    func backToExecute() throws {
        let m = WorkflowStateMachine()
        m.forceState(.verifying)
        try m.transition(.verifyingBackToExecute)
        #expect(m.state == .executing)
        #expect(m.verificationPassed == false)
    }

    // MARK: - Invalid transitions

    @Test("Invalid transition throws")
    func invalidTransition() throws {
        let m = WorkflowStateMachine()   // questioning
        #expect(throws: WorkflowStateMachineError.self) {
            try m.transition(.executeToVerifying)
        }
        #expect(m.state == .questioning)   // unchanged
    }

    @Test("reviewToExecute without planApproved throws")
    func planApprovedGuard() throws {
        let m = WorkflowStateMachine()
        try m.transition(.questionToSpec)
        try m.transition(.specToRoadmap)
        #expect(throws: WorkflowStateMachineError.self) {
            try m.transition(.reviewToExecute)   // no planApproved
        }
        #expect(m.state == .roadmapApproved)   // unchanged
    }

    @Test("verifyingToComplete without verificationPassed throws")
    func verificationGuard() throws {
        let m = WorkflowStateMachine()
        m.forceState(.verifying)
        #expect(throws: WorkflowStateMachineError.self) {
            try m.transition(.verifyingToComplete)   // no verificationPassed
        }
        #expect(m.state == .verifying)   // unchanged
    }

    @Test("canTransition predicates match the guards")
    func predicates() throws {
        let m = WorkflowStateMachine()
        try m.transition(.questionToSpec)
        try m.transition(.specToRoadmap)
        #expect(m.canTransition(.reviewToExecute, planApproved: true))
        #expect(!m.canTransition(.reviewToExecute, planApproved: false))
        m.forceState(.verifying)
        #expect(m.canTransition(.verifyingToComplete, verificationPassed: true))
        #expect(!m.canTransition(.verifyingToComplete, verificationPassed: false))
    }

    // MARK: - Snapshot / restore

    @Test("Snapshot round-trips through restore")
    func snapshotRestore() throws {
        let m = WorkflowStateMachine()
        m.forceState(.executing)
        let snap = m.snapshot()
        let m2 = WorkflowStateMachine()
        try m2.restore(snap)
        #expect(m2.state == .executing)
        #expect(m2.planApproved == true)
    }

    @Test("restore rejects executing-without-planApproved")
    func restoreInvariant() throws {
        let m = WorkflowStateMachine()
        let badSnapshot = WorkflowStateMachine.Snapshot(
            state: .executing, planApproved: false, verificationPassed: false)
        #expect(throws: WorkflowStateMachineError.self) {
            try m.restore(badSnapshot)
        }
    }

    // MARK: - State predicates

    @Test("State predicates allow/deny ops correctly")
    func statePredicates() {
        #expect(WorkflowState.questioning.allowsMutation == false)
        #expect(WorkflowState.executing.allowsMutation == true)
        #expect(WorkflowState.questioning.allowsReadonlyOps == false)
        #expect(WorkflowState.roadmapApproved.allowsReadonlyOps == true)
        #expect(WorkflowState.complete.allowsReadonlyOps == true)
    }
}
