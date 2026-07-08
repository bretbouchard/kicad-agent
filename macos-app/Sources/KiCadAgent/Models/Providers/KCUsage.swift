//
//  KCUsage.swift
//  KiCadAgent
//
//  Phase 164 — LLM Provider Protocol
//
//  Token accounting for one request. FoundationModels and MLX-Swift
//  return zero cost (free, on-device). Cloud providers compute cost from
//  their published price-per-token rates — Router (Phase 165) surfaces
//  this to MOD-12 ("App shows token usage and cost estimate per message").
//
//  ponytail: Decimal for cost — never Float for money.
//

import Foundation

struct KCUsage: Sendable, Equatable {
    /// Prompt tokens consumed (includes system prompt + images).
    var inputTokens: Int

    /// Completion tokens generated.
    var outputTokens: Int

    /// Tokens served from prompt cache (OpenAI prompt caching, Anthropic
    /// cache_control). Counted in inputTokens too — this is the subset
    /// billed at the cache rate.
    var cachedInputTokens: Int

    /// Estimated cost in USD. 0 for local providers. Use Decimal — never
    /// Double for money.
    var estimatedCostUSD: Decimal

    init(
        inputTokens: Int = 0,
        outputTokens: Int = 0,
        cachedInputTokens: Int = 0,
        estimatedCostUSD: Decimal = 0
    ) {
        precondition(inputTokens >= 0)
        precondition(outputTokens >= 0)
        precondition(cachedInputTokens >= 0)
        precondition(estimatedCostUSD >= 0)
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.cachedInputTokens = cachedInputTokens
        self.estimatedCostUSD = estimatedCostUSD
    }
}

extension KCUsage {
    /// ponytail: local providers (FoundationModels, MLX) all return this.
    /// Keeps token counts honest when we don't know them — Apple doesn't
    /// expose FoundationModels token counts in macOS 26.
    static let zeroCost = KCUsage()

    /// ponytail: convenience for tests + non-billing paths.
    static func free(input: Int, output: Int) -> KCUsage {
        KCUsage(inputTokens: input, outputTokens: output, estimatedCostUSD: 0)
    }
}
