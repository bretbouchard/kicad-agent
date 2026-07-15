//
//  KCTask.swift
//  Volta
//
//  Phase 165 — Provider Router
//
//  Task classification envelope. MOD-02: App routes model calls based on
//  task type (privacy mode → local, vision needed → cloud/MLX, complex
//  reasoning → user's preferred). KCTask is the input to KiCadModelRouter;
//  KCTaskClassifier derives it from a KCPrompt using heuristics.
//
//  ponytail: a value type with clear fields. No stringly-typed "task hints" —
//  every router decision comes from a typed field here. Adding a task
//  dimension (e.g. tool-use required) is a compiler-checked change.
//

import Foundation

/// One unit of work the model router dispatches.
///
/// Built from a `KCPrompt` by `KCTaskClassifier`. The router consumes
/// `taskType`, `requiresVision`, `requiresPrivacy`, and `complexity` to
/// pick a provider per MOD-02 / MOD-10 / MOD-11.
struct KCTask: Sendable, Equatable, Identifiable {
    let id: UUID

    /// Primary task family. Drives the router's per-task default mapping
    /// (see `KiCadModelRouter.defaultProvider(for:)`).
    var taskType: KCTaskType

    /// True when the prompt carries image attachments or names a vision
    /// model. Per MOD-02: vision → cloud with vision capability OR MLX
    /// with Gemma vision.
    var requiresVision: Bool

    /// True when the user/system marked the prompt privacy-sensitive
    /// (e.g. contains proprietary schematic, NDA material). Per MOD-02:
    /// privacySensitive → always AppleLocal, never cloud.
    var requiresPrivacy: Bool

    /// 0.0–1.0. Higher = more reasoning / longer generation. Used by the
    /// router to decide whether a "quickReply" with high complexity should
    /// route to a heavier model. 0.0 means unset / unknown.
    var complexity: Double

    init(
        id: UUID = UUID(),
        taskType: KCTaskType,
        requiresVision: Bool = false,
        requiresPrivacy: Bool = false,
        complexity: Double = 0
    ) {
        precondition(complexity >= 0 && complexity <= 1, "complexity must be 0.0–1.0")
        self.id = id
        self.taskType = taskType
        self.requiresVision = requiresVision
        self.requiresPrivacy = requiresPrivacy
        self.complexity = complexity
    }
}

/// Task family. Per MOD-02: each family has routing rules.
///
/// - Note: `quickReply`, `complexReasoning`, `vision`, and `privacySensitive`
///   are the four user-visible categories from MOD-10 ("User can pick
///   preferred model per task type"). The other cases cover internal
///   pipeline stages — the classifier maps them onto these four for
///   preference lookup.
enum KCTaskType: String, Sendable, Equatable, Codable, CaseIterable {
    /// Short conversational reply. Routes to AppleLocal (free, fast).
    case quickReply

    /// Long-form reasoning, multi-step planning, codegen. Routes to user's
    /// preferred cloud model when configured (per MOD-10), else AppleLocal.
    case complexReasoning

    /// Image input — schematic screenshot, PCB render, photo. Routes to a
    /// vision-capable cloud model (per MOD-02) when configured, else MLX
    /// Gemma vision when downloaded, else AppleLocal with a notification.
    case vision

    /// User/system marked this prompt as privacy-sensitive (proprietary
    /// schematic, NDA material). Per MOD-02: ALWAYS AppleLocal. Never cloud.
    case privacySensitive

    // MARK: - Internal pipeline stages (map onto the four above for prefs)

    /// Circuit generation (SKIDL emit). Heuristic default: MLX local.
    case circuitGeneration

    /// PCB routing strategy (Gemma 4 12B V2 vision per Phase 98). Heuristic
    /// default: MLX local vision. Treated as `vision` for prefs lookup.
    case pcbRouting

    /// Board analysis (DRC/ERC explanation, BOM summary). Heuristic default:
    /// AppleLocal.
    case boardAnalysis

    /// Conversation history summarization. Heuristic default: AppleLocal.
    case conversationHistory

    /// Circuit theory questions ("Why use decoupling?", "How do opamps work?").
    /// Routes to MLX local with v5 adapter (theory-trained).
    case circuitTheory

    /// SPICE simulation requests ("Simulate this filter", "Verify gain").
    /// Routes to MLX local with v5 adapter (SPICE-trained).
    case spiceSimulation

    /// User-facing display name for Settings UI.
    var displayName: String {
        switch self {
        case .quickReply: return "Quick Replies"
        case .complexReasoning: return "Complex Reasoning"
        case .vision: return "Vision Tasks"
        case .privacySensitive: return "Privacy-Sensitive"
        case .circuitGeneration: return "Circuit Generation"
        case .pcbRouting: return "PCB Routing"
        case .boardAnalysis: return "Board Analysis"
        case .conversationHistory: return "Conversation History"
        case .circuitTheory: return "Circuit Theory"
        case .spiceSimulation: return "SPICE Simulation"
        }
    }

    /// Short helper description shown under the picker in Settings.
    var roleDescription: String {
        switch self {
        case .quickReply:
            return "Short answers, acks, and clarifications."
        case .complexReasoning:
            return "Multi-step planning, codegen, schematic reasoning."
        case .vision:
            return "Schematic screenshots, PCB renders, photos."
        case .privacySensitive:
            return "Forced to Apple Intelligence. Never sent to cloud."
        case .circuitGeneration:
            return "Emitting SKIDL / KiCad schematics from intent."
        case .pcbRouting:
            return "Strategy advisor for trace routing."
        case .boardAnalysis:
            return "Explaining ERC/DRC findings, BOM summaries."
        case .conversationHistory:
            return "Summarizing long conversations to save context."
        case .circuitTheory:
            return "Explaining circuit physics, component selection, design rules."
        case .spiceSimulation:
            return "Generating netlists, running ngspice, interpreting results."
        }
    }

    /// The "user-visible" category this internal stage maps to for the
    /// Settings preference lookup. `quickReply`, `complexReasoning`,
    /// `vision`, `privacySensitive` map to themselves.
    var preferenceCategory: KCTaskType {
        switch self {
        case .quickReply, .complexReasoning, .vision, .privacySensitive:
            return self
        case .circuitGeneration, .boardAnalysis, .conversationHistory,
             .circuitTheory, .spiceSimulation:
            return .complexReasoning
        case .pcbRouting:
            return .vision
        }
    }
}
