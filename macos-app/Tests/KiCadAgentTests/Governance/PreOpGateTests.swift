//
//  PreOpGateTests.swift
//  KiCadAgentTests
//
//  Phase 170 — Verification Loop Integration (GOV-03)
//

import Testing
import Foundation
@testable import KiCadAgent

@MainActor
@Suite("PreOpGate")
struct PreOpGateTests {

    // MARK: - Local decision branches (no daemon)

    @Test("Empty op name blocks immediately")
    func emptyOpBlocks() async {
        let gate = PreOpGate(client: nil)
        let intent = IntentResult(
            op: "",
            args: [:],
            requirementId: "GOV-01",
            intent: "test",
            targetFiles: [],
            isReadonly: false
        )
        let result = await gate.check(intent: intent, args: [:])
        #expect(result.decision == .block)
        #expect(result.checks["intent_valid"] == false)
    }

    @Test("Read-only ops short-circuit to allow")
    func readOnlyShortCircuit() async {
        let gate = PreOpGate(client: nil)
        let intent = IntentResult(
            op: "query_components",
            args: [:],
            requirementId: "GOV-11",
            intent: "query",
            targetFiles: [],
            isReadonly: true
        )
        let result = await gate.check(intent: intent, args: [:])
        #expect(result.decision == .allow)
        #expect(result.reasons.contains(where: { $0.contains("read-only") }))
    }

    @Test("No MCPClient warns instead of blocking")
    func noClientWarns() async {
        let gate = PreOpGate(client: nil)
        let intent = IntentResult(
            op: "add_component",
            args: ["target_file": AnyCodable("/tmp/x.kicad_sch")],
            requirementId: "GOV-01",
            intent: "add R1",
            targetFiles: ["/tmp/x.kicad_sch"],
            isReadonly: false
        )
        let result = await gate.check(
            intent: intent,
            args: ["target_file": "/tmp/x.kicad_sch"]
        )
        #expect(result.decision == .warn)
        #expect(result.checks["client_wired"] == false)
    }

    // MARK: - Decoding

    @Test("Decode allow response")
    func decodeAllow() {
        let raw: [String: Any] = [
            "decision": "allow",
            "reasons": [],
            "op_type": "add_component",
            "checks": ["op_known": true, "file_type_ok": true],
        ]
        let result = PreOpGate.decode(raw: raw, fallbackOp: "add_component")
        #expect(result.decision == .allow)
        #expect(result.opType == "add_component")
        #expect(result.checks["op_known"] == true)
    }

    @Test("Decode block response carries reasons")
    func decodeBlock() {
        let raw: [String: Any] = [
            "decision": "block",
            "reasons": ["unsupported suffix '.txt'"],
            "op_type": "add_component",
            "checks": ["file_type_ok": false],
        ]
        let result = PreOpGate.decode(raw: raw, fallbackOp: "add_component")
        #expect(result.decision == .block)
        #expect(result.reasons.contains("unsupported suffix '.txt'"))
    }

    @Test("Decode defaults to block on unknown decision string")
    func decodeUnknownDefaultsBlock() {
        let raw: [String: Any] = ["decision": "bogus"]
        let result = PreOpGate.decode(raw: raw, fallbackOp: "x")
        #expect(result.decision == .block)
    }

    @Test("Decode non-dict response blocks")
    func decodeNonDict() {
        let result = PreOpGate.decode(raw: "garbage", fallbackOp: "x")
        #expect(result.decision == .block)
        #expect(result.opType == "x")
    }

    // MARK: - shouldExecute

    @Test("shouldExecute true for allow and warn, false for block")
    func shouldExecuteMatrix() {
        let allow = PreOpResult(decision: .allow, reasons: [], opType: "x", checks: [:])
        let warn = PreOpResult(decision: .warn, reasons: [], opType: "x", checks: [:])
        let block = PreOpResult(decision: .block, reasons: [], opType: "x", checks: [:])
        #expect(allow.shouldExecute)
        #expect(warn.shouldExecute)
        #expect(!block.shouldExecute)
    }
}
