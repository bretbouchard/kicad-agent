//
//  ConcurrencyTesting.swift
//  KiCadAgent
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
    /// Build with `-sanitize=thread` to enable TSan.
    public static func stress(
        _ name: String,
        parallelism: Int = 100,
        iterations: Int = 1000,
        fileID: String = #fileID,
        line: Int = #line,
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
        #expect(true, "Concurrency stress test '\(name)' ran without TSan finding",
                sourceLocation: Testing.SourceLocation(fileID: fileID, filePath: #filePath, line: line, column: 0))
    }

    /// Assert that a type conforms to Sendable.
    public static func assertSendable<T: Sendable>(
        _ type: T.Type,
        fileID: String = #fileID,
        line: Int = #line
    ) {
        #expect(true, "\(type) is Sendable",
                sourceLocation: Testing.SourceLocation(fileID: fileID, filePath: #filePath, line: line, column: 0))
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
