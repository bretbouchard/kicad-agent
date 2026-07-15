//
//  OpenAICompatibleCloudProvider.swift
//  Volta
//
//  Phase 166 — BYOK Keychain Storage
//
//  Shared implementation for cloud providers that speak the OpenAI Chat
//  Completions API. This is the "OpenAI-compatible" family:
//    - OpenAI itself
//    - Groq
//    - xAI (Grok)
//    - Together AI
//
//  Each provider configures: base URL, default model, API key source
//  (KeychainManager), pricing per million tokens, and an HTTP header
//  modifier if needed. The base class handles:
//    - URL + JSON request construction
//    - SSE stream parsing (data: lines + [DONE])
//    - Token usage accounting (delta + final usage chunk)
//    - Cost calculation via pricing table
//    - Availability based on key presence
//
//  Per MOD-01: SDK types never leak. Only KCToken / KCMessage cross the
//  boundary. We use raw URLSession + JSONSerialization — no OpenAI SDK.
//
//  Per MOD-05: pure BYOK. Direct connection to provider, no proxy.
//
//  Per MOD-12: cost estimated from pricing table + emitted via .usage().
//

import Foundation
import OSLog

/// Configuration for an OpenAI-compatible cloud provider. One per kind.
struct CloudProviderConfig: Sendable {
    let kind: KCProviderKind
    let baseURL: URL
    let defaultModel: String
    /// (inputPerMTok, outputPerMTok) in USD.
    let pricingPerMillion: (input: Decimal, output: Decimal)

    static let openAI = CloudProviderConfig(
        kind: .openAI,
        baseURL: URL(string: "https://api.openai.com/v1")!,
        defaultModel: "gpt-4o-mini",
        // GPT-4o-mini pricing: $0.150/MTok in, $0.600/MTok out.
        pricingPerMillion: (input: 0.150, output: 0.600)
    )

    static let groq = CloudProviderConfig(
        kind: .groq,
        baseURL: URL(string: "https://api.groq.com/openai/v1")!,
        defaultModel: "llama-3.3-70b-versatile",
        // Groq pricing: $0.59/MTok in, $0.79/MTok out (public list).
        pricingPerMillion: (input: 0.59, output: 0.79)
    )

    static let xai = CloudProviderConfig(
        kind: .xai,
        baseURL: URL(string: "https://api.x.ai/v1")!,
        defaultModel: "grok-2-latest",
        // xAI pricing: $2.00/MTok in, $10.00/MTok out.
        pricingPerMillion: (input: 2.00, output: 10.00)
    )

    static let together = CloudProviderConfig(
        kind: .together,
        baseURL: URL(string: "https://api.together.xyz/v1")!,
        defaultModel: "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        // Together pricing (Llama 70B Turbo): $0.88/MTok in, $0.88/MTok out.
        pricingPerMillion: (input: 0.88, output: 0.88)
    )
}

/// OpenAI-compatible cloud provider. Handles 4 of the 7 cloud providers
/// (OpenAI, Groq, xAI, Together) since they share the same API shape.
///
/// Concurrency: stateless aside from the immutable config + keychain.
/// Safe to share across actors — each stream creates its own URLSessionTask.
final class OpenAICompatibleCloudProvider: KiCadModelProvider, @unchecked Sendable {
    let config: CloudProviderConfig
    let keychain: KeychainManager
    let session: URLSession

    var kind: KCProviderKind { config.kind }
    var displayName: String { config.kind.displayName }

    /// Optional override model id. When nil, uses config.defaultModel.
    /// The Router can set this per-task to switch to a heavier/lighter model.
    let modelOverride: String?

    init(
        config: CloudProviderConfig,
        keychain: KeychainManager = KeychainManager(),
        session: URLSession = .shared,
        modelOverride: String? = nil
    ) {
        self.config = config
        self.keychain = keychain
        self.session = session
        self.modelOverride = modelOverride
    }

    var availability: KCProviderAvailability {
        get async {
            guard let key = try? keychain.loadAPIKey(for: config.kind), !key.isEmpty else {
                return .requiresKey(providerHint: "Add your \(config.kind.displayName) API key in Settings.")
            }
            return .available
        }
    }

    func stream(_ request: KCPrompt) async throws -> AsyncThrowingStream<KCToken, Error> {
        // Pre-flight: refuse to start a stream with no key.
        guard let key = try? keychain.loadAPIKey(for: config.kind), !key.isEmpty else {
            throw KCProviderError.unavailable(reason: "No \(config.kind.displayName) API key configured.")
        }

        let urlRequest = try buildStreamRequest(request, key: key)

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await session.bytes(for: urlRequest)
                    guard let http = response as? HTTPURLResponse else {
                        throw KCProviderError.requestFailed(underlying: URLError(.badServerResponse))
                    }
                    if http.statusCode == 401 || http.statusCode == 403 {
                        // Per MOD-03: revoked key — surface as unavailable.
                        throw KCProviderError.unavailable(
                            reason: "\(config.kind.displayName) key rejected (HTTP \(http.statusCode)). Re-enter key in Settings."
                        )
                    }
                    if http.statusCode == 429 {
                        throw KCProviderError.rateLimited(retryAfter: nil)
                    }
                    guard (200..<300).contains(http.statusCode) else {
                        // Best-effort body read for the error message.
                        var body = ""
                        for try await line in bytes.lines {
                            body += line
                            if body.count > 400 { break }
                        }
                        throw KCProviderError.requestFailed(
                            underlying: NSError(
                                domain: "CloudProvider",
                                code: http.statusCode,
                                userInfo: [NSLocalizedDescriptionKey: "HTTP \(http.statusCode): \(body.prefix(200))"]
                            )
                        )
                    }

                    var inputTokens = 0
                    var outputTokens = 0
                    var outputChars = 0

                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        guard line.hasPrefix("data:") else { continue }
                        let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        if payload == "[DONE]" { break }
                        guard let data = payload.data(using: .utf8),
                              let chunk = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                            continue
                        }
                        // Stream delta content.
                        if let choices = chunk["choices"] as? [[String: Any]],
           let delta = choices.first?["delta"] as? [String: Any],
           let content = delta["content"] as? String, !content.isEmpty {
                            outputChars += content.count
                            continuation.yield(.text(content))
                        }
                        // Final usage chunk (when stream_options.include_usage is set).
                        if let usage = chunk["usage"] as? [String: Any] {
                            inputTokens = (usage["prompt_tokens"] as? Int) ?? 0
                            outputTokens = (usage["completion_tokens"] as? Int) ?? 0
                        }
                    }

                    // If usage didn't come in the stream, estimate.
                    if inputTokens == 0 {
                        inputTokens = max(1, request.approxInputCharacters / 4)
                    }
                    if outputTokens == 0 {
                        outputTokens = max(1, outputChars / 4)
                    }
                    let cost = Self.estimateCost(
                        config: config,
                        inputTokens: inputTokens,
                        outputTokens: outputTokens
                    )
                    continuation.yield(.usage(KCUsage(
                        inputTokens: inputTokens,
                        outputTokens: outputTokens,
                        estimatedCostUSD: cost
                    )))
                    continuation.yield(.done(.complete))
                    continuation.finish()
                } catch let error as KCProviderError {
                    continuation.yield(.done(.error))
                    continuation.finish(throwing: error)
                } catch is CancellationError {
                    continuation.yield(.done(.cancelled))
                    continuation.finish()
                } catch {
                    Logger.models.error("\(self.config.kind.rawValue) stream failed: \(error.localizedDescription)")
                    continuation.yield(.done(.error))
                    continuation.finish(throwing: KCProviderError.requestFailed(underlying: error))
                }
            }
            // Cancellation: cancel the underlying URLSession bytes task.
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: - Request building

    private func buildStreamRequest(_ request: KCPrompt, key: String) throws -> URLRequest {
        var req = URLRequest(url: config.baseURL.appendingPathComponent("chat/completions"))
        req.httpMethod = "POST"
        req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        req.timeoutInterval = 120

        var body: [String: Any] = [
            "model": resolvedModel(for: request),
            "messages": request.messages.map(Self.transformMessage),
            "stream": true,
            // Ask the server to include usage in the final chunk — needed
            // for accurate cost tracking per MOD-12. Not all OpenAI-compatible
            // providers honor this but it's harmless if ignored.
            "stream_options": ["include_usage": true]
        ]
        if let temp = request.temperature { body["temperature"] = temp }
        if let max = request.maxTokens { body["max_tokens"] = max }
        if let system = request.systemPrompt, !system.isEmpty {
            // Prepend system prompt as a synthetic system message.
            var msgs = body["messages"] as? [[String: Any]] ?? []
            msgs.insert(["role": "system", "content": system], at: 0)
            body["messages"] = msgs
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        return req
    }

    private func resolvedModel(for request: KCPrompt) -> String {
        // ponytail: explicit override > request hint > config default.
        if let override = modelOverride { return override }
        if let hint = request.preferredModel, !hint.isEmpty, hint != "default" { return hint }
        return config.defaultModel
    }

    // MARK: - Cost

    static func estimateCost(
        config: CloudProviderConfig,
        inputTokens: Int,
        outputTokens: Int
    ) -> Decimal {
        let inputCost = Decimal(inputTokens) / 1_000_000 * config.pricingPerMillion.input
        let outputCost = Decimal(outputTokens) / 1_000_000 * config.pricingPerMillion.output
        return inputCost + outputCost
    }

    // MARK: - Message bridging

    /// Translate KCMessage → OpenAI message dict. Per MOD-01: SDK types
    /// don't leak; we hand-roll the JSON shape.
    private static func transformMessage(_ msg: KCMessage) -> [String: Any] {
        // ponytail: attachments / images land in Phase 168+ (vision). For
        // Phase 166 we serialize text only.
        return [
            "role": msg.role.rawValue,
            "content": msg.content
        ]
    }
}

// MARK: - Provider factory

/// Convenience factory functions for the 4 OpenAI-compatible providers.
/// ProviderRegistry uses these when seeding from Keychain.
extension OpenAICompatibleCloudProvider {
    static func openAI(keychain: KeychainManager = KeychainManager()) -> OpenAICompatibleCloudProvider {
        OpenAICompatibleCloudProvider(config: .openAI, keychain: keychain)
    }
    static func groq(keychain: KeychainManager = KeychainManager()) -> OpenAICompatibleCloudProvider {
        OpenAICompatibleCloudProvider(config: .groq, keychain: keychain)
    }
    static func xai(keychain: KeychainManager = KeychainManager()) -> OpenAICompatibleCloudProvider {
        OpenAICompatibleCloudProvider(config: .xai, keychain: keychain)
    }
    static func together(keychain: KeychainManager = KeychainManager()) -> OpenAICompatibleCloudProvider {
        OpenAICompatibleCloudProvider(config: .together, keychain: keychain)
    }
}
