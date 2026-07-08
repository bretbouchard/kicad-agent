//
//  ProjectSnapshot.swift
//  KiCadAgent
//
//  Phase 176 — SwiftData Models
//
//  SwiftData @Model for a point-in-time snapshot of a conversation.
//
//  Snapshots materialize full conversation state at a specific timestamp.
//  Used by Phase 178 Time-Travel to jump backward without replaying every
//  ValueChange event from the beginning.
//
//  MEM-06: snapshots enable fast time-travel (don't replay from epoch).
//

import Foundation
import SwiftData
import OSLog

/// A materialized point-in-time snapshot of a conversation's state.
///
/// Snapshots are written periodically (every N changes, every phase transition,
/// every manual "checkpoint" action). Time-travel walks the nearest snapshot
/// then replays the remaining ValueChange events forward.
@Model
final class ProjectSnapshot {
    /// Stable identifier.
    @Attribute(.unique) var id: UUID

    /// Owning conversation.
    var conversation: Conversation?

    /// Foreign key.
    var conversationId: UUID

    /// When the snapshot was taken (UTC).
    var takenAt: Date

    /// Cumulative ValueChange count at time of snapshot.
    var changeSequence: Int

    /// Full state serialized as JSON. Schema is conversation-state v6.0.0.
    var stateJSON: String

    /// Optional trigger reason (periodic / phase_transition / manual).
    var triggerRaw: String

    /// Size of stateJSON in bytes (for storage audit).
    var stateSizeBytes: Int

    init(
        id: UUID = UUID(),
        conversation: Conversation,
        takenAt: Date = .now,
        changeSequence: Int,
        stateJSON: String,
        trigger: SnapshotTrigger = .periodic
    ) {
        precondition(!stateJSON.isEmpty, "ProjectSnapshot stateJSON must not be empty")
        self.id = id
        self.conversation = conversation
        self.conversationId = conversation.id
        self.takenAt = takenAt
        self.changeSequence = changeSequence
        self.stateJSON = stateJSON
        self.triggerRaw = trigger.rawValue
        self.stateSizeBytes = stateJSON.utf8.count
        Logger.models.info("ProjectSnapshot created seq=\(self.changeSequence) size=\(self.stateSizeBytes) bytes")
    }
}

extension ProjectSnapshot {
    /// Typed trigger accessor.
    var trigger: SnapshotTrigger {
        get { SnapshotTrigger(rawValue: triggerRaw) ?? .periodic }
        set { triggerRaw = newValue.rawValue }
    }
}

/// What caused the snapshot to be taken.
enum SnapshotTrigger: String, Codable, Sendable, CaseIterable {
    case periodic          // Auto-snapshot every N changes
    case phaseTransition   // Snapshot at GSD phase boundary
    case manual            // User-initiated checkpoint
    case preOp             // Pre-mutation snapshot for rollback
}
