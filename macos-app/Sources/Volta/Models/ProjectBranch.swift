//
//  ProjectBranch.swift
//  Volta
//
//  Phase 186 — Project Genealogy
//
//  SwiftData @Model for a branch in a project's family tree. Branches
//  represent forks (CHAT-08), false starts, and alternative explorations.
//
//  GEN-01 through GEN-05: genealogy requirements.
//

import Foundation
import SwiftData
import OSLog

/// A branch in a project's family tree.
///
/// Branches track forks (CHAT-08), false starts, and rejections. Together
/// with `Conversation.parentConversationId`, they form a forest of project
/// histories that the genealogy view visualizes.
@Model
final class ProjectBranch {
    /// Stable identifier.
    @Attribute(.unique) var id: UUID

    /// Owning project.
    var project: Project?

    /// Foreign key.
    var projectId: UUID

    /// Branch type — what kind of branch this is.
    var branchTypeRaw: String

    /// Parent branch ID (nil for root).
    var parentBranchId: UUID?

    /// Branch label (user-facing).
    var label: String

    /// When this branch was created.
    var createdAt: Date

    /// When this branch was finalized (or nil if still active).
    var finalizedAt: Date?

    /// Outcome — what happened to this branch.
    var outcomeRaw: String?

    /// Optional note explaining the branch.
    var note: String

    init(
        id: UUID = UUID(),
        project: Project,
        branchType: BranchType,
        parentBranchId: UUID? = nil,
        label: String,
        createdAt: Date = .now,
        finalizedAt: Date? = nil,
        outcome: BranchOutcome? = nil,
        note: String = ""
    ) {
        precondition(!label.isEmpty, "Branch label must not be empty")
        self.id = id
        self.project = project
        self.projectId = project.id
        self.branchTypeRaw = branchType.rawValue
        self.parentBranchId = parentBranchId
        self.label = label
        self.createdAt = createdAt
        self.finalizedAt = finalizedAt
        self.outcomeRaw = outcome?.rawValue
        self.note = note
        Logger.models.info("ProjectBranch created label=\(self.label, privacy: .public)")
    }
}

extension ProjectBranch {
    var branchType: BranchType {
        get { BranchType(rawValue: branchTypeRaw) ?? .exploration }
        set { branchTypeRaw = newValue.rawValue }
    }

    var outcome: BranchOutcome? {
        get { outcomeRaw.flatMap(BranchOutcome.init(rawValue:)) }
        set { outcomeRaw = newValue?.rawValue }
    }
}

/// Type of branch — what triggered it.
enum BranchType: String, Codable, Sendable, CaseIterable {
    case fork              // User edited + re-submitted (CHAT-08)
    case falseStart        // User abandoned an early path
    case exploration       // Alternative exploration in parallel
    case rollback          // Restore to past state created a new branch
    case continuation      // Normal continuation of the project
}

/// Outcome of a branch — what happened to it.
enum BranchOutcome: String, Codable, Sendable, CaseIterable {
    case active       // Still in progress
    case merged       // Branch content was merged back into parent
    case abandoned    // User abandoned the branch
    case superseded   // A newer branch replaced this one
}
