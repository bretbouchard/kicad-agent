//
//  TimeTravelEngine.swift
//  Volta
//
//  Phase 178 — Time-Travel Engine
//
//  Replays ValueChange events to materialize conversation state at any
//  point in time. Uses snapshots for O(1) seek, then replays remaining
//  events forward.
//
//  TT-01: timeline shows all decisions chronologically
//  TT-02: each entry links to originating message
//  TT-03: scrub slider for time-travel
//  TT-04: compare two points (diff view)
//  TT-06: restore preserves history
//  TT-07: snapshots are immutable
//

import Foundation
import SwiftData
import OSLog

/// Engine for time-travel operations: replay, materialize, diff, restore.
@MainActor
final class TimeTravelEngine {
    private let modelContext: ModelContext

    init(modelContext: ModelContext) {
        self.modelContext = modelContext
    }

    // MARK: - Materialization

    /// Materialize conversation state at the given timestamp.
    ///
    /// Algorithm:
    /// 1. Find nearest snapshot with `takenAt <= target`
    /// 2. If found, deserialize snapshot.stateJSON as base
    /// 3. Replay ValueChange events between snapshot.takenAt and target
    /// 4. If no snapshot, replay all events from epoch
    ///
    /// Returns the materialized state as a ConversationState struct.
    func materializeState(conversationId: UUID, at target: Date) throws -> ConversationState {
        let snapshot = try latestSnapshot(conversationId: conversationId, at: target)
        var state: ConversationState

        if let snapshot {
            state = try ConversationState.decode(snapshot.stateJSON)
        } else {
            state = ConversationState.empty
        }

        let changes = try valueChanges(conversationId: conversationId, after: snapshot?.takenAt ?? .distantPast, upTo: target)
        for change in changes {
            state.apply(ValueChangePayload(
                id: change.id,
                fieldPath: change.fieldPath,
                oldValueJSON: change.oldValueJSON,
                newValueJSON: change.newValueJSON,
                changedAt: change.changedAt,
                actorRaw: change.actorRaw
            ))
        }
        return state
    }

    /// Capture a snapshot for the current conversation state.
    @discardableResult
    func captureSnapshot(
        conversationId: UUID,
        trigger: SnapshotTrigger,
        changeSequence: Int
    ) throws -> ProjectSnapshot? {
        guard let conversation = try fetchConversation(conversationId) else { return nil }
        let state = try materializeState(conversationId: conversationId, at: .now)
        let snapshot = ProjectSnapshot(
            conversation: conversation,
            changeSequence: changeSequence,
            stateJSON: try state.encode(),
            trigger: trigger
        )
        modelContext.insert(snapshot)
        try modelContext.save()
        Logger.models.info("Snapshot captured seq=\(changeSequence) trigger=\(trigger.rawValue)")
        return snapshot
    }

    // MARK: - Diff

    /// Diff two conversation states (typically from two timestamps).
    func diff(
        conversationId: UUID,
        from: Date,
        to: Date
    ) throws -> [TimelineDiffEntry] {
        let fromState = try materializeState(conversationId: conversationId, at: from)
        let toState = try materializeState(conversationId: conversationId, at: to)
        return DiffUtil.diffFields(from: fromState.fields, to: toState.fields)
    }

    // MARK: - Restore

    /// Restore conversation state to the given timestamp.
    ///
    /// TT-06: preserves history. Creates a new ValueChange event that
    /// records the restoration, then applies the old state.
    func restore(conversationId: UUID, to target: Date, actor: ValueChangeActor = .user) throws {
        guard let conversation = try fetchConversation(conversationId) else { return }
        let targetState = try materializeState(conversationId: conversationId, at: target)
        let currentState = try materializeState(conversationId: conversationId, at: .now)

        // Create a restoration event for audit trail (history is preserved).
        let restoreChange = ValueChange(
            conversation: conversation,
            fieldPath: "__restore__",
            oldValueJSON: try currentState.encode(),
            newValueJSON: try targetState.encode(),
            actor: actor
        )
        modelContext.insert(restoreChange)

        // Apply each target field as a new change event.
        for (path, value) in targetState.fields {
            let current = currentState.fields[path]
            let change = ValueChange(
                conversation: conversation,
                fieldPath: path,
                oldValueJSON: current ?? "{}",
                newValueJSON: value,
                actor: actor
            )
            modelContext.insert(change)
        }
        try modelContext.save()
        Logger.models.info("Restored conversation to \(target.formatted()) with \(targetState.fields.count) field changes")
    }

    // MARK: - Helpers

    private func fetchConversation(_ id: UUID) throws -> Conversation? {
        var descriptor = FetchDescriptor<Conversation>(
            predicate: #Predicate { $0.id == id }
        )
        descriptor.fetchLimit = 1
        return try modelContext.fetch(descriptor).first
    }

    private func latestSnapshot(conversationId: UUID, at target: Date) throws -> ProjectSnapshot? {
        var descriptor = FetchDescriptor<ProjectSnapshot>(
            predicate: #Predicate { $0.conversationId == conversationId && $0.takenAt <= target },
            sortBy: [SortDescriptor(\.takenAt, order: .reverse)]
        )
        descriptor.fetchLimit = 1
        return try modelContext.fetch(descriptor).first
    }

    private func valueChanges(conversationId: UUID, after: Date, upTo: Date) throws -> [ValueChange] {
        let descriptor = FetchDescriptor<ValueChange>(
            predicate: #Predicate { $0.conversationId == conversationId && $0.changedAt > after && $0.changedAt <= upTo },
            sortBy: [SortDescriptor(\.changedAt, order: .forward)]
        )
        return try modelContext.fetch(descriptor)
    }
}

/// Snapshotted conversation state — a flat field map for simplicity.
struct ConversationState: Codable, Sendable, Equatable {
    var fields: [String: String]

    static let empty = ConversationState(fields: [:])

    /// Apply a value change: replace field value with newValueJSON.
    mutating func apply(_ change: ValueChangePayload) {
        fields[change.fieldPath] = change.newValueJSON
    }

    func encode() throws -> String {
        let data = try JSONEncoder().encode(self)
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    static func decode(_ json: String) throws -> ConversationState {
        guard let data = json.data(using: .utf8) else { return .empty }
        return try JSONDecoder().decode(ConversationState.self, from: data)
    }
}
