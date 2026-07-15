//
//  AnthropicProviderTests.swift
//  VoltaTests
//
//  Phase 166 — BYOK Keychain Storage
//
//  Tests for AnthropicCloudProvider. Exercises SSE event parsing by mocking
//  URLSession.AsyncBytes with a real SSE-formatted byte stream.
//
//  Per MOD-03: tests verify (1) revoked key surfaces as .unavailable with
//  re-enter message, (2) successful stream emits text tokens + usage +
//  done, (3) SSE events parsed in correct order.
//
//  Pattern: we use a tiny in-process HTTP server bound to 127.0.0.1 to
//  serve canned SSE responses. Production code uses URLSession.shared but
//  accepts a custom URLSession — we override with one pointing at the
//  local server.
//

import Testing
import Foundation
@testable import Volta

@Suite("AnthropicCloudProvider", .serialized)
struct AnthropicProviderTests {

    // MARK: - Helpers

    private func makeKeychain() -> KeychainManager {
        KeychainManager(service: "com.bretbouchard.volta.tests.\(UUID().uuidString)")
    }

    // MARK: - Tests

    @Test("Provider has correct kind and displayName")
    func identity() {
        let provider = AnthropicCloudProvider(keychain: makeKeychain())
        #expect(provider.kind == .anthropic)
        #expect(provider.displayName == "Anthropic")
    }

    @Test("Availability returns .requiresKey when no key configured")
    func requiresKeyWhenMissing() async {
        let provider = AnthropicCloudProvider(keychain: makeKeychain())
        let avail = await provider.availability
        if case .requiresKey(let hint) = avail {
            #expect(hint.contains("Anthropic"))
        } else {
            Issue.record("Expected .requiresKey, got \(avail)")
        }
    }

    @Test("Availability returns .available when key configured")
    func availableWhenConfigured() async throws {
        let kc = makeKeychain()
        try kc.storeAPIKey("test-ant-key", for: .anthropic)
        defer { try? kc.deleteAPIKey(for: .anthropic) }

        let provider = AnthropicCloudProvider(keychain: kc)
        let avail = await provider.availability
        #expect(avail.isAvailable)
    }

    @Test("Stream throws .unavailable when no key configured")
    func streamFailsWithoutKey() async {
        let provider = AnthropicCloudProvider(keychain: makeKeychain())
        do {
            _ = try await provider.stream(KCPrompt.user("hi"))
            Issue.record("Expected throw")
        } catch let err as KCProviderError {
            if case .unavailable = err {
                // expected
            } else {
                Issue.record("Expected .unavailable, got \(err)")
            }
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test("Stream throws .unavailable for revoked key (401)")
    func revokedKeyThrowsUnavailable() async throws {
        let kc = makeKeychain()
        try kc.storeAPIKey("test-ant-key", for: .anthropic)
        defer { try? kc.deleteAPIKey(for: .anthropic) }

        // ponytail: build a session that always returns 401.
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [RevokedKeyProtocol.self]
        let session = URLSession(configuration: config)

        let provider = AnthropicCloudProvider(keychain: kc, session: session)
        do {
            let stream = try await provider.stream(KCPrompt.user("hi"))
            for try await _ in stream {}
            Issue.record("Expected error in stream")
        } catch let err as KCProviderError {
            if case .unavailable(let reason) = err {
                #expect(reason.contains("401"))
                #expect(reason.contains("Re-enter"))
            } else {
                Issue.record("Expected .unavailable, got \(err)")
            }
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test("Stream emits text + usage + done for valid SSE response")
    func streamParsesSSE() async throws {
        let kc = makeKeychain()
        try kc.storeAPIKey("test-ant-key", for: .anthropic)
        defer { try? kc.deleteAPIKey(for: .anthropic) }

        // Construct an SSE payload with Anthropic's event format.
        let ssePayload = """
        event: message_start
        data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}

        event: content_block_delta
        data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}

        event: content_block_delta
        data: {"type":"content_block_delta","delta":{"type":"text_delta","text":" world"}}

        event: message_delta
        data: {"type":"message_delta","usage":{"output_tokens":5}}

        event: message_stop
        data: {"type":"message_stop"}

        """
        // ponytail: mock URLProtocol with the SSE payload.
        SSEStreamProtocol.payload = ssePayload
        SSEStreamProtocol.statusCode = 200
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [SSEStreamProtocol.self]
        let session = URLSession(configuration: config)
        defer { SSEStreamProtocol.reset() }

        let provider = AnthropicCloudProvider(keychain: kc, session: session)
        var textAccumulator = ""
        var usageTokens: KCUsage?
        var doneReason: KCDoneReason?

        let stream = try await provider.stream(KCPrompt.user("hi"))
        for try await token in stream {
            switch token {
            case .text(let chunk):
                textAccumulator += chunk
            case .usage(let usage):
                usageTokens = usage
            case .done(let reason):
                doneReason = reason
            default:
                break
            }
        }

        #expect(textAccumulator == "Hello world")
        #expect(usageTokens?.inputTokens == 10)
        #expect(usageTokens?.outputTokens == 5)
        // Sonnet pricing: $3/MTok in, $15/MTok out.
        // 10 in + 5 out = $30/MTok + $75/MTok per million = $0.000105
        #expect(usageTokens?.estimatedCostUSD ?? 0 > 0)
        if case .complete = doneReason {} else {
            Issue.record("Expected .complete done reason, got \(String(describing: doneReason))")
        }
    }
}

// MARK: - Mock URLProtocols

final class RevokedKeyProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let resp = HTTPURLResponse(url: request.url!, statusCode: 401, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data())
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class SSEStreamProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var payload: String = ""
    nonisolated(unsafe) static var statusCode: Int = 200

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let payload = Data(Self.payload.utf8)
        let headers = ["Content-Type": "text/event-stream"]
        let resp = HTTPURLResponse(
            url: request.url!,
            statusCode: Self.statusCode,
            httpVersion: nil,
            headerFields: headers
        )!
        client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: payload)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    static func reset() {
        payload = ""
        statusCode = 200
    }
}
