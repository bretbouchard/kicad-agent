//
//  GeminiCloudProvider.swift
//  KiCadAgent
//
//  Phase 166 — BYOK Keychain Storage
//
//  Google Gemini provider. Distinct API shape:
//    - Endpoint: POST /v1beta/models/{model}:streamGenerateContent
//    - Auth: ?key=API_KEY in URL (not Authorization header)
//    - Streaming: SSE-like chunked JSON (one JSON object per chunk line)
//    - Usage: each chunk carries usageMetadata
//
//  Per MOD-01: no GoogleGenerativeAI SDK dependency. Raw URLSession.
//  Per MOD-05: direct HTTPS to generativelanguage.googleapis.com.
//  Per MOD-12: Gemini pricing (~$0.075/MTok in, $0.30/MTok out for Flash).
//

import Foundation
import OSLog

final class GeminiCloudProvider: KiCadModelProvider, @unchecked Sendable {
    static let apiBase = URL(string: "https://generativelanguage.googleapis.com/v1beta")!

    let keychain: KeychainManager
    let session: URLSession
    let defaultModel: String
    let pricingPerMillion: (input: Decimal, output: Decimal)

    let kind: KCProviderKind = .gemini
    var displayName: String { "Google Gemini" }

    init(
        keychain: KeychainManager = KeychainManager(),
        session: URLSession = .shared,
        // Gemini 2.0 Flash pricing: $0.10/MTok in, $0.40/MTok out.
        defaultModel: String = "gemini-2.0-flash",
        pricingPerMillion: (input: Decimal, output: Decimal) = (input: 0.10, output: 0.40)
    ) {
        self.keychain = keychain
        self.session = session
        self.defaultModel = defaultModel
        self.pricingPerMillion = pricingPerMillion
    }

    var availability: KCProviderAvailability {
        get async {
            guard let key = try? keychain.loadAPIKey(for: .gemini), !key.isEmpty else {
                return .requiresKey(providerHint: "Add your Google AI Studio API key in Settings.")
            }
            return .available
        }
    }

    func stream(_ request: KCPrompt) async throws -> AsyncThrowingStream<KCToken, Error> {
        guard let key = try? keychain.loadAPIKey(for: .gemini), !key.isEmpty else {
            throw KCProviderError.unavailable(reason: "No Gemini API key configured.")
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
                            reason: "Gemini key rejected (HTTP \(http.statusCode)). Re-enter key in Settings."
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
                                domain: "GeminiCloudProvider",
                                code: http.statusCode,
                                userInfo: [NSLocalizedDescriptionKey: "HTTP \(http.statusCode): \(body.prefix(200))"]
                            )
                        )
                    }

                    var inputTokens = 0
                    var outputTokens = 0
                    var outputChars = 0

                    // Gemini streamGenerateContent returns JSON-array-style:
                    //   [{ chunk1 }, { chunk2 }, ...]
                    // Each line may be a partial JSON object or a complete one.
                    // We accumulate braces to detect boundaries.
                    var braceDepth = 0
                    var buffer = ""

                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        buffer += line
                        braceDepth += line.filter { $0 == "{" }.count
                        braceDepth -= line.filter { $0 == "}" }.count
                        if braceDepth <= 0 && !buffer.isEmpty {
                            // Process the accumulated object.
                            Self.processChunk(
                                buffer,
                                continuation: continuation,
                                inputTokens: &inputTokens,
                                outputTokens: &outputTokens,
                                outputChars: &outputChars
                            )
                            buffer = ""
                            braceDepth = 0
                        }
                    }
                    if !buffer.isEmpty {
                        Self.processChunk(
                            buffer,
                            continuation: continuation,
                            inputTokens: &inputTokens,
                            outputTokens: &outputTokens,
                            outputChars: &outputChars
                        )
                    }

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
                    Logger.models.error("Gemini stream failed: \(error.localizedDescription)")
                    continuation.yield(.done(.error))
                    continuation.finish(throwing: KCProviderError.requestFailed(underlying: error))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: - Request

    private func buildRequest(_ request: KCPrompt, key: String) throws -> URLRequest {
        let modelName = resolvedModel(for: request)
        // alt=sse makes Gemini emit Server-Sent Events (data: lines). This
        // normalizes parsing across all our providers.
        var components = URLComponents(url: Self.apiBase, resolvingAgainstBaseURL: false)!
        components.path += "/models/\(modelName):streamGenerateContent"
        components.queryItems = [
            URLQueryItem(name: "key", value: key),
            URLQueryItem(name: "alt", value: "sse")
        ]
        guard let url = components.url else {
            throw KCProviderError.requestFailed(underlying: URLError(.badURL))
        }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 120

        var contents: [[String: Any]] = []
        for msg in request.messages {
            contents.append([
                "role": msg.role == .assistant ? "model" : "user",
                "parts": [["text": msg.content]]
            ])
        }
        var body: [String: Any] = ["contents": contents]
        var generationConfig: [String: Any] = [:]
        if let temp = request.temperature { generationConfig["temperature"] = temp }
        if let max = request.maxTokens { generationConfig["maxOutputTokens"] = max }
        if !generationConfig.isEmpty { body["generationConfig"] = generationConfig }
        if let system = request.systemPrompt, !system.isEmpty {
            body["systemInstruction"] = ["parts": [["text": system]]]
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        return req
    }

    private func resolvedModel(for request: KCPrompt) -> String {
        if let hint = request.preferredModel, !hint.isEmpty, hint != "default" { return hint }
        return defaultModel
    }

    // MARK: - SSE chunk processing

    private static func processChunk(
        _ raw: String,
        continuation: AsyncThrowingStream<KCToken, Error>.Continuation,
        inputTokens: inout Int,
        outputTokens: inout Int,
        outputChars: inout Int
    ) {
        // Strip SSE "data:" prefix if present.
        var payload = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if payload.hasPrefix("data:") {
            payload = String(payload.dropFirst(5)).trimmingCharacters(in: .whitespaces)
        }
        guard !payload.isEmpty, let data = payload.data(using: .utf8) else { return }
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }

        // Output text.
        if let candidates = json["candidates"] as? [[String: Any]],
           let content = candidates.first?["content"] as? [String: Any],
           let parts = content["parts"] as? [[String: Any]] {
            for part in parts {
                if let text = part["text"] as? String, !text.isEmpty {
                    outputChars += text.count
                    continuation.yield(.text(text))
                }
            }
        }
        // Usage metadata.
        if let usage = json["usageMetadata"] as? [String: Any] {
            inputTokens = (usage["promptTokenCount"] as? Int) ?? inputTokens
            outputTokens = (usage["candidatesTokenCount"] as? Int) ?? outputTokens
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
}
