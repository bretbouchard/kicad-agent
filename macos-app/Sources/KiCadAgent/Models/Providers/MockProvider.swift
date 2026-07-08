//
//  MockProvider.swift
//  KiCadAgent
//
//  Phase 164 — LLM Provider Protocol
//
//  In-process mock provider for tests + SwiftUI previews. Real implementation
//  — not a stub. Configurable to emit any sequence of tokens, including
//  errors, so tests can exercise every KCProviderError path.
//
//  Per project convention: `.mock` is in KCProviderKind enum and explicitly
//  marked "Tests + previews. Never used in production paths."
//

import Foundation
import OSLog

/// Mock provider. Configurable stream output, forced availability, and
/// optional injected error. Thread-safe via dedicated actor for the counter.
final class MockProvider: KiCadModelProvider, @unchecked Sendable {
    let kind: KCProviderKind = .mock
    let displayName: String
    let mockAvailability: KCProviderAvailability

    /// Tokens to emit on each `stream(_:)` call. Cycled if request count
    /// exceeds tokens count.
    private let tokens: [KCToken]

    /// Optional forced error. Set to non-nil to throw before emitting tokens.
    private let forcedError: Error?

    /// Counter actor — async-safe call tracking.
    private let counter = Counter()

    init(
        displayName: String = "Mock",
        availability: KCProviderAvailability = .available,
        tokens: [KCToken] = [.text("hello"), .usage(KCUsage.free(input: 1, output: 1)), .done(.complete)],
        forcedError: Error? = nil
    ) {
        self.displayName = displayName
        self.mockAvailability = availability
        self.tokens = tokens
        self.forcedError = forcedError
    }

    var availability: KCProviderAvailability {
        mockAvailability
    }

    /// Test introspection — how many stream() calls so far.
    func callCount() async -> Int {
        await counter.get()
    }

    func stream(_ request: KCPrompt) async throws -> AsyncThrowingStream<KCToken, Error> {
        let n = await counter.increment()

        if let forcedError = forcedError {
            throw forcedError
        }

        let snapshot = tokens
        return AsyncThrowingStream { continuation in
            Task {
                for token in snapshot {
                    continuation.yield(token)
                }
                continuation.finish()
                Logger.models.debug("MockProvider stream #\(n) served \(snapshot.count) tokens")
            }
        }
    }
}

/// ponytail: dedicated counter actor. Avoids NSLock-from-async warnings
/// and gives clean async-safe semantics.
private actor Counter {
    private var value = 0
    func get() -> Int { value }
    func increment() -> Int {
        value += 1
        return value
    }
}
