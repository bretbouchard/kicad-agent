//
//  IntentGateTests.swift
//  VoltaTests
//
//  Phase 169 — Obdurate Runtime
//

import Testing
import Foundation
@testable import Volta

@Suite("IntentGate")
struct IntentGateTests {

    let gate = IntentGate()

    @Test("Validate accepts known op with catalog requirement")
    func knownOpWithCatalogRequirement() throws {
        let result = try gate.validate(
            op: "add_component",
            args: ["target_file": "board.kicad_sch"],
            intent: "add R1"
        )
        #expect(result.op == "add_component")
        #expect(result.requirementId == "GOV-01")
        #expect(result.isReadonly == false)
        #expect(result.targetFiles == ["board.kicad_sch"])
    }

    @Test("Unknown op rejected")
    func unknownOpRejected() {
        #expect(throws: IntentGateError.self) {
            _ = try gate.validate(op: "fake_op", args: [:])
        }
    }

    @Test("Caller can override requirementId")
    func overrideRequirementId() throws {
        let result = try gate.validate(
            op: "add_component",
            args: [:],
            requirementId: "GOV-CUSTOM"
        )
        #expect(result.requirementId == "GOV-CUSTOM")
    }

    @Test("Empty requirementId on mutating op rejected")
    func emptyRequirementRejected() {
        #expect(throws: IntentGateError.self) {
            _ = try gate.validate(
                op: "add_component",
                args: [:],
                requirementId: ""
            )
        }
    }

    @Test("Readonly ops use GOV-11 default")
    func readonlyDefaultsToGOV11() throws {
        let result = try gate.validate(op: "query_components", args: [:])
        #expect(result.requirementId == "GOV-11")
        #expect(result.isReadonly == true)
    }

    @Test("Args sanitizer redacts secret keys")
    func sanitizerRedacts() {
        let sanitized = IntentGate.sanitize(args: [
            "api_key": "secret123",
            "password": "hunter2",
            "normal_arg": "ok"
        ])
        #expect(sanitized["api_key"]?.value as? String == "[REDACTED]")
        #expect(sanitized["password"]?.value as? String == "[REDACTED]")
        #expect(sanitized["normal_arg"] != nil)
    }

    @Test("target_files plural also extracted")
    func targetFilesPlural() throws {
        let result = try gate.validate(
            op: "safe_sync_pcb_from_schematic",
            args: [
                "target_files": ["board.kicad_pcb", "board.kicad_sch"]
            ]
        )
        #expect(result.targetFiles.count == 2)
    }

    @Test("Intent description defaults to op+requirement")
    func intentDefault() throws {
        let result = try gate.validate(op: "add_component", args: [:])
        #expect(result.intent.contains("add_component"))
        #expect(result.intent.contains("GOV-01"))
    }

    @Test("Catalog covers all GOV requirements for ops it ships with")
    func catalogCoverage() {
        let report = RequirementCoverage.report()
        // Catalog must cover at least GOV-01, GOV-02, GOV-11.
        #expect(report.byRequirement["GOV-01"]?.isEmpty == false)
        #expect(report.byRequirement["GOV-02"]?.isEmpty == false)
        #expect(report.byRequirement["GOV-11"]?.isEmpty == false)
    }
}
