//
//  Conversation.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//  Phase 173 — GSD Conversation Engine (fork support — CHAT-08, GEN-01)
//
//  SwiftData @Model for a conversation within a Project.
//
//  Phase 161 stores the conversation envelope only. Message content
//  (MEM-01 through MEM-10) lands in Phase 168 (Track E — Memory).
//  Phase 173 adds conversation forking for edit-and-resubmit (CHAT-08).
//

import Foundation
import SwiftData
import OSLog

/// A conversation within a Project.
///
/// Conversations are append-only (MEM-03) — never truncated, never lost.
/// Phase 168 adds the `Message` model with full event-sourced semantics
/// (decisions, value changes, op journal entries).
///
/// Phase 173 adds fork support: a conversation may have a parent
/// (the original conversation it was forked from) and a marker for
/// which message triggered the fork. The fork cap is enforced in
/// the GSD engine layer (T-173-04).
@Model
final class Conversation {
    /// Stable identifier.
    @Attribute(.unique) var id: UUID

    /// Owning project. Inverse of `Project.conversations`.
    var project: Project?

    /// Foreign key kept denormalized for queries without joins.
    var projectId: UUID

    /// User-facing title. Auto-derived from first message (Phase 165).
    var title: String

    /// When the conversation started (UTC).
    var startedAt: Date

    /// Last activity timestamp. Bumped on every appended message.
    var lastActivityAt: Date

    /// Phase 173 — parent conversation if this is a fork, nil for original.
    /// CHAT-08: edit-and-resubmit creates a new conversation referencing the original.
    var parentConversationId: UUID?

    /// Phase 173 — message ID that the user edited to trigger this fork.
    /// Helps the timeline show "forked from <message>" badges.
    var forkedFromMessageId: UUID?

    /// Phase 176 — messages belonging to this conversation (MEM-01, MEM-03).
    @Relationship(deleteRule: .cascade, inverse: \Message.conversation)
    var messages: [Message] = []

    /// Phase 176 — decisions made during this conversation (MEM-04).
    @Relationship(deleteRule: .cascade, inverse: \Decision.conversation)
    var decisions: [Decision] = []

    /// Phase 176 — field-level value changes (MEM-05).
    @Relationship(deleteRule: .cascade, inverse: \ValueChange.conversation)
    var valueChanges: [ValueChange] = []

    /// Phase 176 — point-in-time snapshots for fast time-travel (MEM-06).
    @Relationship(deleteRule: .cascade, inverse: \ProjectSnapshot.conversation)
    var snapshots: [ProjectSnapshot] = []

    init(
        id: UUID = UUID(),
        project: Project,
        title: String = "New Conversation",
        startedAt: Date = .now,
        lastActivityAt: Date = .now,
        parentConversationId: UUID? = nil,
        forkedFromMessageId: UUID? = nil
    ) {
        precondition(!title.isEmpty, "Conversation title must not be empty")
        self.id = id
        self.project = project
        self.projectId = project.id
        self.title = title
        self.startedAt = startedAt
        self.lastActivityAt = lastActivityAt
        self.parentConversationId = parentConversationId
        self.forkedFromMessageId = forkedFromMessageId
        Logger.models.info("Conversation created id=\(self.id.uuidString.prefix(8)) projectId=\(self.projectId.uuidString.prefix(8)) fork=\(self.parentConversationId != nil)")
    }
}

extension Conversation {
    /// Mark touched — bump lastActivityAt on any append.
    func touch() {
        lastActivityAt = .now
        project?.touch()
    }

    /// True if this conversation is a fork (has a parent).
    var isFork: Bool { parentConversationId != nil }

    /// Create a fork of this conversation, copying envelope state.
    /// Caller is responsible for re-appending messages up to the fork point.
    func makeFork(forkedFromMessageId: UUID, title: String? = nil) -> Conversation {
        Conversation(
            project: project!,
            title: title ?? "\(self.title) (fork)",
            parentConversationId: self.id,
            forkedFromMessageId: forkedFromMessageId
        )
    }
}
