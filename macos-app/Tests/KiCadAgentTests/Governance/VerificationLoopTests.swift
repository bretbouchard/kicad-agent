//
//  VerificationLoopTests.swift
//  KiCadAgentTests
//
//  Phase 170 — Verification Loop Integration (GOV-03, GOV-04, GOV-05)
//
//  End-to-end pipeline tests using mock gates + rollback. No live daemon.
//

import Testing
import Foundation
@testable import KiCadAgent

// MARK: - Test helpers — in-line gates that bypass the daemon

@MainActor
private final class TestPreOpGate: PreOpGate {
    private let forcedDecision: PreOpDecision

    init(forced: PreOpDecision) {
        self.forcedDecision = forced
        super.init(client: nil)
    }

    override func check(intent: IntentResult, args: [String: Any]) async -> PreOpResult {
        if intent.isReadonly { return .allowReadOnly(op: intent.op) }
        return PreOpResult(
            decision: forcedDecision,
            reasons: ["test override"],
            opType: intent.op,
            checks: ["test": true]
        )
    }
}

@MainActor
private final class TestPostOpGate: PostOpGate {
    private let forcedDecision: PostOpDecision

    init(forced: PostOpDecision) {
        self.forcedDecision = forced
        super.init(client: nil)
    }

    override func verify(intent: IntentResult, opResult: String) async -> PostOpResult {
        if intent.isReadonly { return .skipReadOnly(op: intent.op) }
        return PostOpResult(
            decision: forcedDecision,
            failures: forcedDecision == .failed ? ["test failure"] : [],
            ercSummary: nil, drcSummary: nil,
            semanticVerdict: nil
        )
    }
}

@MainActor
@Suite("VerificationLoop")
struct VerificationLoopTests {

    private func makeMutatingIntent(files: [String] = ["/tmp/x.kicad_sch"]) -> IntentResult {
        IntentResult(
            op: "add_component",
            args: [:],
            requirementId: "GOV-01",
            intent: "add R1",
            targetFiles: files,
            isReadonly: false
        )
    }

    private func makeReadonlyIntent() -> IntentResult {
        IntentResult(
            op: "query_components",
            args: [:],
            requirementId: "GOV-11",
            intent: "query",
            targetFiles: [],
            isReadonly: true
        )
    }

    // MARK: - Happy path

    @Test("Allow + execute + pass = passed outcome")
    func happyPath() async {
        let loop = VerificationLoop(
            preOpGate: TestPreOpGate(forced: .allow),
            postOpGate: TestPostOpGate(forced: .passed),
            rollback: Rollback(client: nil)
        )
        let outcome = await loop.run(
            intent: makeMutatingIntent(),
            args: ["target_file": "/tmp/x.kicad_sch"]
        ) {
            (result: AnyCodable(["ok": true]), summary: "added R1")
        }
        #expect(outcome.status == .passed)
        #expect(outcome.preOp.decision == .allow)
        #expect(outcome.postOp?.decision == .passed)
        #expect(outcome.restore == nil)
        #expect(outcome.checkpointId == Rollback.noClientSnapshotId)
        #expect(outcome.isCommitted)
        #expect(!outcome.didRollback)
    }

    // MARK: - Pre-op block

    @Test("Block = blocked outcome, executor never runs")
    func blockStopsExecution() async {
        var executorRan = false
        let loop = VerificationLoop(
            preOpGate: TestPreOpGate(forced: .block),
            postOpGate: TestPostOpGate(forced: .passed),
            rollback: Rollback(client: nil)
        )
        let outcome = await loop.run(
            intent: makeMutatingIntent(),
            args: [:]
        ) {
            executorRan = true
            return (result: AnyCodable(["ok": true]), summary: "should not run")
        }
        #expect(outcome.status == .blocked)
        #expect(outcome.result == nil)
        #expect(outcome.postOp == nil)
        #expect(!executorRan)
        #expect(!outcome.isCommitted)
    }

    // MARK: - Post-op failure + rollback

    @Test("Post-op failed triggers rollback")
    func failedTriggersRollback() async {
        let loop = VerificationLoop(
            preOpGate: TestPreOpGate(forced: .allow),
            postOpGate: TestPostOpGate(forced: .failed),
            rollback: Rollback(client: nil)
        )
        let outcome = await loop.run(
            intent: makeMutatingIntent(),
            args: [:]
        ) {
            (result: AnyCodable(["ok": true]), summary: "executed")
        }
        #expect(outcome.status == .failed)
        #expect(outcome.postOp?.decision == .failed)
        #expect(outcome.restore != nil)
        // restore with no client returns skipped = file count
        #expect(outcome.restore?.skipped == 1)
        #expect(outcome.didRollback)
        #expect(!outcome.isCommitted)
    }

    // MARK: - Indeterminate

    @Test("Post-op indeterminate commits (no rollback)")
    func indeterminateCommits() async {
        let loop = VerificationLoop(
            preOpGate: TestPreOpGate(forced: .allow),
            postOpGate: TestPostOpGate(forced: .indeterminate),
            rollback: Rollback(client: nil)
        )
        let outcome = await loop.run(
            intent: makeMutatingIntent(),
            args: [:]
        ) {
            (result: AnyCodable(["ok": true]), summary: "executed")
        }
        #expect(outcome.status == .indeterminate)
        #expect(outcome.restore == nil)
        #expect(outcome.isCommitted)
    }

    // MARK: - Execution failure

    @Test("Executor throws = executionFailed status")
    func executorThrows() async {
        let loop = VerificationLoop(
            preOpGate: TestPreOpGate(forced: .allow),
            postOpGate: TestPostOpGate(forced: .passed),
            rollback: Rollback(client: nil)
        )
        let outcome = await loop.run(
            intent: makeMutatingIntent(),
            args: [:]
        ) {
            throw MCPError.transport(message: "executor broken")
        }
        #expect(outcome.status == .executionFailed)
        #expect(outcome.postOp == nil)
        #expect(outcome.result == nil)
        #expect(!outcome.isCommitted)
    }

    // MARK: - Read-only

    @Test("Read-only intent skips checkpoint")
    func readOnlySkipsCheckpoint() async {
        let loop = VerificationLoop(
            preOpGate: TestPreOpGate(forced: .allow),
            postOpGate: TestPostOpGate(forced: .passed),
            rollback: Rollback(client: nil)
        )
        let outcome = await loop.run(
            intent: makeReadonlyIntent(),
            args: [:]
        ) {
            (result: AnyCodable(["count": 42]), summary: "queried")
        }
        #expect(outcome.checkpointId == nil)  // no files = no checkpoint
        #expect(outcome.status == .passed)
    }

    // MARK: - Empty target files (no checkpoint even for mutating op)

    @Test("Mutating op with empty target files has no checkpoint")
    func mutatingEmptyFiles() async {
        let loop = VerificationLoop(
            preOpGate: TestPreOpGate(forced: .allow),
            postOpGate: TestPostOpGate(forced: .passed),
            rollback: Rollback(client: nil)
        )
        let intent = IntentResult(
            op: "add_component", args: [:], requirementId: "GOV-01",
            intent: "test", targetFiles: [], isReadonly: false
        )
        let outcome = await loop.run(intent: intent, args: [:]) {
            (result: AnyCodable(["ok": true]), summary: "done")
        }
        #expect(outcome.checkpointId == nil)
        #expect(outcome.status == .passed)
    }

    // MARK: - Stage timings

    @Test("Stage timings captured")
    func stageTimings() async {
        let loop = VerificationLoop(
            preOpGate: TestPreOpGate(forced: .allow),
            postOpGate: TestPostOpGate(forced: .passed),
            rollback: Rollback(client: nil)
        )
        let outcome = await loop.run(
            intent: makeMutatingIntent(),
            args: [:]
        ) {
            (result: AnyCodable(["ok": true]), summary: "done")
        }
        #expect(outcome.stageTimingsMs["pre_op_ms"] != nil)
        #expect(outcome.stageTimingsMs["execute_ms"] != nil)
        #expect(outcome.stageTimingsMs["post_op_ms"] != nil)
    }
}
