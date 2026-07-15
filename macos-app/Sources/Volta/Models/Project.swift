//
//  Project.swift
//  Volta
//
//  Phase 161 — App Shell Foundation
//
//  SwiftData @Model for a KiCad Agent project.
//
//  A Project is the top-level container for conversations, decisions, and
//  derived artifacts (schematic, PCB, renders). Stored as .kicadagent bundle
//  in Track F. Conversation state IS source of truth (GENOUT-01).
//

import Foundation
import SwiftData
import OSLog

/// A KiCad Agent project. Top-level container for the closed-box design loop.
///
/// Per PROJECT.md: conversation state IS source of truth; .kicad_sch/.kicad_pcb
/// are derived artifacts regenerable from the journal (GENOUT-01, GENOUT-02).
@Model
final class Project {
    /// Stable identifier. UUID v4 — never user-visible.
    @Attribute(.unique) var id: UUID

    /// User-facing project name. Editable from sidebar.
    var name: String

    /// Optional description shown in sidebar subtitle.
    var projectDescription: String

    /// Creation timestamp (UTC). Set once at init.
    var createdAt: Date

    /// Last user-driven modification. Updated on every op call.
    var lastModifiedAt: Date

    /// Conversations belonging to this project.
    /// ponytail: inverse relationship keeps SwiftData graph consistent.
    @Relationship(deleteRule: .cascade, inverse: \Conversation.project)
    var conversations: [Conversation] = []

    init(
        id: UUID = UUID(),
        name: String,
        projectDescription: String = "",
        createdAt: Date = .now,
        lastModifiedAt: Date = .now
    ) {
        precondition(!name.isEmpty, "Project name must not be empty — UI must enforce before init")
        self.id = id
        self.name = name
        self.projectDescription = projectDescription
        self.createdAt = createdAt
        self.lastModifiedAt = lastModifiedAt
        Logger.models.info("Project created id=\(self.id.uuidString.prefix(8)) name=\(self.name, privacy: .public)")
    }
}

extension Project {
    /// Default name for new projects. User can rename from sidebar.
    static let defaultName = "Untitled Project"

    /// Factory for the canonical "new project" instance used by the New button.
    static func newDefault() -> Project {
        Project(name: defaultName)
    }

    /// Mark touched — call on any user-driven mutation to bump `lastModifiedAt`.
    /// ponytail: one method, called everywhere, prevents stale timestamps.
    func touch() {
        lastModifiedAt = .now
    }
}
