//
//  ConcurrencyTesting.swift
//  Volta
//
//  Phase 198 — Concurrency Testing
//
//  Helpers for verifying ThreadSanitizer cleanliness, Sendable conformance,
//  and data-race-free Task groups.
//
//  TEST-09: concurrency tests with ThreadSanitizer.
//

import Foundation
import Testing

/// Concurrency test helpers.
public enum ConcurrencyTesting {

    /// Stress-test a closure with N concurrent invocations.
    ///
    /// Designed to surface data races when run under ThreadSanitizer.
    /// Build with `-sanitize=thread` to enable TSan. The function returns
    /// immediately; TSan findings appear as runtime diagnostics in the
    /// sanitized build's output.
    public static func stress(
        _ name: String,
        parallelism: Int = 100,
        iterations: Int = 1000,
        _ body: @Sendable @escaping (Int) -> Void
    ) {
        Task {
            await withTaskGroup(of: Void.self) { group in
                for worker in 0..<parallelism {
                    group.addTask {
                        for iter in 0..<iterations {
                            body(worker * iterations + iter)
                        }
                    }
                }
            }
        }
    }

    /// Assert that a type conforms to Sendable.
    ///
    /// The conformance check itself happens at compile time via the
    /// `T: Sendable` constraint — if the type isn't Sendable, the call
    /// site won't compile. This function exists so callers can document
    /// the intent in test output; it has no runtime assertions.
    public static func assertSendable<T: Sendable>(
        _ type: T.Type
    ) {
        // Compile-time enforcement via T: Sendable above. No runtime check.
    }

    /// Detect actor isolation violations by running a closure in a detached Task.
    public static func runInDetachedTask<T: Sendable>(
        _ body: @Sendable @escaping () async throws -> T
    ) async throws -> T {
        try await Task.detached { try await body() }.value
    }
}

/// Sendable actor-isolated counter — useful for concurrency tests that
/// need a shared mutable counter safe under TSan.
public actor ConcurrentCounter {
    private var value: Int = 0

    public init() {}

    public func increment() {
        value += 1
    }

    public func get() -> Int {
        value
    }

    public func reset() {
        value = 0
    }
}
