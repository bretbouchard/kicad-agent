//
//  KCDoneReason.swift
//  Volta
//
//  Phase 164 — LLM Provider Protocol
//
//  Why a stream ended. Maps to OpenAI `finish_reason`, Anthropic `stop_reason`,
//  FoundationModels terminal snapshot, MLX end-of-generation. Exhaustive.
//

import Foundation

enum KCDoneReason: Sendable, Equatable {
    /// Model finished naturally — emitted stop token or reached end of generation.
    case complete

    /// Hit `maxTokens` cap. Caller can continue with a follow-up turn.
    case truncated

    /// Caller cancelled (Task.cancel). Provider stream throws CancellationError.
    case cancelled

    /// Provider-specific error — stream throws the matching KCProviderError.
    case error
}
