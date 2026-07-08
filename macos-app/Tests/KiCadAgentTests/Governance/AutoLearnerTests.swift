//
//  AutoLearnerTests.swift
//  KiCadAgentTests
//
//  Phase 169 — Obdurate Runtime
//

import Testing
import Foundation
@testable import KiCadAgent

@Suite("AutoLearner")
struct AutoLearnerTests {

    private func makeLearner() throws -> (AutoLearner, URL) {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("kc-test-learn-\(UUID().uuidString).jsonl")
        FileManager.default.createFile(atPath: tmp.path, contents: nil)
        return (AutoLearner(url: tmp), tmp)
    }

    @Test("Store pattern appends JSONL line")
    func storePattern() throws {
        let (learner, url) = try makeLearner()
        defer { try? FileManager.default.removeItem(at: url) }
        try learner.storeSuccessPattern(
            op: "add_component",
            requirementId: "GOV-01",
            summary: "works with default args"
        )
        let all = learner.readAll()
        #expect(all.count == 1)
        #expect(all.first?.type == .pattern)
        #expect(all.first?.op == "add_component")
    }

    @Test("Store error_message appends JSONL line")
    func storeError() throws {
        let (learner, url) = try makeLearner()
        defer { try? FileManager.default.removeItem(at: url) }
        try learner.storeFailureMessage(
            op: "auto_route",
            requirementId: "GOV-02",
            error: "freerouting jar missing"
        )
        let all = learner.readAll()
        #expect(all.count == 1)
        #expect(all.first?.type == .errorMessage)
        #expect(all.first?.op == "auto_route")
    }

    @Test("queryByOp returns entries for that op")
    func queryByOp() throws {
        let (learner, url) = try makeLearner()
        defer { try? FileManager.default.removeItem(at: url) }
        try learner.storeSuccessPattern(op: "x", requirementId: "GOV-01", summary: "1")
        try learner.storeFailureMessage(op: "x", requirementId: "GOV-01", error: "2")
        try learner.storeSuccessPattern(op: "y", requirementId: "GOV-02", summary: "3")
        #expect(learner.queryByOp("x").count == 2)
        #expect(learner.queryByOp("y").count == 1)
    }

    @Test("similarSuccesses filters type=pattern")
    func similarSuccesses() throws {
        let (learner, url) = try makeLearner()
        defer { try? FileManager.default.removeItem(at: url) }
        try learner.storeSuccessPattern(op: "x", requirementId: "GOV-01", summary: "ok")
        try learner.storeFailureMessage(op: "x", requirementId: "GOV-01", error: "fail")
        let succ = learner.similarSuccesses(op: "x")
        #expect(succ.count == 1)
        #expect(succ.first?.type == .pattern)
    }

    @Test("similarFailures filters type=errorMessage")
    func similarFailures() throws {
        let (learner, url) = try makeLearner()
        defer { try? FileManager.default.removeItem(at: url) }
        try learner.storeSuccessPattern(op: "x", requirementId: "GOV-01", summary: "ok")
        try learner.storeFailureMessage(op: "x", requirementId: "GOV-01", error: "fail")
        let fail = learner.similarFailures(op: "x")
        #expect(fail.count == 1)
        #expect(fail.first?.type == .errorMessage)
    }

    @Test("Tags are persisted")
    func tagsPersist() throws {
        let (learner, url) = try makeLearner()
        defer { try? FileManager.default.removeItem(at: url) }
        try learner.store(Learning(
            type: .designDecision,
            op: nil,
            requirementId: nil,
            content: "use MLX for local inference",
            tags: ["architecture", "phase-164"]
        ))
        #expect(learner.readAll().first?.tags.contains("architecture") == true)
    }
}
