//
//  OllamaCloudProvider.swift
//  Volta
//
//  Phase 166 — BYOK Keychain Storage
//
//  Ollama local provider. Distinct from cloud providers because:
//    - No API key (local daemon at http://localhost:11434)
//    - Cost is always $0 (runs on user's hardware)
//    - Availability depends on daemon reachability, not key presence
//    - Endpoint: POST /api/chat (NDJSON streaming, not SSE)
//
//  Per MOD-04: Ollama is local-only — no iCloud Keychain sync needed.
//  Per MOD-05: direct call to localhost, no proxy.
//  Per MOD-12: cost always $0.
//
//  Per KCProviderKind.isLocal: ollama returns true. Router treats it as
//  local for privacy mode purposes (MOD-02).
//

import Foundation
import OSLog

final class OllamaCloudProvider: KiCadModelProvider, @unchecked Sendable {
    static let defaultBaseURL = URL(string: "http://localhost:11434")!

    let baseURL: URL
    let session: URLSession
    let defaultModel: String

    let kind: KCProviderKind = .ollama
    var displayName: String { "Ollama" }

    init(
        baseURL: URL = OllamaCloudProvider.defaultBaseURL,
        session: URLSession = .shared,
        defaultModel: String = "llama3.2"
    ) {
        self.baseURL = baseURL
        self.session = session
        self.defaultModel = defaultModel
    }

    var availability: KCProviderAvailability {
        get async {
            // Quick reachability probe — /api/tags is cheap.
            var req = URLRequest(url: baseURL.appendingPathComponent("api/tags"))
            req.httpMethod = "GET"
            req.timeoutInterval = 3
            do {
                let (_, response) = try await session.data(for: req)
                guard let http = response as? HTTPURLResponse,
                      (200..<300).contains(http.statusCode) else {
                    return .unavailable(reason: "Ollama daemon isn't responding at \(baseURL.host ?? "localhost"). Is it running?")
                }
                return .available
            } catch {
                return .unavailable(reason: "Can't reach Ollama at \(baseURL.absoluteString). Start it with `ollama serve`.")
            }
        }
    }

    func stream(_ request: KCPrompt) async throws -> AsyncThrowingStream<KCToken, Error> {
        let urlRequest = try buildRequest(request)

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await session.bytes(for: urlRequest)
                    guard let http = response as? HTTPURLResponse else {
                        throw KCProviderError.requestFailed(underlying: URLError(.badServerResponse))
                    }
                    guard (200..<300).contains(http.statusCode) else {
                        var body = ""
                        for try await line in bytes.lines {
                            body += line
                            if body.count > 400 { break }
                        }
                        throw KCProviderError.unavailable(
                            reason: "Ollama returned HTTP \(http.statusCode). Is the daemon running? \(body.prefix(200))"
                        )
                    }

                    var inputTokens = 0
                    var outputTokens = 0
                    var outputChars = 0

                    // Ollama streams NDJSON: one JSON object per line.
                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        guard !line.isEmpty,
                              let data = line.data(using: .utf8),
                              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                            continue
                        }
                        if let msg = json["message"] as? [String: Any],
                           let content = msg["content"] as? String, !content.isEmpty {
                            outputChars += content.count
                            continuation.yield(.text(content))
                        }
                        if let done = json["done"] as? Bool, done {
                            // Final usage chunk.
                            if let promptEval = json["prompt_eval_count"] as? Int {
                                inputTokens = promptEval
                            }
                            if let eval = json["eval_count"] as? Int {
                                outputTokens = eval
                            }
                        }
                    }

                    if inputTokens == 0 {
                        inputTokens = max(1, request.approxInputCharacters / 4)
                    }
                    if outputTokens == 0 {
                        outputTokens = max(1, outputChars / 4)
                    }
                    // ponytail: Ollama is local — always $0.
                    continuation.yield(.usage(KCUsage.free(
                        input: inputTokens,
                        output: outputTokens
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
                    Logger.models.error("Ollama stream failed: \(error.localizedDescription)")
                    continuation.yield(.done(.error))
                    continuation.finish(throwing: KCProviderError.unavailable(
                        reason: "Ollama unreachable: \(error.localizedDescription). Is `ollama serve` running?"
                    ))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: - Request

    private func buildRequest(_ request: KCPrompt) throws -> URLRequest {
        var req = URLRequest(url: baseURL.appendingPathComponent("api/chat"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 300  // local — long OK

        var body: [String: Any] = [
            "model": resolvedModel(for: request),
            "messages": request.messages.map(Self.transformMessage) + Self.systemMessageIfAny(request),
            "stream": true
        ]
        if let temp = request.temperature { body["options"] = ["temperature": temp] }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        return req
    }

    private func resolvedModel(for request: KCPrompt) -> String {
        if let hint = request.preferredModel, !hint.isEmpty, hint != "default" { return hint }
        return defaultModel
    }

    private static func transformMessage(_ msg: KCMessage) -> [String: Any] {
        ["role": msg.role.rawValue, "content": msg.content]
    }

    private static func systemMessageIfAny(_ request: KCPrompt) -> [[String: Any]] {
        guard let system = request.systemPrompt, !system.isEmpty else { return [] }
        return [["role": "system", "content": system]]
    }
}
