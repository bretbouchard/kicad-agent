//
//  AppleLocalProviderTests.swift
//  VoltaTests
//
//  Phase 164 — LLM Provider Protocol
//
//  Tests for AppleLocalProvider. Per Pitfall 3: tests must not assume
//  FoundationModels is available on the test host (Intel Macs, CI runners
//  without Apple Intelligence). We probe availability, then run behavior
//  tests only when available — else we assert the unavailable path.
//
//  Per STACK.md: FoundationModels requires macOS 27+ (locked decision).
//

import Testing
import Foundation
import FoundationModels
@testable import Volta

@Suite("AppleLocalProvider")
struct AppleLocalProviderTests {

    // MARK: - Construction

    @Test("Provider init with default SystemLanguageModel")
    func initDefault() {
        let provider = AppleLocalProvider()
        #expect(provider.kind == .appleLocal)
        #expect(provider.displayName == "Apple Intelligence")
    }

    // MARK: - Availability (Pitfall 3)

    @Test("Availability reflects SystemLanguageModel.default.availability")
    func availabilityMatchesSystem() async {
        let provider = AppleLocalProvider()
        let avail = await provider.availability
        let systemAvail = SystemLanguageModel.default.availability

        switch systemAvail {
        case .available:
            #expect(avail.isAvailable, "Apple reported available but provider didn't")
        case .unavailable(let reason):
            #expect(!avail.isAvailable, "Apple reported unavailable but provider said available")
            // Human-readable reason must mention what's wrong per MOD-06.
            if case .unavailable(let message) = avail {
                #expect(!message.isEmpty)
                // MOD-06 augmentation: banner must guide user to a fix.
                // Check that the message references one of: Apple Intelligence,
                // Apple Silicon, modelNotReady, System Settings.
                let lower = message.lowercased()
                let mentionsFixPath = lower.contains("apple intelligence")
                    || lower.contains("apple silicon")
                    || lower.contains("system settings")
                    || lower.contains("try again")
                #expect(mentionsFixPath, "Unavailable message must guide user to a fix. Got: \(message)")
                // Sanity: shouldn't leak the raw SDK enum name.
                _ = reason // (no assertion — we just want to consume it)
            } else {
                Issue.record("Expected unavailable case")
            }
        @unknown default:
            Issue.record("Unknown availability case from FoundationModels")
        }
    }

    @Test("Provider doesn't crash when FoundationModels unavailable")
    func unavailableDoesntCrash() async {
        let provider = AppleLocalProvider()
        // Whatever the host says, just calling availability must not throw.
        let _ = await provider.availability
    }

    // MARK: - Stream — only runs when host has Apple Intelligence

    @Test("Stream either serves tokens or throws KCProviderError.unavailable")
    func streamContract() async throws {
        let provider = AppleLocalProvider()
        let avail = await provider.availability

        if avail.isAvailable {
            // Apple Intelligence is on. Try a tiny generation.
            let prompt = KCPrompt(
                messages: [KCMessage(role: .user, content: "Say the word 'hello' and nothing else.")],
                temperature: 0.0,
                maxTokens: 16
            )
            do {
                let stream = try await provider.stream(prompt)
                var sawText = false
                var sawDone = false
                for try await token in stream {
                    if case .text = token { sawText = true }
                    if case .done = token { sawDone = true }
                }
                #expect(sawText, "Expected at least one text token")
                #expect(sawDone, "Expected done signal")
            } catch {
                // FoundationModels may still throw (rate limit, etc.).
                // That's fine — we just want to confirm the path executes.
                #expect(error is KCProviderError || error is LanguageModelSession.GenerationError)
            }
        } else {
            // Apple Intelligence unavailable on this host. Stream must throw
            // KCProviderError.unavailable before constructing a session.
            let prompt = KCPrompt.user("test")
            do {
                let stream = try await provider.stream(prompt)
                for try await _ in stream {
                    Issue.record("Should not produce tokens when unavailable")
                }
                Issue.record("Should have thrown when unavailable")
            } catch let error as KCProviderError {
                if case .unavailable = error {
                    // expected
                } else {
                    Issue.record("Wrong KCProviderError: \(error)")
                }
            } catch {
                Issue.record("Unexpected error type: \(error)")
            }
        }
    }

    // MARK: - Generation options bridging (no network)

    @Test("AppleLocalProvider exists in registry by default")
    func registryDefaultContainsApple() async {
        let registry = ProviderRegistry()
        #expect(registry.allProviders.contains { $0.kind == .appleLocal })
    }

    // MARK: - Registry integration

    @Test("ProviderRegistry.defaultProvider prefers AppleLocal when available")
    func defaultPrefersApple() async {
        let registry = ProviderRegistry()
        let def = await registry.defaultProvider()
        let avail = await registry.availableProviders()

        if avail.contains(where: { $0.kind == .appleLocal }) {
            #expect(def?.kind == .appleLocal, "Default must be Apple when available")
        } else if avail.isEmpty {
            #expect(def == nil, "Default must be nil when nothing available")
        }
        // Else: Apple unavailable + something else available — Phase 165
        // Router tests cover MLX-first defaults.
    }
}
