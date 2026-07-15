//
//  KCProviderAvailability.swift
//  Volta
//
//  Phase 164 — LLM Provider Protocol
//
//  Provider availability state. Pitfall 3 prevention: FoundationModels
//  reports `.unavailable` on Intel Macs / Macs without Apple Intelligence —
//  ProviderRegistry routes to MLX instead. Pitfall 7 prevention: MLX
//  reports `.unavailable` when VRAM < model requirement.
//
//  ponytail: enum with associated value. Exhaustive switching in Router.
//

import Foundation

enum KCProviderAvailability: Sendable, Equatable {
    /// Provider is ready to serve requests right now.
    case available

    /// Provider exists but cannot serve requests. Reason is user-readable.
    /// Examples:
    ///   - FoundationModels on Intel Mac: "Apple Intelligence not enabled"
    ///   - MLX without model downloaded: "Download a model from the catalog"
    ///   - Cloud provider without API key: "Add your OpenAI key in Settings"
    case unavailable(reason: String)

    /// Provider needs user action (key entry, model download) but is
    /// otherwise configured. UI surfaces a deep-link.
    case requiresKey(providerHint: String)

    /// True only when available. Convenience for Router filters.
    var isAvailable: Bool {
        if case .available = self { return true }
        return false
    }
}
