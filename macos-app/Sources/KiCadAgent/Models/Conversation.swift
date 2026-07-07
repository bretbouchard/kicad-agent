//
//  Conversation.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//
//  SwiftData @Model for a conversation within a Project.
//
//  Phase 161 stores the conversation envelope only. Message content
//  (MEM-01 through MEM-10) lands in Phase 168 (Track E — Memory).
//

import Foundation
import SwiftData
import OSLog

/// A conversation within a Project.
///
/// Conversations are append-only (MEM-03) — never truncated, never lost.
/// Phase 168 adds the `Message` model with full event-sourced semantics
/// (decisions, value changes, op journal entries).
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

    init(
        id: UUID = UUID(),
        project: Project,
        title: String = "New Conversation",
        startedAt: Date = .now,
        lastActivityAt: Date = .now
    ) {
        precondition(!title.isEmpty, "Conversation title must not be empty")
        self.id = id
        self.project = project
        self.projectId = project.id
        self.title = title
        self.startedAt = startedAt
        self.lastActivityAt = lastActivityAt
        Logger.models.info("Conversation created id=\(self.id.uuidString.prefix(8)) projectId=\(self.projectId.uuidString.prefix(8))")
    }
}

extension Conversation {
    /// Mark touched — bump lastActivityAt on any append.
    func touch() {
        lastActivityAt = .now
        project?.touch()
    }
}
