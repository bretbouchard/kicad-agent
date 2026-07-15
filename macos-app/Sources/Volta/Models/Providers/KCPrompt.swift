//
//  KCPrompt.swift
//  Volta
//
//  Phase 164 — LLM Provider Protocol
//
//  Provider-agnostic prompt envelope. MOD-01 lock: this is the only
//  prompt shape that crosses the provider boundary. Provider classes
//  translate it into FoundationModels.Prompt / MLXLMInput / OpenAI ChatCompletion
//  request / Anthropic Message internally — those SDK types never leak.
//
//  Design rationale: rather than mirrored associated types per provider
//  (which break heterogeneous arrays), we use one struct with optional
//  fields providers may ignore. Provider parity is enforced by tests.
//

import Foundation

/// A request to a language model. Sendable + value-type — safe to share
/// across actors and to retry idempotently.
struct KCPrompt: Sendable, Equatable, Identifiable {
    /// Stable id for tracing / logging. Auto-UUID if not supplied.
    let id: UUID

    /// Ordered conversation turns. System prompt is separate (below).
    var messages: [KCMessage]

    /// Optional system instructions. Provider decides whether to prepend
    /// as a synthetic `.system` message (OpenAI/Anthropic) or use the
    /// framework's native instructions API (FoundationModels).
    var systemPrompt: String?

    /// 0.0–2.0. `nil` means provider default. Local models tend to be
    /// near-deterministic at <=0.2; cloud providers default to ~0.7.
    var temperature: Double?

    /// Hard cap on output tokens. `nil` = provider default.
    var maxTokens: Int?

    /// Vision inputs (schematic screenshots, PCB renders, photos).
    /// Provider decides per-message whether images are bundled inline.
    var attachments: [KCAttachment]

    /// Hint for routing. Provider may ignore. "gemma-4-12b-it-mlx-q4"
    /// style names or "default" / "fast" / "heavy" aliases.
    var preferredModel: String?

    init(
        id: UUID = UUID(),
        messages: [KCMessage] = [],
        systemPrompt: String? = nil,
        temperature: Double? = nil,
        maxTokens: Int? = nil,
        attachments: [KCAttachment] = [],
        preferredModel: String? = nil
    ) {
        precondition(temperature.map { $0 >= 0 && $0 <= 2 } ?? true, "temperature must be 0.0–2.0")
        precondition(maxTokens.map { $0 > 0 } ?? true, "maxTokens must be > 0")
        self.id = id
        self.messages = messages
        self.systemPrompt = systemPrompt
        self.temperature = temperature
        self.maxTokens = maxTokens
        self.attachments = attachments
        self.preferredModel = preferredModel
    }
}

extension KCPrompt {
    /// ponytail: convenience for the most common case — single user message,
    /// no system prompt, no images.
    static func user(_ text: String, preferredModel: String? = nil) -> KCPrompt {
        KCPrompt(
            messages: [KCMessage(role: .user, content: text)],
            preferredModel: preferredModel
        )
    }

    /// ponytail: convenience for system + single user.
    static func systemPlusUser(_ system: String, _ user: String) -> KCPrompt {
        KCPrompt(
            messages: [KCMessage(role: .user, content: user)],
            systemPrompt: system
        )
    }

    /// Total text length across all messages. Used by Router for cost preview.
    var approxInputCharacters: Int {
        (systemPrompt?.count ?? 0) + messages.reduce(0) { $0 + $1.content.count }
    }
}
