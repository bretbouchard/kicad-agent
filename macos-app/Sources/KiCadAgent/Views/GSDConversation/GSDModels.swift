//
//  GSDModels.swift
//  KiCadAgent
//
//  Phase 173 — GSD Conversation Engine
//
//  Value types for the GSD methodology: ProjectSpec, ProjectRoadmap,
//  RoadmapPhase, CompletionSummary, ConversationFork.
//
//  These are UI-facing structs (not SwiftData @Model). The @Model
//  layer (Project, Conversation, Decision) is in Models/. GSDModels
//  bridge between LLM output and SwiftData persistence.
//
//  T-173-02: All user-edited fields length-capped (max 1000 chars).
//  GSD-01/02/03/08: GSD methodology requirements.
//

import Foundation

/// A structured project specification produced from questioning.
///
/// GSD-02: spec card generation.
struct ProjectSpec: Identifiable, Sendable, Equatable {
    let id: UUID
    var title: String
    var goalStatement: String
    var requirements: [String]
    var successCriteria: [String]
    var constraints: ProjectConstraints

    init(
        id: UUID = UUID(),
        title: String = "",
        goalStatement: String = "",
        requirements: [String] = [],
        successCriteria: [String] = [],
        constraints: ProjectConstraints = ProjectConstraints()
    ) {
        self.id = id
        self.title = title
        self.goalStatement = goalStatement
        self.requirements = requirements
        self.successCriteria = successCriteria
        self.constraints = constraints
    }

    /// Default spec for "Use defaults" skip path.
    static var defaultSpec: ProjectSpec {
        ProjectSpec(
            title: "Untitled Project",
            goalStatement: "Design a hardware circuit per user's high-level intent.",
            requirements: ["Circuit must be electrically valid (ERC passes)."],
            successCriteria: ["KiCad project exports without errors."],
            constraints: ProjectConstraints()
        )
    }
}

/// Project-level constraints captured during questioning.
struct ProjectConstraints: Sendable, Equatable, Codable {
    var budgetUSD: String?
    var sizeMM: String?
    var powerV: String?
    var otherNotes: String?

    static let empty = ProjectConstraints()
}

/// A single phase in a project roadmap.
struct RoadmapPhase: Identifiable, Sendable, Equatable {
    let id: UUID
    var name: String
    var goal: String
    var requirements: [String]
    var successCriteria: [String]
    var estimatedDurationLabel: String
    var dependencies: [UUID] // IDs of phases this depends on

    init(
        id: UUID = UUID(),
        name: String,
        goal: String,
        requirements: [String] = [],
        successCriteria: [String] = [],
        estimatedDurationLabel: String = "—",
        dependencies: [UUID] = []
    ) {
        self.id = id
        self.name = name
        self.goal = goal
        self.requirements = requirements
        self.successCriteria = successCriteria
        self.estimatedDurationLabel = estimatedDurationLabel
        self.dependencies = dependencies
    }
}

/// A full project roadmap — ordered list of phases.
///
/// GSD-03: roadmap generation.
struct ProjectRoadmap: Identifiable, Sendable, Equatable {
    let id: UUID
    var phases: [RoadmapPhase]

    init(id: UUID = UUID(), phases: [RoadmapPhase] = []) {
        self.id = id
        self.phases = phases
    }

    /// Default 5-phase roadmap for "Use defaults" path.
    static var defaultRoadmap: ProjectRoadmap {
        ProjectRoadmap(phases: [
            RoadmapPhase(name: "Foundation", goal: "Establish app shell + daemon + governance", estimatedDurationLabel: "1 week"),
            RoadmapPhase(name: "Models", goal: "Wire LLM providers + BYOK", estimatedDurationLabel: "1 week"),
            RoadmapPhase(name: "UI Surfaces", goal: "Build Liquid Glass chat + pipeline views", estimatedDurationLabel: "2 weeks"),
            RoadmapPhase(name: "Memory", goal: "SwiftData + CloudKit + Time-travel", estimatedDurationLabel: "1 week"),
            RoadmapPhase(name: "Ship", goal: "Fastlane + TestFlight", estimatedDurationLabel: "3 days"),
        ])
    }
}

/// Completion summary shown when a phase finishes.
///
/// GSD-08: completion summary.
struct CompletionSummary: Sendable, Equatable {
    let phaseName: String
    let schematicPath: URL?
    let pcbPath: URL?
    let exports: [ExportArtifact]
    let decisionsCount: Int
    let totalDurationSeconds: Int

    init(
        phaseName: String,
        schematicPath: URL? = nil,
        pcbPath: URL? = nil,
        exports: [ExportArtifact] = [],
        decisionsCount: Int = 0,
        totalDurationSeconds: Int = 0
    ) {
        self.phaseName = phaseName
        self.schematicPath = schematicPath
        self.pcbPath = pcbPath
        self.exports = exports
        self.decisionsCount = decisionsCount
        self.totalDurationSeconds = totalDurationSeconds
    }

    /// Human-readable total duration ("2h 34m" / "12m" / "45s").
    var formattedDuration: String {
        if totalDurationSeconds < 60 { return "\(totalDurationSeconds)s" }
        let minutes = totalDurationSeconds / 60
        let remSeconds = totalDurationSeconds % 60
        if minutes < 60 { return "\(minutes)m \(remSeconds)s" }
        let hours = minutes / 60
        let remMinutes = minutes % 60
        return "\(hours)h \(remMinutes)m"
    }
}

/// Export artifact metadata — for display in completion summary.
struct ExportArtifact: Identifiable, Sendable, Equatable {
    let id: UUID
    let fileName: String
    let fileSizeBytes: Int64
    let kind: ExportKind

    init(id: UUID = UUID(), fileName: String, fileSizeBytes: Int64, kind: ExportKind) {
        self.id = id
        self.fileName = fileName
        self.fileSizeBytes = fileSizeBytes
        self.kind = kind
    }

    var formattedSize: String {
        ByteCountFormatter.string(fromByteCount: fileSizeBytes, countStyle: .file)
    }
}

enum ExportKind: String, Sendable, Equatable {
    case gerber
    case drill
    case bom
    case position
    case step
    case other
}

/// Validator for spec fields (T-173-02 mitigation).
enum SpecValidator {
    /// Max length per spec field. HTML chars are stripped in sanitization.
    static let maxFieldLength = 1000

    /// True if the given text is within length limits.
    static func isWithinLength(_ text: String) -> Bool {
        text.count <= maxFieldLength
    }

    /// Sanitize potentially unsafe text (strip script tags, event handlers).
    /// T-173-02: mitigation for LLM-injected XSS / HTML.
    static func sanitize(_ text: String) -> String {
        var sanitized = text
        // Strip script blocks (case-insensitive).
        let scriptPattern = "<script[^>]*>[\\s\\S]*?</script>"
        if let regex = try? NSRegularExpression(pattern: scriptPattern, options: .caseInsensitive) {
            let range = NSRange(sanitized.startIndex..., in: sanitized)
            sanitized = regex.stringByReplacingMatches(in: sanitized, range: range, withTemplate: "")
        }
        // Strip on* event handlers (onclick, onerror, etc.).
        let eventPattern = "\\son\\w+\\s*=\\s*\"[^\"]*\""
        if let regex = try? NSRegularExpression(pattern: eventPattern, options: .caseInsensitive) {
            let range = NSRange(sanitized.startIndex..., in: sanitized)
            sanitized = regex.stringByReplacingMatches(in: sanitized, range: range, withTemplate: "")
        }
        return sanitized
    }
}

/// Fork limiter — enforces T-173-04 (fork spam cap).
enum ForkLimiter {
    static let maxForksPerConversation = 100
    static let warningThreshold = 80

    enum ForkDecision: Sendable, Equatable {
        case allow(remaining: Int)
        case warn(remaining: Int)
        case deny
    }

    static func evaluate(currentForkCount: Int) -> ForkDecision {
        if currentForkCount >= maxForksPerConversation {
            return .deny
        }
        if currentForkCount >= warningThreshold {
            return .warn(remaining: maxForksPerConversation - currentForkCount)
        }
        return .allow(remaining: maxForksPerConversation - currentForkCount)
    }
}
