//
//  KiCadModelProvider.swift
//  Volta
//
//  Phase 164 — LLM Provider Protocol
//
//  The only model interface in the app. MOD-01 lock: SDK types never leak
//  through KCToken / KCMessage. Concrete providers (FoundationModels,
//  MLX-Swift, OpenAI, Anthropic, Gemini, Groq, xAI, Together, Ollama, Mock)
//  conform to this protocol. Phase 165 (Router) dispatches by task/cost/
//  privacy. Phase 166 (BYOK) adds cloud providers behind the same protocol.
//
//  Per PROJECT.md "Track B — Models": KiCadModelProvider is THE protocol
//  wrapping FoundationModels + MLX-Swift + Swift AI SDK. SDK types are
//  contained inside each provider's file; only KCToken/KCMessage cross
//  the boundary.
//
//  Per STACK.md: protocol with associated types was considered and rejected
//  in favor of generic `Decodable` JSON output — keeps the protocol
//  non-generic so providers can be stored in a heterogeneous array.
//

import Foundation

// MARK: - KiCadModelProvider

/// The unified model interface for the KiCad Agent app.
///
/// All AI calls go through this protocol. Providers translate KCPrompt
/// into their native SDK call shape internally; only KC* value types
/// cross the boundary. This is the MOD-01 lock.
///
/// Conformers must be `Sendable` — providers are shared across actors
/// (main UI, daemon supervisor, conversation engine).
protocol KiCadModelProvider: Sendable {
    /// Stream a response for `request`. Tokens arrive as an
    /// `AsyncThrowingStream` ending with `.done` or an error.
    func stream(_ request: KCPrompt) async throws -> AsyncThrowingStream<KCToken, Error>

    /// Generate a single JSON response decoded into `T`. Use for tool calls,
    /// structured outputs, and any prompt where partial output isn't useful.
    func generateJSON<T: Decodable>(_ request: KCPrompt, as: T.Type) async throws -> T

    /// Live availability. FoundationModels checks Apple Intelligence status;
    /// MLX checks model presence + VRAM; cloud providers check key validity.
    var availability: KCProviderAvailability { get async }

    /// Human-readable name for Settings UI and banner.
    var displayName: String { get }

    /// Category — drives UI grouping and Router defaults.
    var kind: KCProviderKind { get }
}

// MARK: - Defaults

extension KiCadModelProvider {
    /// Default JSON generation uses stream + accumulate + decode. Providers
    /// with native structured-output (FoundationModels `@Generable`, OpenAI
    /// `response_format`) override this for better accuracy.
    func generateJSON<T: Decodable>(_ request: KCPrompt, as: T.Type) async throws -> T {
        var accumulated = ""
        let stream = try await self.stream(request)
        for try await token in stream {
            if case .text(let chunk) = token { accumulated += chunk }
        }
        guard let data = accumulated.data(using: .utf8) else {
            throw KCProviderError.invalidJSONOutput(raw: accumulated)
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw KCProviderError.invalidJSONOutput(raw: accumulated, underlying: error)
        }
    }
}

// MARK: - KCProviderError

/// Errors providers throw. Kept enum-not-struct so equatable + exhaustive.
enum KCProviderError: Error, LocalizedError, Sendable {
    case unavailable(reason: String)
    case rateLimited(retryAfter: TimeInterval?)
    case invalidJSONOutput(raw: String, underlying: Error? = nil)
    case contextLengthExceeded(inputTokens: Int, max: Int)
    case requestFailed(underlying: Error)
    case modelNotFound(modelId: String)
    case modelFormatInvalid(file: String, reason: String)
    case insufficientVRAM(requiredBytes: UInt64, availableBytes: UInt64)

    var errorDescription: String? {
        switch self {
        case .unavailable(let reason):
            return "Provider unavailable: \(reason)"
        case .rateLimited(let retryAfter):
            if let retryAfter = retryAfter {
                return "Rate limited. Retry in \(Int(retryAfter))s."
            }
            return "Rate limited."
        case .invalidJSONOutput(let raw, let underlying):
            let trimmed = raw.prefix(200)
            return "Model did not return valid JSON (got: '\(trimmed)')\(underlying.map { ". \($0.localizedDescription)" } ?? "")"
        case .contextLengthExceeded(let input, let max):
            return "Context length exceeded (\(input) > \(max) tokens)"
        case .requestFailed(let underlying):
            return "Request failed: \(underlying.localizedDescription)"
        case .modelNotFound(let id):
            return "Model not found: \(id)"
        case .modelFormatInvalid(let file, let reason):
            return "Model format invalid for \(file): \(reason)"
        case .insufficientVRAM(let required, let available):
            let reqMB = required / 1024 / 1024
            let availMB = available / 1024 / 1024
            return "Insufficient VRAM: model needs \(reqMB)MB, only \(availMB)MB available"
        }
    }
}
