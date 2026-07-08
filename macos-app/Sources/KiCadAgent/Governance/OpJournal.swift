//
//  OpJournal.swift
//  KiCadAgent
//
//  Phase 169 — Obdurate Runtime
//
//  Swift port of the routing/audit.py JSONL+fsync pattern. Every governed
//  op call appends one entry to a single append-only file with fsync
//  durability. Queries by op_type / requirement / actor / date.
//
//  GOV-06: Op Journal logs every op (uuid, timestamp, actor, intent, op,
//  args, result, verification, requirement_id).
//
//  Storage location:
//      ~/Library/Application Support/KiCadAgent/journal.jsonl
//
//  Per-entry fields mirror Python audit_log.py:
//      - operation_id  (UUID, unique per call)
//      - timestamp     (ISO 8601 UTC)
//      - actor         ("user" | "daemon" | "automation")
//      - intent        (human-readable, sanitized)
//      - op            (op name, e.g. "add_component")
//      - args          (sanitized dict, secrets redacted)
//      - result        ("success" | "failed" | "rejected")
//      - verification  (bool | null)
//      - requirement_id (e.g. "GOV-01")
//      - escalation_tier (0..4)
//
//  Fsync durability: each append uses FileHandle.synchronize() which is
//  the Foundation wrapper for fsync(2). In the rare event of a mid-write
//  crash, the last line may be truncated; queries skip invalid JSON lines.
//

import Foundation
import OSLog

// MARK: - OpJournalEntry

/// One journal entry. Codable so it can be persisted and re-loaded.
struct OpJournalEntry: Codable, Equatable, Sendable {
    let operationId: String
    let timestamp: String        // ISO 8601 UTC
    let actor: String
    let intent: String
    let op: String
    let args: [String: AnyCodable]
    let resultStatus: String     // "success" | "failed" | "rejected"
    let resultSummary: String
    let phase: String            // current WorkflowState.rawValue
    let verificationPassed: Bool?
    let requirementId: String?
    let escalationTier: Int

    init(operationId: String,
         timestamp: String,
         actor: String,
         intent: String,
         op: String,
         args: [String: AnyCodable],
         resultStatus: String,
         resultSummary: String,
         phase: String,
         verificationPassed: Bool?,
         requirementId: String?,
         escalationTier: Int = 0) {
        self.operationId = operationId
        self.timestamp = timestamp
        self.actor = actor
        self.intent = intent
        self.op = op
        self.args = args
        self.resultStatus = resultStatus
        self.resultSummary = resultSummary
        self.phase = phase
        self.verificationPassed = verificationPassed
        self.requirementId = requirementId
        self.escalationTier = escalationTier
    }

    /// Coding keys — JSON keys are snake_case to match Python convention.
    enum CodingKeys: String, CodingKey {
        case operationId = "operation_id"
        case timestamp
        case actor
        case intent
        case op
        case args
        case resultStatus = "result_status"
        case resultSummary = "result_summary"
        case phase
        case verificationPassed = "verification_passed"
        case requirementId = "requirement_id"
        case escalationTier = "escalation_tier"
    }
}

// MARK: - OpJournal

/// Append-only JSONL op journal with fsync durability.
///
/// Thread-safe via NSLock on the FileHandle. The handle is opened lazily
/// on first append and kept open for the process lifetime; close() is
/// available for tests and shutdown.
final class OpJournal: @unchecked Sendable {

    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    /// Default journal location.
    static var defaultURL: URL {
        let fm = FileManager.default
        let appSupport = (try? fm.url(for: .applicationSupportDirectory,
                                      in: .userDomainMask,
                                      appropriateFor: nil,
                                      create: true))
            ?? URL(fileURLWithPath: NSTemporaryDirectory())
        let dir = appSupport.appendingPathComponent("KiCadAgent", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("journal.jsonl")
    }

    private let url: URL
    private let lock = NSLock()
    private var fileHandle: FileHandle?

    init(url: URL = OpJournal.defaultURL) {
        self.url = url
        // Ensure the file exists so we can open it for appending.
        let fm = FileManager.default
        if !fm.fileExists(atPath: url.path) {
            fm.createFile(atPath: url.path, contents: nil, attributes: [
                .protectionKey: FileProtectionType.completeUntilFirstUserAuthentication
            ])
        }
    }

    deinit {
        try? close()
    }

    // MARK: - Append (fsync durable)

    /// Append one entry as a single JSONL line. fsyncs after the write.
    ///
    /// GOV-06 durability requirement. We use FileHandle.synchronize() which
    /// is the Foundation wrapper for fsync(2) on Apple platforms.
    func append(_ entry: OpJournalEntry) throws {
        let data: Data
        do {
            data = try JSONEncoder().encode(entry)
        } catch {
            throw NSError(domain: "OpJournal", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "encode failed: \(error)"])
        }
        // Append newline — JSONL format.
        var lineData = data
        lineData.append(0x0A)   // '\n'

        lock.lock(); defer { lock.unlock() }

        let handle = try ensureHandleLocked()
        try handle.write(contentsOf: lineData)
        try handle.synchronize()    // fsync
    }

    /// Convenience builder: append from primitive fields.
    func append(
        operationId: String = UUID().uuidString,
        timestamp: String = OpJournal.nowISO8601(),
        actor: String,
        intent: String,
        op: String,
        args: [String: Any],
        resultStatus: String,
        resultSummary: String,
        phase: String,
        verificationPassed: Bool?,
        requirementId: String?,
        escalationTier: Int = 0
    ) throws {
        let codableArgs = args.mapValues { AnyCodable($0) }
        let entry = OpJournalEntry(
            operationId: operationId,
            timestamp: timestamp,
            actor: actor,
            intent: intent,
            op: op,
            args: codableArgs,
            resultStatus: resultStatus,
            resultSummary: resultSummary,
            phase: phase,
            verificationPassed: verificationPassed,
            requirementId: requirementId,
            escalationTier: escalationTier
        )
        try append(entry)
    }

    // MARK: - Query

    /// Read all entries. Skips invalid JSON lines (H5 recovery pattern).
    func readAll() -> [OpJournalEntry] {
        guard let raw = try? Data(contentsOf: url) else { return [] }
        // Split on newlines.
        var entries: [OpJournalEntry] = []
        var start = raw.startIndex
        while start < raw.endIndex {
            if let nl = raw[start...].firstIndex(of: 0x0A) {
                let chunk = raw[start..<nl]
                if let entry = OpJournal.decode(chunk) {
                    entries.append(entry)
                }
                start = raw.index(after: nl)
            } else {
                let chunk = raw[start...]
                if let entry = OpJournal.decode(chunk) {
                    entries.append(entry)
                }
                break
            }
        }
        return entries
    }

    /// Query by operation_id. Returns at most one entry (UUIDs are unique).
    func queryByOperationId(_ id: String) -> OpJournalEntry? {
        return readAll().first { $0.operationId == id }
    }

    /// Query by op type.
    func queryByOp(_ op: String) -> [OpJournalEntry] {
        return readAll().filter { $0.op == op }
    }

    /// Query by requirement_id.
    func queryByRequirement(_ requirementId: String) -> [OpJournalEntry] {
        return readAll().filter { $0.requirementId == requirementId }
    }

    /// Query by actor.
    func queryByActor(_ actor: String) -> [OpJournalEntry] {
        return readAll().filter { $0.actor == actor }
    }

    /// Query by date (UTC date prefix, e.g. "2026-07-08").
    func queryByDate(_ datePrefix: String) -> [OpJournalEntry] {
        return readAll().filter { $0.timestamp.hasPrefix(datePrefix) }
    }

    /// Count failures for a given task key (used by EscalationLadder).
    /// "task key" = the op name; the ladder tracks failures per op.
    func failureCount(op: String) -> Int {
        return readAll().filter { $0.op == op && $0.resultStatus == "failed" }.count
    }

    /// Count all failures since a timestamp (ISO 8601 prefix string compare).
    func failureCount(since timestampPrefix: String) -> Int {
        return readAll().filter {
            $0.resultStatus == "failed" && $0.timestamp >= timestampPrefix
        }.count
    }

    // MARK: - Lifecycle

    /// Close the underlying file handle. Safe to call multiple times.
    func close() throws {
        lock.lock(); defer { lock.unlock() }
        try fileHandle?.close()
        fileHandle = nil
    }

    /// Test helper: clear the journal file. Production code should never
    /// call this — journal is append-only.
    func _testReset() throws {
        lock.lock(); defer { lock.unlock() }
        try fileHandle?.close()
        fileHandle = nil
        try Data().write(to: url)
    }

    // MARK: - Internals

    /// Open the file handle for appending if not already open. Caller MUST
    /// hold `lock`.
    private func ensureHandleLocked() throws -> FileHandle {
        if let h = fileHandle { return h }
        let h = try FileHandle(forWritingTo: url)
        // Seek to end — append mode.
        try h.seekToEnd()
        fileHandle = h
        return h
    }

    /// Decode one JSON line, returning nil on failure (H5 recovery).
    private static func decode(_ data: Data.SubSequence) -> OpJournalEntry? {
        guard !data.isEmpty else { return nil }
        let bytes = Data(data)
        // Strip trailing whitespace.
        let trimmed = bytes.filter { $0 != 0x0A && $0 != 0x0D }
        guard !trimmed.isEmpty else { return nil }
        do {
            return try JSONDecoder().decode(OpJournalEntry.self, from: trimmed)
        } catch {
            logger.warning("OpJournal: skipping malformed line (\(trimmed.count) bytes)")
            return nil
        }
    }

    // MARK: - Time helpers

    /// Current UTC time as ISO 8601 string with millisecond precision.
    static func nowISO8601() -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: Date())
    }
}
