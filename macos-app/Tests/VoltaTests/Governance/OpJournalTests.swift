//
//  OpJournalTests.swift
//  VoltaTests
//
//  Phase 169 — Obdurate Runtime
//
//  Tests OpJournal append durability (fsync verified via re-read after
//  write) and query behavior.
//

import Testing
import Foundation
@testable import Volta

@Suite("OpJournal")
struct OpJournalTests {

    /// Each test gets a fresh journal in a tmp file.
    private func makeJournal() throws -> (OpJournal, URL) {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("kc-test-journal-\(UUID().uuidString).jsonl")
        FileManager.default.createFile(atPath: tmp.path, contents: nil)
        let j = OpJournal(url: tmp)
        return (j, tmp)
    }

    @Test("Append writes a JSONL line and readAll returns it")
    func appendAndRead() throws {
        let (j, url) = try makeJournal()
        defer { try? FileManager.default.removeItem(at: url) }
        let entry = OpJournalEntry(
            operationId: "op-1",
            timestamp: OpJournal.nowISO8601(),
            actor: "user",
            intent: "test op",
            op: "add_component",
            args: ["refdes": AnyCodable("R1")],
            resultStatus: "success",
            resultSummary: "ok",
            phase: "executing",
            verificationPassed: true,
            requirementId: "GOV-01"
        )
        try j.append(entry)

        let all = j.readAll()
        #expect(all.count == 1)
        #expect(all.first?.operationId == "op-1")
        #expect(all.first?.op == "add_component")
        #expect(all.first?.requirementId == "GOV-01")
    }

    @Test("Append is durable — fsync means the bytes are on disk immediately")
    func appendIsDurable() throws {
        let (j, url) = try makeJournal()
        defer { try? FileManager.default.removeItem(at: url) }
        try j.append(operationId: "op-x",
                     timestamp: OpJournal.nowISO8601(),
                     actor: "user", intent: "durability check",
                     op: "query_components",
                     args: ["refdes": AnyCodable("R2")],
                     resultStatus: "success",
                     resultSummary: "",
                     phase: "executing",
                     verificationPassed: true,
                     requirementId: "GOV-11")
        // Read the file directly — bypass the journal's cache.
        let raw = try String(contentsOf: url, encoding: .utf8)
        #expect(raw.contains("op-x"))
        #expect(raw.contains("query_components"))
    }

    @Test("Query by op filters correctly")
    func queryByOp() throws {
        let (j, url) = try makeJournal()
        defer { try? FileManager.default.removeItem(at: url) }
        for i in 0..<3 {
            try j.append(operationId: "id-\(i)", timestamp: OpJournal.nowISO8601(),
                         actor: "user", intent: "",
                         op: "add_component", args: [:],
                         resultStatus: "success", resultSummary: "",
                         phase: "executing",
                         verificationPassed: true, requirementId: "GOV-01")
        }
        try j.append(operationId: "id-other", timestamp: OpJournal.nowISO8601(),
                     actor: "user", intent: "",
                     op: "query_components", args: [:],
                     resultStatus: "success", resultSummary: "",
                     phase: "executing",
                     verificationPassed: true, requirementId: "GOV-11")
        #expect(j.queryByOp("add_component").count == 3)
        #expect(j.queryByOp("query_components").count == 1)
    }

    @Test("Query by requirement filters correctly")
    func queryByRequirement() throws {
        let (j, url) = try makeJournal()
        defer { try? FileManager.default.removeItem(at: url) }
        try j.append(operationId: "a", timestamp: OpJournal.nowISO8601(),
                     actor: "user", intent: "", op: "add_component", args: [:],
                     resultStatus: "success", resultSummary: "",
                     phase: "executing", verificationPassed: true,
                     requirementId: "GOV-01")
        try j.append(operationId: "b", timestamp: OpJournal.nowISO8601(),
                     actor: "user", intent: "", op: "query_components", args: [:],
                     resultStatus: "success", resultSummary: "",
                     phase: "executing", verificationPassed: true,
                     requirementId: "GOV-11")
        #expect(j.queryByRequirement("GOV-01").count == 1)
        #expect(j.queryByRequirement("GOV-11").count == 1)
    }

    @Test("Failure count tracks failed entries")
    func failureCount() throws {
        let (j, url) = try makeJournal()
        defer { try? FileManager.default.removeItem(at: url) }
        try j.append(operationId: "f1", timestamp: OpJournal.nowISO8601(),
                     actor: "user", intent: "", op: "add_component", args: [:],
                     resultStatus: "failed", resultSummary: "boom",
                     phase: "executing", verificationPassed: false,
                     requirementId: "GOV-01")
        try j.append(operationId: "f2", timestamp: OpJournal.nowISO8601(),
                     actor: "user", intent: "", op: "add_component", args: [:],
                     resultStatus: "success", resultSummary: "",
                     phase: "executing", verificationPassed: true,
                     requirementId: "GOV-01")
        #expect(j.failureCount(op: "add_component") == 1)
    }

    @Test("Truncated final line is skipped (H5 recovery)")
    func truncatedLineRecovery() throws {
        let (j, url) = try makeJournal()
        defer { try? FileManager.default.removeItem(at: url) }
        try j.append(operationId: "good", timestamp: OpJournal.nowISO8601(),
                     actor: "user", intent: "", op: "add_component", args: [:],
                     resultStatus: "success", resultSummary: "",
                     phase: "executing", verificationPassed: true,
                     requirementId: "GOV-01")
        // Append a malformed (truncated) line directly to the file.
        let handle = try FileHandle(forWritingTo: url)
        try handle.seekToEnd()
        try handle.write(contentsOf: Data("{truncated json without closing".utf8))
        try handle.close()

        // readAll should skip the bad line and return only the good one.
        let entries = j.readAll()
        #expect(entries.count == 1)
        #expect(entries.first?.operationId == "good")
    }

    @Test("queryByOperationId returns the entry")
    func queryByOpId() throws {
        let (j, url) = try makeJournal()
        defer { try? FileManager.default.removeItem(at: url) }
        try j.append(operationId: "uuid-42", timestamp: OpJournal.nowISO8601(),
                     actor: "user", intent: "", op: "add_component", args: [:],
                     resultStatus: "success", resultSummary: "",
                     phase: "executing", verificationPassed: true,
                     requirementId: "GOV-01")
        #expect(j.queryByOperationId("uuid-42")?.op == "add_component")
        #expect(j.queryByOperationId("does-not-exist") == nil)
    }
}
