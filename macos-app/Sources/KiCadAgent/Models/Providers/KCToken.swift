//
//  KCToken.swift
//  KiCadAgent
//
//  Phase 164 — LLM Provider Protocol
//
//  Stream events from `KiCadModelProvider.stream(_:)`. MOD-01 lock: every
//  streaming model output flows through this enum. SDK types
//  (LanguageModelSession.ResponseStream, MLXLM TokenIterator,
//  OpenAI ChatCompletionChunk, Anthropic MessageStreamEvent) never leak.
//
//  ponytail: one enum with associated values. Exhaustive switching forces
//  consumers to handle every case at compile time.
//

import Foundation

/// A single streaming event. Providers emit these in order; consumers
/// (ConversationEngine, Phase 165) accumulate text and observe usage/done.
enum KCToken: Sendable, Equatable {
    /// Incremental text chunk. Concatenate in arrival order.
    case text(String)

    /// Model is calling a tool. Phase 166+ wiring; FoundationModels
    /// supports this natively via GenerationOptions.toolCallingMode.
    case toolCall(KCToolCall)

    /// Token accounting for the completed request. Emitted once near the
    /// end of the stream. Local models (FoundationModels, MLX) may emit
    /// with zero cost — see KCUsage.cost.
    case usage(KCUsage)

    /// Stream completed. Always the last event before the stream ends.
    /// Errors throw instead — `.done` is only for clean completion.
    case done(KCDoneReason)
}

/// Tool-call payload. Phase 165+ uses this when routing needs tools.
/// Phase 164 ships the type so providers can populate it.
struct KCToolCall: Sendable, Equatable, Identifiable {
    let id: String
    var name: String
    /// JSON-encoded arguments string. Caller decodes per tool schema.
    var argumentsJSON: String
}
