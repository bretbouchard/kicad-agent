//
//  KiCadModelProviderProtocolTests.swift
//  VoltaTests
//
//  Phase 164 — LLM Provider Protocol
//
//  Tests for the KiCadModelProvider protocol contract. Verifies:
//    - Protocol shape (MOD-01: SDK types don't leak)
//    - Default generateJSON accumulation
//    - Stream token sequencing (text → usage → done)
//    - Error propagation
//    - Provider kind classification
//
//  Uses MockProvider as the test subject — no real network or model calls.
//

import Testing
import Foundation
@testable import Volta

@Suite("KiCadModelProvider Protocol")
struct KiCadModelProviderProtocolTests {

    // MARK: - Protocol shape (MOD-01)

    @Test("Protocol requires stream + generateJSON + availability + displayName + kind")
    func protocolShape() throws {
        // Compile-time check: MockProvider conforms to KiCadModelProvider.
        let provider: any KiCadModelProvider = MockProvider()
        #expect(provider.displayName == "Mock")
        #expect(provider.kind == .mock)
    }

    @Test("MOD-01: SDK types don't leak — public API surface is KC* types only")
    func sdkTypesDoNotLeak() throws {
        // KCToken carries only KC-named types. No OpenAI/Anthropic/FoundationModels
        // types appear as associated values.
        let tokenCases: [KCToken] = [
            .text("hi"),
            .usage(KCUsage.free(input: 1, output: 1)),
            .done(.complete),
            .toolCall(KCToolCall(id: "x", name: "noop", argumentsJSON: "{}"))
        ]
        // Each token case is one of: text(String), usage(KCUsage), done(KCDoneReason),
        // toolCall(KCToolCall). No SDK types in associated values.
        for token in tokenCases {
            switch token {
            case .text(let s): #expect(!s.isEmpty)
            case .usage(let u): #expect(u.inputTokens >= 0)
            case .done(let r): _ = r
            case .toolCall(let c): #expect(!c.name.isEmpty)
            }
        }
    }

    // MARK: - Default generateJSON

    @Test("Default generateJSON accumulates text and decodes JSON")
    func defaultGenerateJSONAccumulates() async throws {
        let json = #"{"answer":"yes","count":42}"#
        let provider = MockProvider(
            tokens: [
                .text(json),
                .usage(KCUsage.free(input: 5, output: 5)),
                .done(.complete)
            ]
        )

        struct Response: Decodable, Equatable {
            let answer: String
            let count: Int
        }

        let result = try await provider.generateJSON(.user("test"), as: Response.self)
        #expect(result.answer == "yes")
        #expect(result.count == 42)
    }

    @Test("Default generateJSON throws invalidJSONOutput for malformed JSON")
    func defaultGenerateJSONThrowsOnMalformed() async throws {
        let provider = MockProvider(
            tokens: [
                .text("not valid json at all"),
                .done(.complete)
            ]
        )

        struct Response: Decodable { let answer: String }

        await #expect(throws: KCProviderError.self) {
            _ = try await provider.generateJSON(.user("test"), as: Response.self)
        }
    }

    // MARK: - Stream sequencing

    @Test("Stream emits tokens in arrival order and finishes cleanly")
    func streamSequencing() async throws {
        let provider = MockProvider(
            tokens: [
                .text("hello "),
                .text("world"),
                .usage(KCUsage.free(input: 2, output: 2)),
                .done(.complete)
            ]
        )

        let stream = try await provider.stream(.user("hi"))
        var collector: [KCToken] = []
        for try await token in stream {
            collector.append(token)
        }

        #expect(collector.count == 4)
        // First two are text chunks.
        if case .text(let first) = collector[0] { #expect(first == "hello ") } else { Issue.record("expected text") }
        if case .text(let second) = collector[1] { #expect(second == "world") } else { Issue.record("expected text") }
        // Third is usage.
        if case .usage(let usage) = collector[2] {
            #expect(usage.outputTokens == 2)
        } else {
            Issue.record("expected usage")
        }
        // Fourth is done.
        if case .done(let reason) = collector[3] {
            #expect(reason == .complete)
        } else {
            Issue.record("expected done")
        }
    }

    @Test("Stream propagates errors from provider")
    func streamPropagatesErrors() async throws {
        struct TestError: Error {}
        let provider = MockProvider(
            tokens: [],
            forcedError: TestError()
        )

        // The forced error throws from inside stream() before returning,
        // not as a token in the stream.
        do {
            let _ = try await provider.stream(.user("hi"))
            Issue.record("Expected TestError to be thrown")
        } catch {
            #expect(error is TestError || error is KCProviderError)
        }
    }

    // MARK: - Availability

    @Test("Mock provider reports its injected availability")
    func mockAvailability() async throws {
        let p1 = MockProvider(availability: .available)
        let avail1 = p1.availability
        #expect(avail1.isAvailable)

        let p2 = MockProvider(availability: .unavailable(reason: "testing"))
        let avail2 = p2.availability
        #expect(!avail2.isAvailable)
    }

    @Test("KCProviderAvailability.isAvailable toggles correctly")
    func availabilityToggle() {
        #expect(KCProviderAvailability.available.isAvailable)
        #expect(!KCProviderAvailability.unavailable(reason: "x").isAvailable)
        #expect(!KCProviderAvailability.requiresKey(providerHint: "y").isAvailable)
    }

    // MARK: - Provider kind classification

    @Test("KCProviderKind.isLocal splits local vs cloud correctly")
    func providerKindLocal() {
        let localKinds: Set<KCProviderKind> = [.appleLocal, .mlxLocal, .ollama, .mock]
        for kind in KCProviderKind.allCases {
            #expect(kind.isLocal == localKinds.contains(kind), "kind \(kind) misclassified")
        }
    }

    @Test("All KCProviderKind cases have non-empty displayName")
    func providerKindDisplayNames() {
        for kind in KCProviderKind.allCases {
            #expect(!kind.displayName.isEmpty, "kind \(kind) missing display name")
        }
    }

    // MARK: - KCPrompt

    @Test("KCPrompt factory methods produce expected shapes")
    func promptFactories() {
        let user = KCPrompt.user("hello")
        #expect(user.messages.count == 1)
        #expect(user.messages[0].role == .user)
        #expect(user.systemPrompt == nil)

        let sysPlus = KCPrompt.systemPlusUser("you are helpful", "hi")
        #expect(sysPlus.systemPrompt == "you are helpful")
        #expect(sysPlus.messages.count == 1)
        #expect(sysPlus.messages[0].content == "hi")
    }

    @Test("KCPrompt.approxInputCharacters sums system + messages")
    func approxInput() {
        let p = KCPrompt(
            messages: [
                KCMessage(role: .user, content: "12345"),
                KCMessage(role: .assistant, content: "abc")
            ],
            systemPrompt: "system"
        )
        // "system"(6) + "12345"(5) + "abc"(3) = 14
        #expect(p.approxInputCharacters == 14)
    }

    @Test("KCPrompt accepts in-range temperature")
    func temperatureValidation() {
        // In-range values construct successfully.
        let ok1 = KCPrompt(temperature: 0.0)
        let ok2 = KCPrompt(temperature: 1.0)
        let ok3 = KCPrompt(temperature: 2.0)
        #expect(ok1.temperature == 0.0)
        #expect(ok2.temperature == 1.0)
        #expect(ok3.temperature == 2.0)
    }

    // MARK: - KCAttachment

    @Test("KCAttachment.sniffMimeType detects PNG, JPEG, GIF, WEBP")
    func mimeSniff() {
        let png: [UInt8] = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A]
        #expect(KCAttachment.sniffMimeType(data: Data(png)) == "image/png")

        let jpeg: [UInt8] = [0xFF, 0xD8, 0xFF, 0xE0]
        #expect(KCAttachment.sniffMimeType(data: Data(jpeg)) == "image/jpeg")

        let gif: [UInt8] = [0x47, 0x49, 0x46, 0x38]
        #expect(KCAttachment.sniffMimeType(data: Data(gif)) == "image/gif")

        let webp: [UInt8] = [0x52, 0x49, 0x46, 0x46, 0x00, 0x00, 0x00, 0x00, 0x57, 0x45, 0x42, 0x50]
        #expect(KCAttachment.sniffMimeType(data: Data(webp)) == "image/webp")

        let unknown: [UInt8] = [0x00, 0x01, 0x02, 0x03]
        #expect(KCAttachment.sniffMimeType(data: Data(unknown)) == nil)
    }
}
