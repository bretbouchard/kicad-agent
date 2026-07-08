//
//  DriftDetectorTests.swift
//  KiCadAgentTests
//
//  Phase 169 — Obdurate Runtime
//

import Testing
import Foundation
@testable import KiCadAgent

@Suite("DriftDetector")
struct DriftDetectorTests {

    @Test("Permissive when no scope registered")
    func permissiveWithoutScope() throws {
        let d = DriftDetector()
        let intent = IntentResult(
            op: "add_component",
            args: [:],
            requirementId: "GOV-01",
            intent: "",
            targetFiles: ["board.kicad_sch"],
            isReadonly: false
        )
        let result = d.check(intent)
        #expect(result.isClean)
        #expect(result.warnings.isEmpty == false)   // warns about permissive mode
    }

    @Test("In-scope files return clean result")
    func inScope() throws {
        let d = DriftDetector()
        d.registerScope(for: "GOV-01", files: ["kicad_sch"])
        let intent = IntentResult(
            op: "add_component",
            args: [:],
            requirementId: "GOV-01",
            intent: "",
            targetFiles: ["board.kicad_sch"],
            isReadonly: false
        )
        let result = d.check(intent)
        #expect(result.isClean)
        #expect(result.outOfScope.isEmpty)
    }

    @Test("Out-of-scope files flagged")
    func outOfScope() throws {
        let d = DriftDetector()
        d.registerScope(for: "GOV-01", files: ["kicad_sch"])
        let intent = IntentResult(
            op: "add_component",
            args: [:],
            requirementId: "GOV-01",
            intent: "",
            targetFiles: ["board.kicad_pcb"],   // PCB not in scope for GOV-01 catalog
            isReadonly: false
        )
        let result = d.check(intent)
        #expect(!result.isClean)
        #expect(result.outOfScope.contains("board.kicad_pcb"))
    }

    @Test("Strict mode rejects out-of-scope (logged error)")
    func strictMode() throws {
        let d = DriftDetector(strictMode: true)
        d.registerScope(for: "GOV-01", files: ["kicad_sch"])
        let intent = IntentResult(
            op: "add_component",
            args: [:],
            requirementId: "GOV-01",
            intent: "",
            targetFiles: ["board.kicad_pcb"],
            isReadonly: false
        )
        let result = d.check(intent)
        #expect(!result.isClean)
    }

    @Test("File matching uses suffix rules")
    func suffixMatching() {
        #expect(DriftDetector.matches(file: "myboard.kicad_sch", in: ["kicad_sch"]))
        #expect(DriftDetector.matches(file: "/abs/path/board.kicad_sch", in: ["kicad_sch"]))
        #expect(!DriftDetector.matches(file: "board.kicad_pcb", in: ["kicad_sch"]))
    }
}
