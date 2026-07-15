//
//  ChatPipelineE2ETests.swift
//  VoltaTests
//
//  Phase 241 — Streaming Chat E2E Test
//
//  End-to-end tests for the streaming chat pipeline:
//    MockProvider → KiCadModelRouter → RouterStreamProvider → chunks
//
//  Verifies (the gap that allowed the echo bug):
//    - Echoed user prompt is stripped from the first chunk
//    - Sentence / paragraph boundaries produce separate chunks
//    - Cost callback fires with non-zero usage
//    - Conversation history is preserved across stream() calls
//    - Stream terminates cleanly with .done (not via thrown error)
//    - Loop-only response delivers the full text (renderer owns collapse)
//
//  All tests are pure unit / integration — no real network, no real model.
//  Fixtures are inline (no Bundle.module gymnastics; the SPM test target
//  has no resources: declaration).
//

import Testing
import Foundation
@testable import Volta

// MARK: - Test fixtures (inline)

private enum Fixture {
    static let userPrompt = "What is the gain of a non-inverting op-amp?"

    /// Echo regression — model repeats the user prompt verbatim before answering.
    static let echoTokens: [KCToken] = [
        .text("What is the gain of a non-inverting op-amp?\n"),
        .text("The gain of a non-inverting amplifier is given by 1 + Rf/Rin.\n"),
        .text("Pick Rf = 9k and Rin = 1k for a gain of 10."),
        .usage(KCUsage(inputTokens: 12, outputTokens: 35, estimatedCostUSD: 0)),
        .done(.complete)
    ]

    /// Clean response with a paragraph break.
    static let cleanTokens: [KCToken] = [
        .text("The closed-box demo is an automated analog verification flow. "),
        .text("It runs Optuna GPSampler, verifies the design with ngspice, then asserts specs.\n\n"),
        .text("Targets are gain, bandwidth, and BOM cost. "),
        .text("Each candidate is scored against the user-defined thresholds."),
        .usage(KCUsage(inputTokens: 8, outputTokens: 42, estimatedCostUSD: 0)),
        .done(.complete)
    ]

    /// Loop response — same sentence 5x.
    static let loopTokens: [KCToken] = [
        .text("Sure. "),
        .text("Got it. "),
        .text("Got it. "),
        .text("Got it. "),
        .text("Got it. "),
        .text("Got it. "),
        .text("Done."),
        .usage(KCUsage(inputTokens: 3, outputTokens: 16, estimatedCostUSD: 0)),
        .done(.complete)
    ]
}

// MARK: - Test helpers

/// Build a router that routes to a single injected provider. Sets every
/// preferenceCategory to .mock so any task classification lands on our
/// injected provider, bypassing AppleLocal / cloud / privacy fallbacks.
@MainActor
private func makeRouter(provider: any KiCadModelProvider) -> KiCadModelRouter {
    let prefs = KCRoutingPreferences(
        preferredProviderPerTask: [
            .quickReply: .mock,
            .complexReasoning: .mock,
            .vision: .mock,
            .privacySensitive: .mock
        ],
        privacyMode: false,
        costWarningThresholdUSD: KCCostLedger.defaultPerMessageWarningThreshold
    )
    return KiCadModelRouter(
        providers: [.appleLocal: provider, .mock: provider],
        preferences: prefs,
        loadPersistedPreferences: false
    )
}

private func makeUserMessage(_ text: String) -> ChatMessage {
    ChatMessage(role: .user, content: text, status: .complete)
}

private func makeHistory(userText: String, priorAssistant: String? = nil) -> [ChatMessage] {
    var history: [ChatMessage] = []
    if let prior = priorAssistant, !prior.isEmpty {
        history.append(ChatMessage(role: .assistant, content: prior, status: .complete))
    }
    history.append(makeUserMessage(userText))
    return history
}

/// Collect every chunk from a String stream into an array.
private func collectChunks(from stream: AsyncThrowingStream<String, Error>) async throws -> [String] {
    var chunks: [String] = []
    for try await chunk in stream {
        chunks.append(chunk)
    }
    return chunks
}

// MARK: - Tests

@Suite("Chat Pipeline E2E (Phase 241)")
@MainActor
struct ChatPipelineE2ETests {

    // MARK: - Echo stripping (the regression that started this work)

    @Test("Echo of user prompt is stripped from first chunk")
    func echoStripped() async throws {
        let mock = MockProvider(tokens: Fixture.echoTokens)
        let router = makeRouter(provider: mock)
        let provider = RouterStreamProvider(router: router)
        let history = makeHistory(userText: Fixture.userPrompt)

        let chunks = try await collectChunks(from: provider.stream(history: history, attachments: []))

        guard let first = chunks.first else {
            Issue.record("Expected at least one chunk from the echo fixture")
            return
        }
        #expect(
            !first.lowercased().hasPrefix(Fixture.userPrompt.lowercased()),
            "First chunk still starts with the user prompt: \(first.prefix(80))"
        )

        let fullText = chunks.joined()
        #expect(fullText.contains("1 + Rf/Rin"))
        #expect(fullText.contains("gain of 10"))
    }

    // MARK: - Chunking at boundaries

    @Test("Paragraph break (\\n\\n) produces a separate chunk")
    func paragraphBreakFlushes() async throws {
        let mock = MockProvider(tokens: Fixture.cleanTokens)
        let router = makeRouter(provider: mock)
        let provider = RouterStreamProvider(router: router)
        let history = makeHistory(userText: Fixture.userPrompt)

        let chunks = try await collectChunks(from: provider.stream(history: history, attachments: []))

        #expect(chunks.count >= 2, "Expected ≥2 chunks, got \(chunks.count): \(chunks)")

        let joined = chunks.joined()
        #expect(joined.contains("closed-box demo"))
        #expect(joined.contains("Optuna GPSampler"))
        #expect(joined.contains("ngspice"))
    }

    @Test("Sentence boundary (. ) flushes a chunk on its own")
    func sentenceBoundaryFlushes() async throws {
        let tokens: [KCToken] = [
            .text("First sentence. "),
            .text("Second sentence. "),
            .text("Third sentence."),
            .usage(KCUsage.free(input: 1, output: 3)),
            .done(.complete)
        ]
        let mock = MockProvider(tokens: tokens)
        let router = makeRouter(provider: mock)
        let provider = RouterStreamProvider(router: router)
        let history = makeHistory(userText: "Test.")

        let chunks = try await collectChunks(from: provider.stream(history: history, attachments: []))

        #expect(chunks.count >= 3, "Expected ≥3 chunks, got \(chunks.count): \(chunks)")

        let joined = chunks.joined()
        #expect(joined.contains("First sentence"))
        #expect(joined.contains("Second sentence"))
        #expect(joined.contains("Third sentence"))
    }

    // MARK: - Cost callback

    @Test("onUsage fires with non-zero usage after stream completes")
    func costCallbackFires() async throws {
        let mock = MockProvider(tokens: Fixture.cleanTokens)
        let router = makeRouter(provider: mock)

        let captured = CapturedUsage()
        let provider = RouterStreamProvider(
            router: router,
            onUsage: { usage in
                Task { await captured.set(usage) }
            }
        )

        let history = makeHistory(userText: Fixture.userPrompt)
        _ = try await collectChunks(from: provider.stream(history: history, attachments: []))

        // Wait briefly for the @Sendable callback to land on the actor.
        try await Task.sleep(for: .milliseconds(50))
        let usage = await captured.get()
        #expect(usage != nil, "onUsage was never called")
        #expect(usage?.outputTokens == 42, "Expected outputTokens=42, got \(usage?.outputTokens ?? -1)")
    }

    // MARK: - Clean termination

    @Test("Stream terminates with continuation.finish(), not via thrown error")
    func streamTerminatesCleanly() async throws {
        let tokens: [KCToken] = [
            .text("hello"),
            .text(" world"),
            .done(.complete)
        ]
        let mock = MockProvider(tokens: tokens)
        let router = makeRouter(provider: mock)
        let provider = RouterStreamProvider(router: router)
        let history = makeHistory(userText: "hi")

        // If .done isn't emitted, collectChunks will hang on the for-await.
        // swift-testing will time out the test, which is the failure signal.
        let chunks = try await collectChunks(from: provider.stream(history: history, attachments: []))

        #expect(chunks == ["hello world"])
    }

    // MARK: - Loop response (full delivery, not silent truncation)

    @Test("Loop response delivers all repeated content (no silent truncation)")
    func loopResponseDeliversFull() async throws {
        let mock = MockProvider(tokens: Fixture.loopTokens)
        let router = makeRouter(provider: mock)
        let provider = RouterStreamProvider(router: router)
        let history = makeHistory(userText: Fixture.userPrompt)

        let chunks = try await collectChunks(from: provider.stream(history: history, attachments: []))

        let joined = chunks.joined()
        let gotItCount = joined.components(separatedBy: "Got it.").count - 1
        #expect(gotItCount == 5, "Expected 5 'Got it.' repeats, got \(gotItCount) in: \(joined)")
        #expect(joined.contains("Done."))
    }

    // MARK: - Conversation history preservation

    @Test("Multi-turn history is forwarded to the provider (prior assistant turn included)")
    func historyIsForwarded() async throws {
        let capture = PromptCapture()
        let mock = PromptCapturingProvider(capture: capture)
        let router = makeRouter(provider: mock)
        let provider = RouterStreamProvider(router: router)

        let history: [ChatMessage] = [
            ChatMessage(role: .user, content: "What's an op-amp?", status: .complete),
            ChatMessage(role: .assistant, content: "An op-amp amplifies the difference between two inputs.", status: .complete),
            ChatMessage(role: .user, content: "And a non-inverting configuration?", status: .complete)
        ]
        _ = try await collectChunks(from: provider.stream(history: history, attachments: []))

        let lastPrompt = await capture.lastPrompt
        #expect(lastPrompt != nil, "Provider never received a KCPrompt")
        let messages = lastPrompt?.messages ?? []
        #expect(messages.count == 3, "Expected 3 messages in KCPrompt, got \(messages.count)")
        #expect(messages[0].role == .user)
        #expect(messages[0].content == "What's an op-amp?")
        #expect(messages[1].role == .assistant)
        #expect(messages[1].content.contains("amplifies"))
        #expect(messages[2].role == .user)
        #expect(messages[2].content.contains("non-inverting"))
    }

    // MARK: - Echo stripper unit checks (in addition to the E2E test above)

    @Test("stripEcho: full-chunk echo returns empty")
    func stripEchoFull() {
        let result = RouterStreamProvider.stripEcho(
            "What is the gain?",
            userPrompt: "What is the gain?"
        )
        #expect(result.isEmpty)
    }

    @Test("stripEcho: prefix echo returns the remainder")
    func stripEchoPrefix() {
        let result = RouterStreamProvider.stripEcho(
            "What is the gain?\nThe answer is 10.",
            userPrompt: "What is the gain?"
        )
        #expect(result == "The answer is 10.")
    }

    @Test("stripEcho: no echo returns the chunk unchanged")
    func stripEchoNone() {
        let original = "The answer is 10."
        let result = RouterStreamProvider.stripEcho(original, userPrompt: "Different question?")
        #expect(result == original)
    }

    @Test("stripEcho: case-insensitive match")
    func stripEchoCaseInsensitive() {
        let result = RouterStreamProvider.stripEcho(
            "WHAT IS THE GAIN?\nThe answer is 10.",
            userPrompt: "what is the gain?"
        )
        #expect(result == "The answer is 10.")
    }
}

// MARK: - Test-only support types

/// Async-safe holder for capturing the KCUsage delivered to the cost callback.
private actor CapturedUsage {
    private var usage: KCUsage?
    func set(_ u: KCUsage) { usage = u }
    func get() -> KCUsage? { usage }
}

/// Async-safe holder for capturing the KCPrompt received by a provider.
private actor PromptCapture {
    var lastPrompt: KCPrompt?
    func set(_ p: KCPrompt) { lastPrompt = p }
}

/// MockProvider variant that records the KCPrompt it received before
/// returning canned tokens.
private final class PromptCapturingProvider: KiCadModelProvider, @unchecked Sendable {
    let displayName = "PromptCapturing"
    var kind: KCProviderKind = .mock
    let mockAvailability: KCProviderAvailability = .available
    var availability: KCProviderAvailability { mockAvailability }

    private let capture: PromptCapture
    init(capture: PromptCapture) { self.capture = capture }

    func stream(_ request: KCPrompt) async throws -> AsyncThrowingStream<KCToken, Error> {
        await capture.set(request)
        return AsyncThrowingStream { continuation in
            Task {
                continuation.yield(.text("ok"))
                continuation.yield(.usage(KCUsage.free(input: 1, output: 1)))
                continuation.yield(.done(.complete))
                continuation.finish()
            }
        }
    }

    func generateJSON<T: Decodable>(_ request: KCPrompt, as: T.Type) async throws -> T {
        try await stream(request)
        let data = "{}".data(using: .utf8)!
        return try JSONDecoder().decode(T.self, from: data)
    }
}
