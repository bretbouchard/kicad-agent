//
//  APIKeyValidatorTests.swift
//  KiCadAgentTests
//
//  Phase 166 — BYOK Keychain Storage
//
//  Tests for APIKeyValidator using a mock URLProtocol. We never hit a real
//  provider — all requests are intercepted at the URL loading layer.
//
//  Per MOD-03: tests verify (1) valid keys return .valid, (2) revoked keys
//  (401) return .invalid, (3) network errors return .networkError distinct
//  from invalid.
//
//  Per MOD-05: tests verify direct URL — no proxying.
//

import Testing
import Foundation
@testable import KiCadAgent

// MARK: - Mock URLProtocol

/// Captures incoming requests and serves canned responses. Singleton state
/// because URLProtocol is registered globally.
final class MockURLProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var responder: ((URLRequest) -> (HTTPURLResponse, Data))?
    nonisolated(unsafe) static var errorResponder: ((URLRequest) -> Error)?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        if let errorResponder = Self.errorResponder {
            client?.urlProtocol(self, didFailWithError: errorResponder(request))
            return
        }
        guard let responder = Self.responder else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL))
            return
        }
        let (response, data) = responder(request)
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    static func reset() {
        responder = nil
        errorResponder = nil
    }
}

@Suite("APIKeyValidator", .serialized)
struct APIKeyValidatorTests {

    /// ponytail: build a URLSession whose entire traffic routes through
    /// MockURLProtocol.
    private func makeMockSession() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        return URLSession(configuration: config)
    }

    // MARK: - Valid keys

    @Test("OpenAI valid key returns .valid")
    func openAIValid() async {
        MockURLProtocol.responder = { req in
            // Verify direct connection (MOD-05): URL must hit api.openai.com.
            #expect(req.url?.host == "api.openai.com")
            #expect(req.value(forHTTPHeaderField: "Authorization") == "Bearer sk-valid")
            let resp = HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (resp, Data("{}".utf8))
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .openAI, key: "sk-valid")
        #expect(result.isValid)
        if case .valid(let hint) = result {
            #expect(hint.contains("OpenAI"))
        }
    }

    @Test("Anthropic valid key returns .valid")
    func anthropicValid() async {
        MockURLProtocol.responder = { req in
            // Anthropic uses x-api-key header.
            #expect(req.value(forHTTPHeaderField: "x-api-key") == "sk-ant-valid")
            #expect(req.value(forHTTPHeaderField: "anthropic-version") == "2023-06-01")
            #expect(req.url?.absoluteString.contains("/v1/messages") == true)
            let resp = HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (resp, Data("{}".utf8))
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .anthropic, key: "sk-ant-valid")
        #expect(result.isValid)
    }

    @Test("Gemini valid key returns .valid")
    func geminiValid() async {
        MockURLProtocol.responder = { req in
            // Gemini uses ?key= in URL.
            #expect(req.url?.query?.contains("key=AIzaValidKey") == true)
            #expect(req.url?.host == "generativelanguage.googleapis.com")
            let resp = HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (resp, Data("{}".utf8))
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .gemini, key: "AIzaValidKey")
        #expect(result.isValid)
    }

    @Test("Groq valid key returns .valid")
    func groqValid() async {
        MockURLProtocol.responder = { req in
            #expect(req.url?.host == "api.groq.com")
            let resp = HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (resp, Data("{}".utf8))
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .groq, key: "gsk_valid")
        #expect(result.isValid)
    }

    @Test("xAI valid key returns .valid")
    func xaiValid() async {
        MockURLProtocol.responder = { req in
            #expect(req.url?.host == "api.x.ai")
            let resp = HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (resp, Data("{}".utf8))
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .xai, key: "xai-valid")
        #expect(result.isValid)
    }

    @Test("Together valid key returns .valid")
    func togetherValid() async {
        MockURLProtocol.responder = { req in
            #expect(req.url?.host == "api.together.xyz")
            let resp = HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (resp, Data("{}".utf8))
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .together, key: "tg-valid")
        #expect(result.isValid)
    }

    // MARK: - Invalid keys (revoked)

    @Test("OpenAI revoked key (401) returns .invalid")
    func openAIRevoked() async {
        MockURLProtocol.responder = { req in
            let resp = HTTPURLResponse(url: req.url!, statusCode: 401, httpVersion: nil, headerFields: nil)!
            return (resp, Data("{}".utf8))
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .openAI, key: "sk-revoked")
        if case .invalid = result {
            // expected per MOD-03
        } else {
            Issue.record("Expected .invalid for revoked key, got \(result)")
        }
    }

    @Test("Anthropic forbidden (403) returns .invalid")
    func anthropicForbidden() async {
        MockURLProtocol.responder = { req in
            let resp = HTTPURLResponse(url: req.url!, statusCode: 403, httpVersion: nil, headerFields: nil)!
            return (resp, Data("{}".utf8))
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .anthropic, key: "sk-ant-forbidden")
        if case .invalid = result {
            // expected
        } else {
            Issue.record("Expected .invalid for forbidden key")
        }
    }

    // MARK: - Network errors (distinct from invalid)

    @Test("Network failure returns .networkError not .invalid")
    func networkFailureDistinct() async {
        MockURLProtocol.errorResponder = { _ in
            URLError(.timedOut)
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .openAI, key: "sk-valid-but-offline")
        if case .networkError = result {
            // expected — distinct from .invalid per MOD-03
        } else {
            Issue.record("Expected .networkError for offline, got \(result)")
        }
    }

    @Test("Rate-limited (429) returns .networkError")
    func rateLimitedNetworkError() async {
        MockURLProtocol.responder = { req in
            let resp = HTTPURLResponse(url: req.url!, statusCode: 429, httpVersion: nil, headerFields: nil)!
            return (resp, Data("{}".utf8))
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .openAI, key: "sk-valid")
        if case .networkError = result {
            // expected
        } else {
            Issue.record("Expected .networkError for rate limit, got \(result)")
        }
    }

    // MARK: - Edge cases

    @Test("Empty key returns .invalid without network call")
    func emptyKeyShortCircuits() async {
        MockURLProtocol.responder = { _ in
            Issue.record("Should not make network call for empty key")
            let resp = HTTPURLResponse(url: URL(string: "https://example.com")!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (resp, Data())
        }
        defer { MockURLProtocol.reset() }

        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .openAI, key: "")
        if case .invalid = result {
            // expected
        } else {
            Issue.record("Expected .invalid for empty key")
        }
    }

    @Test("Local provider returns .invalid")
    func localProviderRejected() async {
        let validator = APIKeyValidator(session: makeMockSession())
        let result = await validator.validate(provider: .appleLocal, key: "anything")
        if case .invalid = result {
            // expected
        } else {
            Issue.record("Expected .invalid for local provider")
        }
    }
}
