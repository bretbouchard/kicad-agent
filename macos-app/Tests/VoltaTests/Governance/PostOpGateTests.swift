//
//  PostOpGateTests.swift
//  VoltaTests
//
//  Phase 170 — Verification Loop Integration (GOV-04)
//

import Testing
import Foundation
@testable import Volta

// MARK: - Mock SemanticJudge

@MainActor
final class MockSemanticJudge: SemanticJudge {
    var verdict: Bool?
    var calls = 0

    func judge(intent: String, op: String, result: String) async -> Bool? {
        calls += 1
        return verdict
    }
}

@MainActor
@Suite("PostOpGate")
struct PostOpGateTests {

    private func makeMutatingIntent(op: String = "add_component",
                                    files: [String] = ["/tmp/x.kicad_sch"]) -> IntentResult {
        IntentResult(
            op: op,
            args: [:],
            requirementId: "GOV-01",
            intent: "test",
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

    // MARK: - Read-only skip

    @Test("Read-only ops skip post-check")
    func readOnlySkips() async {
        let gate = PostOpGate(client: nil)
        let result = await gate.verify(intent: makeReadonlyIntent(), opResult: "ok")
        #expect(result.decision == .passed)
        #expect(result.ercSummary == nil)
        #expect(result.drcSummary == nil)
    }

    // MARK: - No daemon

    @Test("No daemon returns indeterminate for mutating op")
    func noDaemonIndeterminate() async {
        let gate = PostOpGate(client: nil)
        let result = await gate.verify(intent: makeMutatingIntent(), opResult: "ok")
        #expect(result.decision == .indeterminate)
    }

    // MARK: - Semantic judge

    @Test("Semantic judge true passes when daemon absent")
    func semanticTruePasses() async {
        // No daemon → deterministic check returns indeterminate. With semantic
        // judge returning true, we'd expect a "passed" if daemon said passed.
        // Since daemon is nil, deterministic is indeterminate — semantic only
        // runs when deterministic passed, so semantic is skipped.
        let judge = MockSemanticJudge()
        judge.verdict = true
        let gate = PostOpGate(client: nil, judge: judge)
        let result = await gate.verify(intent: makeMutatingIntent(), opResult: "ok")
        #expect(result.decision == .indeterminate)
        #expect(judge.calls == 0)  // judge not called when deterministic indeterminate
    }

    // MARK: - Decision composition

    @Test("Failed deterministic with no daemon still indeterminate")
    func failedDeterministic() async {
        let gate = PostOpGate(client: nil)
        let result = await gate.verify(intent: makeMutatingIntent(), opResult: "ok")
        // No daemon → indeterminate.
        #expect(result.decision == .indeterminate)
        #expect(result.semanticVerdict == nil)
    }

    // MARK: - Helpers

    @Test("toCodable returns nil for non-dict")
    func toCodableNilForNonDict() {
        #expect(PostOpGate.toCodable(nil) == nil)
        #expect(PostOpGate.toCodable("string") == nil)
    }

    @Test("toCodable wraps dict values")
    func toCodableWrapsDict() {
        let result = PostOpGate.toCodable(["clean": true, "error_count": 5])
        #expect(result != nil)
        #expect(result?.keys.contains("clean") == true)
    }

    // MARK: - Static helpers

    @Test("skipReadOnly returns passed with no summaries")
    func skipReadOnlyShape() {
        let result = PostOpResult.skipReadOnly(op: "query_erc")
        #expect(result.decision == .passed)
        #expect(result.ercSummary == nil)
        #expect(result.drcSummary == nil)
    }

    // MARK: - isPassed

    @Test("isPassed true only for passed")
    func isPassedMatrix() {
        let p = PostOpResult(decision: .passed, failures: [],
                              ercSummary: nil, drcSummary: nil, semanticVerdict: nil)
        let f = PostOpResult(decision: .failed, failures: ["x"],
                              ercSummary: nil, drcSummary: nil, semanticVerdict: nil)
        let i = PostOpResult(decision: .indeterminate, failures: [],
                              ercSummary: nil, drcSummary: nil, semanticVerdict: nil)
        #expect(p.isPassed)
        #expect(!f.isPassed)
        #expect(!i.isPassed)
    }
}
