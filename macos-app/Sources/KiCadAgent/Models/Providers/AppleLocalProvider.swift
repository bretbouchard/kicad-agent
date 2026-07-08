//
//  AppleLocalProvider.swift
//  KiCadAgent
//
//  Phase 164 — LLM Provider Protocol (Task 2)
//
//  Apple FoundationModels provider — built-in, free, on-device. macOS 27+.
//  MOD-06 lock: FoundationModels is always available as default (free,
//  on-device, no key required). Devices without Apple Intelligence see
//  a banner (ProviderBanner) explaining local-only mode.
//
//  Pitfall 3 prevention: availability is checked at runtime via
//  `SystemLanguageModel.default.availability`, NOT device model detection.
//  This provider reports `.unavailable` on Intel Macs / Macs with Apple
//  Intelligence disabled. ProviderRegistry routes to MLXLocalProvider.
//
//  STACK.md: FoundationModels is the default AI provider (free, built-in,
//  no API keys). Tool calling via GenerationOptions.ToolCallingMode
//  (future Phase 166). Structured output via @Generable macro.
//
//  Concurrency: LanguageModelSession is `@unchecked Sendable`. We create
//  one session per stream/generate call to avoid shared mutable state
//  across tasks. SystemLanguageModel.default is a Sendable singleton.
//

import Foundation
import FoundationModels
import OSLog

/// Apple FoundationModels-backed provider. Free, on-device, macOS 27+.
///
/// Wraps `SystemLanguageModel.default` + per-request `LanguageModelSession`.
/// Reports real availability at launch — Pitfall 3 prevention.
struct AppleLocalProvider: KiCadModelProvider {
    /// Optional injected model. Default uses `SystemLanguageModel.default`
    /// which respects user's Apple Intelligence enrollment. Tests inject
    /// a stub to assert availability logic without hardware differences.
    private let model: SystemLanguageModel

    /// ponytail: no config. Apple built-in framework needs no keys.
    init(model: SystemLanguageModel = .default) {
        self.model = model
    }

    // MARK: - KiCadModelProvider

    var kind: KCProviderKind { .appleLocal }

    var displayName: String { "Apple Intelligence" }

    var availability: KCProviderAvailability {
        get async {
            // Pitfall 3: query the framework, not the device model.
            switch model.availability {
            case .available:
                return .available
            case .unavailable(let reason):
                return .unavailable(reason: humanReadableUnavailable(reason))
            @unknown default:
                return .unavailable(reason: "Unknown FoundationModels availability")
            }
        }
    }

    func stream(_ request: KCPrompt) async throws -> AsyncThrowingStream<KCToken, Error> {
        // Re-check availability before constructing a session — don't let
        // an unavailable model proceed to a cryptic FoundationModels error.
        let avail = await self.availability
        guard avail.isAvailable else {
            throw KCProviderError.unavailable(reason: "Apple Intelligence not available on this device")
        }

        // Each request gets a fresh session — sessions are not safe to
        // share across tasks (mutable transcript state inside).
        let session = LanguageModelSession(model: model)
        let prompt = AppleLocalProvider.bridge(request)
        let options = AppleLocalProvider.generationOptions(for: request)

        // streamResponse is `nonisolated(nonsending)`. We pass `request`
        // and `session` by sending into the stream — both are Sendable.
        return AsyncThrowingStream { continuation in
            // ponytail: Task.detached is wrong here (breaks priority inheritance).
            // Use structured-style Task with explicit Sendable capture to satisfy
            // Swift 6's sending-closure-risks-data-race diagnostic. We move the
            // ResponseStream into the closure by sending each snapshot delta.
            let yield = continuation
            let sessionRef = session
            let promptStr = prompt
            let opts = options
            let approxInput = AppleLocalProvider.estimateTokens(request.approxInputCharacters)

            Task { [sessionRef, promptStr, opts, approxInput] in
                do {
                    let responseStream = sessionRef.streamResponse(to: promptStr, options: opts)
                    var outputTokenCount = 0
                    for try await snapshot in responseStream {
                        let chunk = snapshot.content
                        outputTokenCount += AppleLocalProvider.estimateTokens(chunk)
                        yield.yield(.text(chunk))
                    }
                    yield.yield(.usage(KCUsage.free(
                        input: approxInput,
                        output: outputTokenCount
                    )))
                    yield.yield(.done(.complete))
                    yield.finish()
                } catch is CancellationError {
                    yield.yield(.done(.cancelled))
                    yield.finish()
                } catch let error as LanguageModelSession.GenerationError {
                    AppleLocalProvider.handleGenerationError(error, continuation: yield)
                } catch {
                    yield.yield(.done(.error))
                    yield.finish(throwing: KCProviderError.requestFailed(underlying: error))
                }
            }
        }
    }

    // MARK: - Bridging

    /// Translate KCPrompt into FoundationModels native prompt. MOD-01:
    /// SDK type never escapes this file — caller only sees KCPrompt.
    private static func bridge(_ request: KCPrompt) -> String {
        // ponytail: for Phase 164 we use the string-form prompt API.
        // Multi-message + system prompt flattens into a single string.
        // Phase 165 Router upgrades to native Prompt segments + tools.
        var parts: [String] = []
        if let system = request.systemPrompt, !system.isEmpty {
            parts.append("Instructions: \(system)")
        }
        for message in request.messages {
            switch message.role {
            case .system:
                if !message.content.isEmpty { parts.append("Instructions: \(message.content)") }
            case .user:
                parts.append("User: \(message.content)")
            case .assistant:
                parts.append("Assistant: \(message.content)")
            case .tool:
                parts.append("Tool result: \(message.content)")
            }
        }
        return parts.joined(separator: "\n\n")
    }

    /// Map KCPrompt temperature/maxTokens to FoundationModels options.
    private static func generationOptions(for request: KCPrompt) -> GenerationOptions {
        GenerationOptions(
            temperature: request.temperature,
            maximumResponseTokens: request.maxTokens
        )
    }

    /// Convert FoundationModels GenerationError into a stream-terminating
    /// KCProviderError. Localized + actionable per Pitfall 3.
    private static func handleGenerationError(
        _ error: LanguageModelSession.GenerationError,
        continuation: AsyncThrowingStream<KCToken, Error>.Continuation
    ) {
        let mapped: KCProviderError
        switch error {
        case .exceededContextWindowSize(let ctx):
            // Context struct only carries debugDescription in macOS 26 SDK.
            // Surface that — Router can re-derive context size from the original
            // KCPrompt if needed (request.approxInputCharacters / 4 heuristic).
            mapped = .contextLengthExceeded(
                inputTokens: AppleLocalProvider.estimateTokens(ctx.debugDescription),
                max: 0 // unknown — provider didn't disclose limit
            )
        case .rateLimited:
            mapped = .rateLimited(retryAfter: nil)
        case .refusal:
            mapped = .requestFailed(underlying: error)
        case .assetsUnavailable, .guardrailViolation, .unsupportedGuide,
             .unsupportedLanguageOrLocale, .decodingFailure, .concurrentRequests:
            mapped = .requestFailed(underlying: error)
        @unknown default:
            mapped = .requestFailed(underlying: error)
        }
        continuation.yield(.done(.error))
        continuation.finish(throwing: mapped)
    }

    /// ponytail: FoundationModels doesn't expose token counts. Use 4 chars/token
    /// heuristic — matches OpenAI's rule of thumb well enough for UI display.
    private static func estimateTokens(_ text: String) -> Int {
        max(1, text.count / 4)
    }

    private static func estimateTokens(_ chars: Int) -> Int {
        max(1, chars / 4)
    }

    /// User-facing string for each UnavailableReason. MOD-06 augmentation:
    /// banner explains "local-only mode" — never cryptic SDK enum names.
    private func humanReadableUnavailable(_ reason: SystemLanguageModel.Availability.UnavailableReason) -> String {
        switch reason {
        case .deviceNotEligible:
            return "This Mac doesn't meet Apple Intelligence requirements (Apple Silicon, 8GB+ RAM). Local MLX models still work."
        case .appleIntelligenceNotEnabled:
            return "Apple Intelligence isn't enabled. Open System Settings → Apple Intelligence & Siri to enable, or use local MLX models."
        case .modelNotReady:
            return "Apple Intelligence is still preparing. Try again in a moment, or use a local MLX model."
        @unknown default:
            return "Apple Intelligence isn't available right now."
        }
    }
}
