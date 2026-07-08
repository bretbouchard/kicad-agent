//
//  AnthropicCloudProvider.swift
//  KiCadAgent
//
//  Phase 166 — BYOK Keychain Storage
//
//  Anthropic Messages API provider. Distinct from OpenAI-compatible:
//    - Endpoint: POST https://api.anthropic.com/v1/messages
//    - Auth: x-api-key header (not Bearer)
//    - Versioning: anthropic-version header (2023-06-01)
//    - Streaming: SSE with named events (message_start, content_block_delta,
//      message_delta, message_stop)
//    - Usage: streamed via message_delta.usage + message_start.usage
//
//  Per MOD-01: no SDK types leak. Raw URLSession + JSON dict.
//  Per MOD-03: revoked key (401) surfaces as `.unavailable` with re-enter
//              prompt.
//  Per MOD-04: key pulled from KeychainManager at stream time.
//  Per MOD-05: direct HTTPS to api.anthropic.com, no proxy.
//  Per MOD-12: cost estimated from pricing table.
//
//  Per STACK.md "Swift AI SDK BYOK pattern": pure BYOK, direct connection,
//  Keychain storage.
//

import Foundation
import OSLog

/// Anthropic Cloud provider — distinct SSE event protocol.
final class AnthropicCloudProvider: KiCadModelProvider, @unchecked Sendable {
    static let apiBase = URL(string: "https://api.anthropic.com/v1")!
    static let anthropicVersion = "2023-06-01"

    /// Pricing per million tokens. Per MOD-12. Defaults to Claude 3.5 Sonnet.
    /// ponytail: the Router can override per-model once we expose multi-model.
    let pricingPerMillion: (input: Decimal, output: Decimal)
    let defaultModel: String
    let keychain: KeychainManager
    let session: URLSession

    let kind: KCProviderKind = .anthropic
    var displayName: String { "Anthropic" }

    init(
        keychain: KeychainManager = KeychainManager(),
        session: URLSession = .shared,
        defaultModel: String = "claude-3-5-sonnet-20241022",
        // Claude 3.5 Sonnet pricing: $3.00/MTok in, $15.00/MTok out.
        pricingPerMillion: (input: Decimal, output: Decimal) = (input: 3.00, output: 15.00)
    ) {
        self.keychain = keychain
        self.session = session
        self.defaultModel = defaultModel
        self.pricingPerMillion = pricingPerMillion
    }

    var availability: KCProviderAvailability {
        get async {
            guard let key = try? keychain.loadAPIKey(for: .anthropic), !key.isEmpty else {
                return .requiresKey(providerHint: "Add your Anthropic API key in Settings.")
            }
            return .available
        }
    }

    func stream(_ request: KCPrompt) async throws -> AsyncThrowingStream<KCToken, Error> {
        guard let key = try? keychain.loadAPIKey(for: .anthropic), !key.isEmpty else {
            throw KCProviderError.unavailable(reason: "No Anthropic API key configured.")
        }

        let urlRequest = try buildRequest(request, key: key)

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await session.bytes(for: urlRequest)
                    guard let http = response as? HTTPURLResponse else {
                        throw KCProviderError.requestFailed(underlying: URLError(.badServerResponse))
                    }
                    if http.statusCode == 401 || http.statusCode == 403 {
                        throw KCProviderError.unavailable(
                            reason: "Anthropic key rejected (HTTP \(http.statusCode)). Re-enter key in Settings."
                        )
                    }
                    if http.statusCode == 429 {
                        throw KCProviderError.rateLimited(retryAfter: nil)
                    }
                    guard (200..<300).contains(http.statusCode) else {
                        var body = ""
                        for try await line in bytes.lines {
                            body += line
                            if body.count > 400 { break }
                        }
                        throw KCProviderError.requestFailed(
                            underlying: NSError(
                                domain: "AnthropicCloudProvider",
                                code: http.statusCode,
                                userInfo: [NSLocalizedDescriptionKey: "HTTP \(http.statusCode): \(body.prefix(200))"]
                            )
                        )
                    }

                    // SSE event accumulator.
                    var inputTokens = 0
                    var outputTokens = 0
                    var outputChars = 0
                    var currentEvent = ""
                    var dataBuffer = ""

                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        if line.hasPrefix("event:") {
                            currentEvent = String(line.dropFirst(6)).trimmingCharacters(in: .whitespaces)
                            continue
                        }
                        if line.hasPrefix("data:") {
                            dataBuffer = String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces)
                        } else if line.isEmpty {
                            // Event boundary — process the accumulated event.
                            try Self.processEvent(
                                event: currentEvent,
                                data: dataBuffer,
                                continuation: continuation,
                                inputTokens: &inputTokens,
                                outputTokens: &outputTokens,
                                outputChars: &outputChars
                            )
                            currentEvent = ""
                            dataBuffer = ""
                        }
                    }

                    // Estimate when usage didn't arrive.
                    if inputTokens == 0 {
                        inputTokens = max(1, request.approxInputCharacters / 4)
                    }
                    if outputTokens == 0 {
                        outputTokens = max(1, outputChars / 4)
                    }
                    let cost = Self.estimateCost(
                        pricing: pricingPerMillion,
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
                    Logger.models.error("Anthropic stream failed: \(error.localizedDescription)")
                    continuation.yield(.done(.error))
                    continuation.finish(throwing: KCProviderError.requestFailed(underlying: error))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: - Request

    private func buildRequest(_ request: KCPrompt, key: String) throws -> URLRequest {
        var req = URLRequest(url: Self.apiBase.appendingPathComponent("messages"))
        req.httpMethod = "POST"
        req.setValue(key, forHTTPHeaderField: "x-api-key")
        req.setValue(Self.anthropicVersion, forHTTPHeaderField: "anthropic-version")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        req.timeoutInterval = 120

        // Anthropic takes system as a top-level field, not a synthetic message.
        var body: [String: Any] = [
            "model": resolvedModel(for: request),
            "max_tokens": request.maxTokens ?? 4096,
            "messages": request.messages.map(Self.transformMessage),
            "stream": true
        ]
        if let system = request.systemPrompt, !system.isEmpty {
            body["system"] = system
        }
        if let temp = request.temperature { body["temperature"] = temp }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        return req
    }

    private func resolvedModel(for request: KCPrompt) -> String {
        if let hint = request.preferredModel, !hint.isEmpty, hint != "default" { return hint }
        return defaultModel
    }

    // MARK: - SSE event processing

    /// Process one SSE event from Anthropic's stream. Mutates accumulators.
    private static func processEvent(
        event: String,
        data: String,
        continuation: AsyncThrowingStream<KCToken, Error>.Continuation,
        inputTokens: inout Int,
        outputTokens: inout Int,
        outputChars: inout Int
    ) throws {
        guard !data.isEmpty, let payload = data.data(using: .utf8) else { return }
        guard let json = try? JSONSerialization.jsonObject(with: payload) as? [String: Any] else { return }

        switch event {
        case "message_start":
            // usage.input_tokens arrives here.
            if let msg = json["message"] as? [String: Any],
               let usage = msg["usage"] as? [String: Any] {
                inputTokens = (usage["input_tokens"] as? Int) ?? 0
            }
        case "content_block_delta":
            // Streaming token text.
            if let delta = json["delta"] as? [String: Any],
               let text = delta["text"] as? String, !text.isEmpty {
                outputChars += text.count
                continuation.yield(.text(text))
            }
        case "message_delta":
            // Final usage arrives here (output tokens).
            if let usage = json["usage"] as? [String: Any] {
                outputTokens = (usage["output_tokens"] as? Int) ?? outputTokens
            }
        case "message_stop":
            // Stream complete — caller will emit .done after the loop ends.
            break
        case "error":
            // Anthropic emits server-side errors as SSE events.
            let errType = (json["error"] as? [String: Any])?["type"] as? String ?? "unknown"
            let errMsg = (json["error"] as? [String: Any])?["message"] as? String ?? "Anthropic stream error"
            throw KCProviderError.requestFailed(
                underlying: NSError(
                    domain: "AnthropicCloudProvider",
                    code: -1,
                    userInfo: [NSLocalizedDescriptionKey: "\(errType): \(errMsg)"]
                )
            )
        default:
            // ponytail: ignore unknown events (ping, etc.) — forward-compat.
            break
        }
    }

    // MARK: - Cost

    static func estimateCost(
        pricing: (input: Decimal, output: Decimal),
        inputTokens: Int,
        outputTokens: Int
    ) -> Decimal {
        let inputCost = Decimal(inputTokens) / 1_000_000 * pricing.input
        let outputCost = Decimal(outputTokens) / 1_000_000 * pricing.output
        return inputCost + outputCost
    }

    private static func transformMessage(_ msg: KCMessage) -> [String: Any] {
        // Anthropic role values: "user", "assistant". System goes top-level.
        // ponytail: tool messages would need different shape — Phase 168+.
        return [
            "role": msg.role == .system ? "user" : msg.role.rawValue,
            "content": msg.content
        ]
    }
}
