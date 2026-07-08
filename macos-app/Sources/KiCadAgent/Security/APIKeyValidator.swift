//
//  APIKeyValidator.swift
//  KiCadAgent
//
//  Phase 166 — BYOK Keychain Storage
//
//  Per MOD-03 stupid-proof augmentation: "Invalid API keys detected via
//  test call on save; revoked keys (401) trigger re-entry prompt."
//
//  Validates an API key by making a tiny real call to the provider's API
//  BEFORE storing it. Returns a `ValidationResult` the Settings UI uses
//  to either store the key (.valid) or surface a re-entry prompt (.invalid).
//
//  Per MOD-05: all validation calls go DIRECT from the app to the provider
//  via URLSession. No proxy through developer infrastructure.
//
//  Per T-166-01 mitigation: keys are never logged. Network errors are
//  surfaced separately from invalid-key errors so the user can distinguish
//  "wrong key" from "internet down".
//

import Foundation
import OSLog

/// Result of validating an API key. Surfaced in the Settings UI per MOD-03.
enum APIKeyValidationResult: Sendable, Equatable {
    /// Key works — safe to store. Includes the model id we used for the
    /// test call (so the UI can show "Validated against claude-3-5-sonnet").
    case valid(providerHint: String)
    /// Key rejected (401/403). Per MOD-03: triggers re-entry prompt.
    case invalid(reason: String)
    /// Network failure, timeout, or 5xx. Distinct from invalid — user
    /// shouldn't be told key is wrong when their internet is just down.
    case networkError(reason: String)

    /// True when the key is safe to store.
    var isValid: Bool {
        if case .valid = self { return true }
        return false
    }

    /// User-facing message for Settings UI.
    var userMessage: String {
        switch self {
        case .valid(let hint):
            return "Valid key — confirmed with \(hint)."
        case .invalid(let reason):
            return "Invalid key: \(reason)"
        case .networkError(let reason):
            return "Network error (key not yet saved): \(reason)"
        }
    }
}

/// Validates API keys via real provider test calls. MOD-03 enforcement.
///
/// Stateless + Sendable — one shared instance per app. The Settings UI
/// calls `validate(provider:key:)` when the user clicks "Test" or before
/// saving a freshly entered key. Per MOD-03: revoked keys (401) return
/// `.invalid` so the UI can trigger a re-entry prompt.
struct APIKeyValidator: Sendable {
    /// URLSession for all calls. Caller-injectable so tests use a mock
    /// URLProtocol (see APIKeyValidatorTests). Production uses .shared.
    let session: URLSession

    /// Per-provider endpoint + minimal test-call shape. Each cloud provider
    /// exposes a different "list models" or "minimal chat" endpoint — we
    /// pick the cheapest one (free / 1-token / models list).
    private let strategies: [KCProviderKind: ValidationStrategy]

    init(
        session: URLSession = .shared,
        strategies: [KCProviderKind: ValidationStrategy]? = nil
    ) {
        self.session = session
        self.strategies = strategies ?? Self.defaultStrategies
    }

    // MARK: - Public

    /// Validate a key by making a real call to the provider. Async so the
    /// Settings UI can `await` from a Task.
    func validate(
        provider: KCProviderKind,
        key: String
    ) async -> APIKeyValidationResult {
        guard !key.isEmpty else {
            return .invalid(reason: "Key is empty.")
        }
        // Local providers don't have keys to validate.
        if provider.isLocal {
            return .invalid(reason: "\(provider.displayName) does not use an API key.")
        }
        guard let strategy = strategies[provider] else {
            return .invalid(reason: "No validation strategy for \(provider.displayName).")
        }

        do {
            let request = try strategy.buildRequest(key)
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return .networkError(reason: "Non-HTTP response from \(provider.displayName).")
            }
            return strategy.classify(http.statusCode, data)
        } catch let error as URLError where error.code == .cancelled {
            return .networkError(reason: "Validation cancelled.")
        } catch let error as URLError {
            return .networkError(reason: error.localizedDescription)
        } catch {
            return .networkError(reason: error.localizedDescription)
        }
    }

    // MARK: - Strategies

    /// One per cloud provider. ponytail: struct not protocol — strategies
    /// are tiny and share most of their logic. Closures capture the bits
    /// that differ (URL, method, body, status classification).
    struct ValidationStrategy: Sendable {
        let buildRequest: @Sendable (String) throws -> URLRequest
        let classify: @Sendable (Int, Data) -> APIKeyValidationResult
    }

    /// The default strategies for each cloud provider. Picks the cheapest
    /// endpoint per provider (typically "list models" — free, no generation).
    static let defaultStrategies: [KCProviderKind: ValidationStrategy] = [
        .openAI: .openAI,
        .anthropic: .anthropic,
        .gemini: .gemini,
        .groq: .groq,
        .xai: .xai,
        .together: .together,
        .ollama: .ollama
    ]
}

// MARK: - Per-provider strategies

extension APIKeyValidator.ValidationStrategy {
    /// OpenAI: GET /v1/models — free, returns model list, 401 on bad key.
    static let openAI = APIKeyValidator.ValidationStrategy(
        buildRequest: { key in
            var req = URLRequest(url: URL(string: "https://api.openai.com/v1/models")!)
            req.httpMethod = "GET"
            req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
            req.setValue("application/json", forHTTPHeaderField: "Accept")
            req.timeoutInterval = 15
            return req
        },
        classify: { status, _ in
            switch status {
            case 200..<300: return .valid(providerHint: "OpenAI /v1/models")
            case 401, 403: return .invalid(reason: "Key rejected (HTTP \(status)).")
            case 429: return .networkError(reason: "Rate limited — try again.")
            default: return .networkError(reason: "HTTP \(status).")
            }
        }
    )

    /// Anthropic: POST /v1/messages with a 1-token prompt — cheapest chat call.
    /// Anthropic has no free "list models" endpoint that accepts an API key
    /// directly; the messages endpoint with max_tokens=1 is the minimal
    /// cost test (sub-cent).
    static let anthropic = APIKeyValidator.ValidationStrategy(
        buildRequest: { key in
            var req = URLRequest(url: URL(string: "https://api.anthropic.com/v1/messages")!)
            req.httpMethod = "POST"
            req.setValue(key, forHTTPHeaderField: "x-api-key")
            req.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            // Minimal: 1 token max, smallest model.
            let body: [String: Any] = [
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 1,
                "messages": [["role": "user", "content": "hi"]]
            ]
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
            req.timeoutInterval = 20
            return req
        },
        classify: { status, _ in
            switch status {
            case 200..<300: return .valid(providerHint: "Anthropic /v1/messages")
            case 401: return .invalid(reason: "Key rejected — usually revoked or never valid.")
            case 403: return .invalid(reason: "Key lacks permission for /v1/messages.")
            case 429: return .networkError(reason: "Rate limited — try again.")
            case 400, 404: return .invalid(reason: "Key accepted but request shape rejected (HTTP \(status)). Likely needs rotation.")
            default: return .networkError(reason: "HTTP \(status).")
            }
        }
    )

    /// Gemini: GET /v1beta/models?key=KEY — free list endpoint.
    static let gemini = APIKeyValidator.ValidationStrategy(
        buildRequest: { key in
            var req = URLRequest(url: URL(string: "https://generativelanguage.googleapis.com/v1beta/models?key=\(key)")!)
            req.httpMethod = "GET"
            req.timeoutInterval = 15
            return req
        },
        classify: { status, _ in
            switch status {
            case 200..<300: return .valid(providerHint: "Gemini /v1beta/models")
            case 400, 401, 403: return .invalid(reason: "Key rejected (HTTP \(status)).")
            case 429: return .networkError(reason: "Rate limited — try again.")
            default: return .networkError(reason: "HTTP \(status).")
            }
        }
    )

    /// Groq: OpenAI-compatible. GET /openai/v1/models.
    static let groq = APIKeyValidator.ValidationStrategy(
        buildRequest: { key in
            var req = URLRequest(url: URL(string: "https://api.groq.com/openai/v1/models")!)
            req.httpMethod = "GET"
            req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
            req.timeoutInterval = 15
            return req
        },
        classify: { status, _ in
            switch status {
            case 200..<300: return .valid(providerHint: "Groq /openai/v1/models")
            case 401, 403: return .invalid(reason: "Key rejected (HTTP \(status)).")
            case 429: return .networkError(reason: "Rate limited — try again.")
            default: return .networkError(reason: "HTTP \(status).")
            }
        }
    )

    /// xAI Grok: OpenAI-compatible. GET /v1/models.
    static let xai = APIKeyValidator.ValidationStrategy(
        buildRequest: { key in
            var req = URLRequest(url: URL(string: "https://api.x.ai/v1/models")!)
            req.httpMethod = "GET"
            req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
            req.timeoutInterval = 15
            return req
        },
        classify: { status, _ in
            switch status {
            case 200..<300: return .valid(providerHint: "xAI /v1/models")
            case 401, 403: return .invalid(reason: "Key rejected (HTTP \(status)).")
            case 429: return .networkError(reason: "Rate limited — try again.")
            default: return .networkError(reason: "HTTP \(status).")
            }
        }
    )

    /// Together AI: GET /v1/models — OpenAI-compatible list.
    static let together = APIKeyValidator.ValidationStrategy(
        buildRequest: { key in
            var req = URLRequest(url: URL(string: "https://api.together.xyz/v1/models")!)
            req.httpMethod = "GET"
            req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
            req.timeoutInterval = 15
            return req
        },
        classify: { status, _ in
            switch status {
            case 200..<300: return .valid(providerHint: "Together /v1/models")
            case 401, 403: return .invalid(reason: "Key rejected (HTTP \(status)).")
            case 429: return .networkError(reason: "Rate limited — try again.")
            default: return .networkError(reason: "HTTP \(status).")
            }
        }
    )

    /// Ollama: GET /api/tags — works without a key (local). Returns valid
    /// if the server is reachable; the "key" is ignored.
    static let ollama = APIKeyValidator.ValidationStrategy(
        buildRequest: { _ in
            var req = URLRequest(url: URL(string: "http://localhost:11434/api/tags")!)
            req.httpMethod = "GET"
            req.timeoutInterval = 5  // local — short timeout
            return req
        },
        classify: { status, _ in
            switch status {
            case 200..<300: return .valid(providerHint: "Ollama /api/tags (local)")
            default: return .networkError(reason: "Ollama returned HTTP \(status). Is the daemon running?")
            }
        }
    )
}
