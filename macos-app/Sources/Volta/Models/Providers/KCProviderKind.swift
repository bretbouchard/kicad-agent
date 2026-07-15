//
//  KCProviderKind.swift
//  Volta
//
//  Phase 164 — LLM Provider Protocol
//
//  Category tag for each provider. Drives:
//  - UI grouping in Settings ("Local", "Cloud")
//  - Router privacy decisions (MOD-02: privacy mode → local)
//  - Cost estimation defaults (local = free)
//  - Banner logic (ProviderBanner shows when no cloud + FoundationModels down)
//
//  ponytail: enum not stringly-typed. New provider kinds get compile-checked.
//

import Foundation

enum KCProviderKind: String, Sendable, Equatable, CaseIterable, Codable {
    /// Apple FoundationModels — built-in, free, on-device. macOS 27+.
    case appleLocal

    /// MLX-Swift in-process — local, free, requires user-downloaded model.
    case mlxLocal

    // Cloud providers (Phase 166 BYOK wiring; Phase 164 ships enum only).
    case openAI
    case anthropic
    case gemini
    case groq
    case xai
    case together
    case ollama

    /// Tests + previews. Never used in production paths.
    case mock

    /// Convenience: on-device providers (no network, no key, no cost).
    var isLocal: Bool {
        switch self {
        case .appleLocal, .mlxLocal, .ollama, .mock: return true
        case .openAI, .anthropic, .gemini, .groq, .xai, .together: return false
        }
    }

    /// User-facing label for Settings UI.
    var displayName: String {
        switch self {
        case .appleLocal: return "Apple Intelligence"
        case .mlxLocal: return "MLX (local)"
        case .openAI: return "OpenAI"
        case .anthropic: return "Anthropic"
        case .gemini: return "Google Gemini"
        case .groq: return "Groq"
        case .xai: return "xAI"
        case .together: return "Together"
        case .ollama: return "Ollama"
        case .mock: return "Mock (testing)"
        }
    }
}
