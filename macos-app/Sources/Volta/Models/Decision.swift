//
//  Decision.swift
//  Volta
//
//  Phase 176 — SwiftData Models
//
//  SwiftData @Model for a decision event.
//
//  Decisions are first-class: every gate resolution, spec edit, roadmap
//  approve creates a Decision event with reasoning. Forms the audit trail
//  for Phase 178 Time-Travel and Phase 179 Decision Timeline.
//
//  MEM-04: decisions are first-class objects.
//

import Foundation
import SwiftData
import OSLog

/// A decision event — gate approval, spec edit, roadmap approve, etc.
///
/// Decisions are the spine of the audit trail. Every user-driven choice
/// creates one. Time-travel (Phase 178) walks these to materialize past state.
@Model
final class Decision {
    /// Stable identifier.
    @Attribute(.unique) var id: UUID

    /// Owning conversation (a decision belongs to one conversation).
    var conversation: Conversation?

    /// Foreign key kept denormalized.
    var conversationId: UUID

    /// When the decision was made (UTC).
    var decidedAt: Date

    /// Short key (e.g., "spec.approve", "gate.approve", "phase.transition").
    var decisionKey: String

    /// Old value before the decision (JSON-encoded; may be empty for create ops).
    var oldValueJSON: String

    /// New value after the decision (JSON-encoded).
    var newValueJSON: String

    /// User-supplied reasoning. Required for `.reject` resolutions (Phase 174).
    var reasoning: String

    /// Resolution state from four-state taxonomy.
    /// One of: implemented / added_as_phase / superseded / deferred.
    var resolutionRaw: String

    /// Optional linked requirement ID.
    var requirementId: String?

    /// Optional linked gate ID (if decision resulted from approval gate).
    var gateId: UUID?

    init(
        id: UUID = UUID(),
        conversation: Conversation,
        decidedAt: Date = .now,
        decisionKey: String,
        oldValueJSON: String = "{}",
        newValueJSON: String = "{}",
        reasoning: String = "",
        resolution: GateDecision = .implemented,
        requirementId: String? = nil,
        gateId: UUID? = nil
    ) {
        precondition(!decisionKey.isEmpty, "Decision key must not be empty")
        self.id = id
        self.conversation = conversation
        self.conversationId = conversation.id
        self.decidedAt = decidedAt
        self.decisionKey = decisionKey
        self.oldValueJSON = oldValueJSON
        self.newValueJSON = newValueJSON
        self.reasoning = reasoning
        self.resolutionRaw = resolution.rawValue
        self.requirementId = requirementId
        self.gateId = gateId
        Logger.models.info("Decision created id=\(self.id.uuidString.prefix(8)) key=\(self.decisionKey, privacy: .public)")
    }
}

extension Decision {
    /// Typed resolution accessor.
    var resolution: GateDecision {
        get { GateDecision(rawValue: resolutionRaw) ?? .implemented }
        set { resolutionRaw = newValue.rawValue }
    }
}

/// Convenience decision-key prefixes (kept here so consumers don't hardcode strings).
enum DecisionKey {
    static let specApprove = "spec.approve"
    static let specEdit = "spec.edit"
    static let roadmapApprove = "roadmap.approve"
    static let roadmapRefine = "roadmap.refine"
    static let gateApprove = "gate.approve"
    static let gateReject = "gate.reject"
    static let phaseTransition = "phase.transition"
    static let userEdit = "user.edit"
    static let opRollback = "op.rollback"
}
