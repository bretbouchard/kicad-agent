//
//  ValueChange.swift
//  Volta
//
//  Phase 176 — SwiftData Models
//
//  SwiftData @Model for a single value-change event.
//
//  Every user-driven mutation is captured as a ValueChange with old → new
//  value, reason, and timestamp. This is event sourcing at the field level.
//
//  MEM-05: values are event-sourced.
//

import Foundation
import SwiftData
import OSLog

/// A single field-level change event (event sourcing pattern).
///
/// Each ValueChange captures one mutation: who changed what, from what,
/// to what, and why. Replaying these reconstitutes the conversation state
/// at any point in time (Phase 178 Time-Travel).
@Model
final class ValueChange {
    /// Stable identifier.
    @Attribute(.unique) var id: UUID

    /// Owning conversation.
    var conversation: Conversation?

    /// Foreign key.
    var conversationId: UUID

    /// When the change was made (UTC).
    var changedAt: Date

    /// Field path (e.g., "spec.title", "spec.constraints.budgetUSD").
    var fieldPath: String

    /// Old value (JSON-encoded; "{}" for create ops).
    var oldValueJSON: String

    /// New value (JSON-encoded).
    var newValueJSON: String

    /// Why the change was made (link to Decision.decisionId for audit trail).
    var decisionId: UUID?

    /// Optional actor (user / assistant / system).
    var actorRaw: String

    init(
        id: UUID = UUID(),
        conversation: Conversation,
        changedAt: Date = .now,
        fieldPath: String,
        oldValueJSON: String = "{}",
        newValueJSON: String = "{}",
        decisionId: UUID? = nil,
        actor: ValueChangeActor = .user
    ) {
        precondition(!fieldPath.isEmpty, "ValueChange fieldPath must not be empty")
        self.id = id
        self.conversation = conversation
        self.conversationId = conversation.id
        self.changedAt = changedAt
        self.fieldPath = fieldPath
        self.oldValueJSON = oldValueJSON
        self.newValueJSON = newValueJSON
        self.decisionId = decisionId
        self.actorRaw = actor.rawValue
        Logger.models.info("ValueChange created field=\(self.fieldPath, privacy: .public)")
    }
}

extension ValueChange {
    /// Typed actor accessor.
    var actor: ValueChangeActor {
        get { ValueChangeActor(rawValue: actorRaw) ?? .user }
        set { actorRaw = newValue.rawValue }
    }
}

/// Who made the change. Drives UI badges (Phase 179 Timeline).
enum ValueChangeActor: String, Codable, Sendable, CaseIterable {
    case user
    case assistant
    case system
}
