//
//  AutoLearner.swift
//  KiCadAgent
//
//  Phase 169 — Obdurate Runtime
//
//  Auto-learner: persists successful patterns and failed-attempt
//  error_messages so future calls can look them up.
//
//  GOV-10: "Auto-learning (success → pattern store, failure →
//  error_message store)."
//
//  Storage:
//      ~/Library/Application Support/KiCadAgent/learnings.jsonl
//
//  Learnings are JSONL+fsync (mirrors OpJournal durability). Queryable
//  by op name, requirement_id, and success/failure type.
//

import Foundation
import OSLog

// MARK: - LearningType

enum LearningType: String, Codable, Sendable {
    case pattern         // success — what worked
    case errorMessage    // failure — what didn't
    case designDecision  // architecture decision
    case knowledgeState  // session-end state summary
}

// MARK: - Learning

struct Learning: Codable, Equatable, Sendable {
    let id: String                  // UUID
    let timestamp: String           // ISO 8601
    let type: LearningType
    let op: String?
    let requirementId: String?
    let content: String             // human-readable
    let tags: [String]

    init(id: String = UUID().uuidString,
                timestamp: String = AutoLearner.nowISO8601(),
                type: LearningType,
                op: String? = nil,
                requirementId: String? = nil,
                content: String,
                tags: [String] = []) {
        self.id = id
        self.timestamp = timestamp
        self.type = type
        self.op = op
        self.requirementId = requirementId
        self.content = content
        self.tags = tags
    }
}

// MARK: - AutoLearner

final class AutoLearner: @unchecked Sendable {

    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    static var defaultURL: URL {
        let fm = FileManager.default
        let appSupport = (try? fm.url(for: .applicationSupportDirectory,
                                      in: .userDomainMask,
                                      appropriateFor: nil,
                                      create: true))
            ?? URL(fileURLWithPath: NSTemporaryDirectory())
        let dir = appSupport.appendingPathComponent("KiCadAgent", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("learnings.jsonl")
    }

    private let url: URL
    private let lock = NSLock()
    private var fileHandle: FileHandle?

    init(url: URL = AutoLearner.defaultURL) {
        self.url = url
        let fm = FileManager.default
        if !fm.fileExists(atPath: url.path) {
            fm.createFile(atPath: url.path, contents: nil)
        }
    }

    deinit { try? close() }

    // MARK: - Store

    /// Store a learning (fsync durable).
    func store(_ learning: Learning) throws {
        let data = try JSONEncoder().encode(learning)
        var lineData = data
        lineData.append(0x0A)

        lock.lock(); defer { lock.unlock() }
        let handle = try ensureHandleLocked()
        try handle.write(contentsOf: lineData)
        try handle.synchronize()

        Self.logger.info("AutoLearner: stored \(learning.type.rawValue, privacy: .public) id=\(learning.id, privacy: .public)")
    }

    /// Convenience: store a pattern from a successful op call.
    func storeSuccessPattern(op: String,
                                    requirementId: String,
                                    summary: String,
                                    tags: [String] = []) throws {
        let l = Learning(
            type: .pattern, op: op, requirementId: requirementId,
            content: summary, tags: tags + ["success", "op:\(op)"]
        )
        try store(l)
    }

    /// Convenience: store an error_message from a failed op call.
    func storeFailureMessage(op: String,
                                    requirementId: String?,
                                    error: String,
                                    tags: [String] = []) throws {
        let l = Learning(
            type: .errorMessage, op: op, requirementId: requirementId,
            content: error, tags: tags + ["failure", "op:\(op)"]
        )
        try store(l)
    }

    // MARK: - Query

    func readAll() -> [Learning] {
        guard let raw = try? Data(contentsOf: url) else { return [] }
        var out: [Learning] = []
        var start = raw.startIndex
        while start < raw.endIndex {
            if let nl = raw[start...].firstIndex(of: 0x0A) {
                let chunk = raw[start..<nl]
                if let l = try? JSONDecoder().decode(Learning.self, from: Data(chunk)) {
                    out.append(l)
                }
                start = raw.index(after: nl)
            } else {
                let chunk = raw[start...]
                if let l = try? JSONDecoder().decode(Learning.self, from: Data(chunk)) {
                    out.append(l)
                }
                break
            }
        }
        return out
    }

    /// Query by op name — returns most-recent-first.
    func queryByOp(_ op: String) -> [Learning] {
        return readAll()
            .filter { $0.op == op }
            .sorted { $0.timestamp > $1.timestamp }
    }

    /// Query similar successes: patterns for a given op sorted most-recent.
    func similarSuccesses(op: String) -> [Learning] {
        return queryByOp(op).filter { $0.type == .pattern }
    }

    /// Query similar failures: error_messages for a given op.
    func similarFailures(op: String) -> [Learning] {
        return queryByOp(op).filter { $0.type == .errorMessage }
    }

    // MARK: - Lifecycle

    func close() throws {
        lock.lock(); defer { lock.unlock() }
        try fileHandle?.close()
        fileHandle = nil
    }

    func _testReset() throws {
        lock.lock(); defer { lock.unlock() }
        try fileHandle?.close()
        fileHandle = nil
        try Data().write(to: url)
    }

    private func ensureHandleLocked() throws -> FileHandle {
        if let h = fileHandle { return h }
        let h = try FileHandle(forWritingTo: url)
        try h.seekToEnd()
        fileHandle = h
        return h
    }

    static func nowISO8601() -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: Date())
    }
}
