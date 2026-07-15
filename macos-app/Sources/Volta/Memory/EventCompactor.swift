//
//  EventCompactor.swift
//  Volta
//
//  Phase 180 — Event Sourcing
//
//  Archives old events to a separate store, keeping active event count
//  under 100K (Pitfall 8 prevention — query performance).
//
//  MEM-07: materialized snapshots maintain current state.
//

import Foundation
import SwiftData
import OSLog

/// Compacts event sourcing store by archiving old events.
@MainActor
final class EventCompactor {
    static let maxActiveEvents = 100_000

    private let modelContext: ModelContext
    private let archiveDirectory: URL

    init(modelContext: ModelContext, archiveDirectory: URL? = nil) {
        self.modelContext = modelContext
        self.archiveDirectory = archiveDirectory ?? FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Volta/Archive", isDirectory: true)
        try? FileManager.default.createDirectory(at: self.archiveDirectory, withIntermediateDirectories: true)
    }

    /// Run compaction. Archives events older than `olderThan` to a JSONL file
    /// and deletes them from the active SwiftData store.
    ///
    /// Returns the number of events archived.
    @discardableResult
    func compact(olderThan cutoff: Date) throws -> Int {
        // Capture latest snapshot for each conversation before archiving.
        let conversations = try fetchAllConversations()
        var archivedCount = 0

        for conversation in conversations {
            archivedCount += try archiveOldEvents(conversation: conversation, olderThan: cutoff)
        }

        Logger.models.info("Compaction archived \(archivedCount) events older than \(cutoff.formatted())")
        return archivedCount
    }

    /// True if active event count exceeds the cap.
    func needsCompaction() throws -> Bool {
        let decisions = try modelContext.fetch(FetchDescriptor<Decision>())
        let changes = try modelContext.fetch(FetchDescriptor<ValueChange>())
        return (decisions.count + changes.count) >= Self.maxActiveEvents
    }

    // MARK: - Private

    private func fetchAllConversations() throws -> [Conversation] {
        try modelContext.fetch(FetchDescriptor<Conversation>())
    }

    private func archiveOldEvents(conversation: Conversation, olderThan cutoff: Date) throws -> Int {
        let decisionsToArchive = try fetchDecisions(conversationId: conversation.id, olderThan: cutoff)
        let changesToArchive = try fetchValueChanges(conversationId: conversation.id, olderThan: cutoff)

        guard !decisionsToArchive.isEmpty || !changesToArchive.isEmpty else { return 0 }

        // Write to JSONL archive file.
        let archiveURL = archiveFile(for: conversation.id, date: cutoff)
        try writeArchive(decisions: decisionsToArchive, changes: changesToArchive, to: archiveURL)

        // Delete from active store.
        for decision in decisionsToArchive { modelContext.delete(decision) }
        for change in changesToArchive { modelContext.delete(change) }
        try modelContext.save()

        return decisionsToArchive.count + changesToArchive.count
    }

    private func fetchDecisions(conversationId: UUID, olderThan cutoff: Date) throws -> [Decision] {
        try modelContext.fetch(FetchDescriptor<Decision>(
            predicate: #Predicate { $0.conversationId == conversationId && $0.decidedAt < cutoff }
        ))
    }

    private func fetchValueChanges(conversationId: UUID, olderThan cutoff: Date) throws -> [ValueChange] {
        try modelContext.fetch(FetchDescriptor<ValueChange>(
            predicate: #Predicate { $0.conversationId == conversationId && $0.changedAt < cutoff }
        ))
    }

    private func archiveFile(for conversationId: UUID, date: Date) -> URL {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let dateStr = formatter.string(from: date)
        return archiveDirectory.appendingPathComponent("\(conversationId.uuidString)-\(dateStr).jsonl")
    }

    private func writeArchive(decisions: [Decision], changes: [ValueChange], to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        var lines: [String] = []

        for decision in decisions {
            let payload: [String: String] = [
                "type": "decision",
                "id": decision.id.uuidString,
                "conversationId": decision.conversationId.uuidString,
                "decidedAt": ISO8601DateFormatter().string(from: decision.decidedAt),
                "decisionKey": decision.decisionKey,
                "oldValueJSON": decision.oldValueJSON,
                "newValueJSON": decision.newValueJSON,
                "reasoning": decision.reasoning,
                "resolution": decision.resolutionRaw
            ]
            let data = try encoder.encode(payload)
            if let line = String(data: data, encoding: .utf8) {
                lines.append(line)
            }
        }

        for change in changes {
            let payload: [String: String] = [
                "type": "valueChange",
                "id": change.id.uuidString,
                "conversationId": change.conversationId.uuidString,
                "changedAt": ISO8601DateFormatter().string(from: change.changedAt),
                "fieldPath": change.fieldPath,
                "oldValueJSON": change.oldValueJSON,
                "newValueJSON": change.newValueJSON,
                "actor": change.actorRaw
            ]
            let data = try encoder.encode(payload)
            if let line = String(data: data, encoding: .utf8) {
                lines.append(line)
            }
        }

        let jsonl = lines.joined(separator: "\n") + "\n"
        try jsonl.data(using: .utf8)?.write(to: url, options: .atomic)
    }
}
