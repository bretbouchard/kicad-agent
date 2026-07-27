//
//  DigiKeyAuth.swift
//  Volta
//
//  Phase 1 / Task 2 — Digi-Key V4 Provider
//
//  OAuth2 2-legged client credentials flow for Digi-Key V4 API.
//  Token caching with expiry tracking and auto-refresh.
//
//  SEC-P1-01: Dedicated URLSessionConfiguration with cookies disabled,
//  no URL cache, and reload-ignoring cache policy — prevents token
//  request body caching. Debug logging never includes client_secret.
//

import Foundation
import OSLog

/// OAuth2 token manager for Digi-Key V4 API.
/// Caches the access token in memory and auto-refreshes on expiry.
final class DigiKeyAuth: @unchecked Sendable {
    private let credentials: DigiKeyCredentials
    private let session: URLSession

    // Token state — protected by lock
    private var cachedToken: String?
    private var tokenExpiry: Date?
    private let tokenLock = NSLock()

    /// Base URL for Digi-Key OAuth2. Sandbox: api-sandbox.digikey.com.
    private let tokenURL: URL

    init(credentials: DigiKeyCredentials, sandbox: Bool = false) {
        self.credentials = credentials
        let baseURL = sandbox ? "https://api-sandbox.digikey.com" : "https://api.digikey.com"
        self.tokenURL = URL(string: "\(baseURL)/v1/oauth2/token")!

        // SEC-P1-01: Hardened session config — no cookies, no cache.
        let config = URLSessionConfiguration.ephemeral
        config.httpShouldSetCookies = false
        config.urlCache = nil
        config.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        config.timeoutIntervalForRequest = 15
        self.session = URLSession(configuration: config)
    }

    /// Get a valid access token, refreshing if expired or missing.
    /// Thread-safe — concurrent callers share the same cached token.
    func getAccessToken() async throws -> String {
        // Fast path: check cache under lock
        let needsRefresh: Bool = tokenLock.withLock { [self] in
            guard let token = cachedToken, let expiry = tokenExpiry else {
                return true
            }
            // Refresh 60s before expiry to avoid race on use
            return Date().addingTimeInterval(60) >= expiry
        }

        if !needsRefresh {
            return tokenLock.withLock { cachedToken! }
        }

        // Slow path: request new token
        let token = try await refreshToken()
        return token
    }

    /// Force a token refresh regardless of cache state.
    private func refreshToken() async throws -> String {
        var request = URLRequest(url: tokenURL)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")

        // Body contains client_id + client_secret — never logged (SEC-P1-01).
        let body = "grant_type=client_credentials&client_id=\(credentials.clientID)&client_secret=\(credentials.clientSecret)"
        request.httpBody = body.data(using: .utf8)

        let (data, response) = try await session.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw DigiKeyError.invalidResponse
        }

        guard http.statusCode == 200 else {
            Logger.models.error("DigiKey OAuth2 token request failed: HTTP \(http.statusCode)")
            throw DigiKeyError.authFailed(statusCode: http.statusCode)
        }

        let tokenResponse = try JSONDecoder().decode(DigiKeyTokenResponse.self, from: data)

        // Cache token with expiry
        let expiry = Date().addingTimeInterval(TimeInterval(tokenResponse.expiresIn))
        tokenLock.withLock {
            cachedToken = tokenResponse.accessToken
            tokenExpiry = expiry
        }

        Logger.models.info("DigiKey OAuth2 token refreshed, expires in \(tokenResponse.expiresIn)s")
        return tokenResponse.accessToken
    }

    /// The Client ID for X-DIGIKEY-Client-Id header on API calls.
    var clientID: String { credentials.clientID }
}

/// Digi-Key OAuth2 token response (client credentials grant).
private struct DigiKeyTokenResponse: Decodable {
    let accessToken: String
    let expiresIn: Int
    let tokenType: String

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case expiresIn = "expires_in"
        case tokenType = "token_type"
    }
}

/// Digi-Key provider errors.
enum DigiKeyError: Error, LocalizedError, Sendable {
    case noCredentials
    case authFailed(statusCode: Int)
    case invalidResponse
    case rateLimited(retryAfter: TimeInterval?)
    case apiError(statusCode: Int, message: String?)

    var errorDescription: String? {
        switch self {
        case .noCredentials:
            return "Digi-Key credentials not configured. Add them in Settings."
        case .authFailed(let code):
            return "Digi-Key authentication failed (HTTP \(code))."
        case .invalidResponse:
            return "Digi-Key returned an invalid response."
        case .rateLimited(let retry):
            if let retry {
                return "Digi-Key rate limit hit. Retry in \(Int(retry))s."
            }
            return "Digi-Key rate limit hit."
        case .apiError(let code, let msg):
            return "Digi-Key API error (HTTP \(code)): \(msg ?? "unknown")"
        }
    }
}

// MARK: - NSLock convenience (Swift 6.2 safe — sync function, not called from async)

private extension NSLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}
