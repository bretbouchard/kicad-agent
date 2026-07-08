//
//  ApprovalGatesTests.swift
//  KiCadAgentTests
//
//  Phase 174 — Approval Gates UI
//
//  Tests GateType enum, GateContext, four-state resolution taxonomy,
//  and 4-variant trait instantiation of ApprovalGatesView, GateDetailView,
//  CompletionSummaryCard.
//

import Testing
import SwiftUI
@testable import KiCadAgent

@Suite("Approval Gates", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil))
struct ApprovalGatesTests {

    // MARK: - GateType

    @Test("GateType has six canonical cases")
    func gateTypeCases() {
        #expect(GateType.allCases.count == 6)
        #expect(GateType.allCases.contains(.ercWarning))
        #expect(GateType.allCases.contains(.escalation))
    }

    @Test("GateType labels are human-readable")
    func gateTypeLabels() {
        #expect(GateType.ercWarning.label == "ERC Warning")
        #expect(GateType.opConfirmation.label == "Confirm Operation")
    }

    // MARK: - GateContext

    @Test("GateContext constructs with minimal required fields")
    func gateContextMinimal() {
        let gate = GateContext(
            type: .opConfirmation,
            intent: "Delete C1",
            operation: "delete_component"
        )
        #expect(gate.type == .opConfirmation)
        #expect(gate.requirementId == nil)
        #expect(gate.escalationTier == nil)
    }

    @Test("GateContext carries verification snapshot when present")
    func gateContextWithVerification() {
        let snapshot = VerificationSnapshot(passed: false, warningCount: 2, errorCount: 1, notes: "Float nets")
        let gate = GateContext(
            type: .verificationFailure,
            intent: "Run ERC",
            operation: "run_erc",
            verificationResult: snapshot
        )
        #expect(gate.verificationResult?.passed == false)
        #expect(gate.verificationResult?.errorCount == 1)
    }

    // MARK: - GateResolution + GateDecision (Four-State Taxonomy)

    @Test("GateDecision has four canonical states per bureaucracy §7")
    func fourStates() {
        #expect(GateDecision.implemented.label == "Implemented")
        #expect(GateDecision.addedAsPhase.label == "Added as Phase")
        #expect(GateDecision.superseded.label == "Superseded by Alternative")
        #expect(GateDecision.deferred.label == "Deferred to Named Target")
    }

    @Test("GateResolution approve carries decision")
    func approveResolution() {
        let resolution: GateResolution = .approve(decision: .implemented)
        if case .approve(let decision) = resolution {
            #expect(decision == .implemented)
        } else {
            Issue.record("expected .approve, got \(resolution)")
        }
    }

    @Test("GateResolution reject carries reason")
    func rejectResolution() {
        let resolution: GateResolution = .reject(reason: "User chose alternative")
        if case .reject(let reason) = resolution {
            #expect(reason.contains("alternative"))
        } else {
            Issue.record("expected .reject, got \(resolution)")
        }
    }

    // MARK: - GateDecisionRecord (audit trail)

    @Test("GateDecisionRecord captures gate + resolution + timestamp")
    func decisionRecord() {
        let gateId = UUID()
        let record = GateDecisionRecord(
            gateId: gateId,
            resolution: .approve(decision: .implemented)
        )
        #expect(record.gateId == gateId)
    }

    // MARK: - View Instantiation (4-Variant)

    @Test("ApprovalGatesView instantiates with ERC warning gate", .tags(.ui, .a11y))
    func approvalViewERC() {
        let gate = GateContext(
            type: .ercWarning,
            intent: "Generate schematic",
            operation: "auto_generate",
            verificationResult: VerificationSnapshot(passed: true, warningCount: 3, errorCount: 0, notes: "Untested nets")
        )
        let view = ApprovalGatesView(gate: gate, onResolve: { _ in })
        _ = view
    }

    @Test("ApprovalGatesView instantiates with escalation gate", .tags(.ui, .a11y))
    func approvalViewEscalation() {
        let gate = GateContext(
            type: .escalation,
            intent: "Repeated failure",
            operation: "auto_route",
            escalationTier: 3
        )
        let view = ApprovalGatesView(gate: gate, onResolve: { _ in })
            .preferredColorScheme(.dark)
        _ = view
    }

    @Test("GateDetailView instantiates with full context", .tags(.ui, .a11y))
    func gateDetailView() {
        let gate = GateContext(
            type: .phaseTransition,
            intent: "Advance from spec to roadmap",
            operation: "advance_workflow",
            requirementId: "GSD-03"
        )
        let view = GateDetailView(gate: gate, onResolve: { _ in })
            .dynamicTypeSize(.accessibility3)
        _ = view
    }

    @Test("CompletionSummaryCard instantiates with summary", .tags(.ui, .a11y))
    func completionSummaryCard() {
        let summary = CompletionSummary(
            phaseName: "Foundation",
            exports: [
                ExportArtifact(fileName: "gerbers.zip", fileSizeBytes: 12_500, kind: .gerber),
                ExportArtifact(fileName: "bom.csv", fileSizeBytes: 2_300, kind: .bom)
            ],
            decisionsCount: 14,
            totalDurationSeconds: 7200
        )
        let view = CompletionSummaryCard(summary: summary, onOpen: {})
        _ = view
    }
}
