//
//  MutationTesting.swift
//  Volta
//
//  Phase 194 — Mutation Testing
//
//  Helpers that make tests effective at catching mutants. Mull-xcode
//  integration setup is documented; the tests themselves must be tight
//  enough that any mutation fails.
//
//  TEST-05: mutation testing with >90% mutation score.
//

import Foundation
import Testing

/// Mutation testing helpers + score reporter.
public enum MutationTesting {

    /// Run a mutation-resistance check on a single value transformation.
    ///
    /// Asserts: applying `transform` twice produces the same result as once
    /// (idempotency). Useful for catching mutations in sanitizers, validators.
    public static func assertIdempotent<T: Equatable>(
        _ name: String,
        input: T,
        transform: (T) -> T,
        fileID: String = #fileID,
        line: Int = #line
    ) {
        let once = transform(input)
        let twice = transform(once)
        #expect(once == twice, "Idempotency failed for \(name): once=\(once), twice=\(twice)")
    }

    /// Mutation score report (computed by mull-xcode externally).
    public struct MutationReport: Sendable, Codable {
        public let totalMutants: Int
        public let killed: Int
        public let survived: Int
        public let timedOut: Int
        public let mutationScore: Double

        public init(totalMutants: Int, killed: Int, survived: Int, timedOut: Int) {
            self.totalMutants = totalMutants
            self.killed = killed
            self.survived = survived
            self.timedOut = timedOut
            self.mutationScore = totalMutants > 0 ? Double(killed) / Double(totalMutants) : 0
        }

        public var passesGate: Bool { mutationScore >= 0.90 }
    }
}

/// High-coverage test pattern documentation.
///
/// These tests are designed to kill mutants. Each one targets a specific
/// code path with concrete assertions — not just "doesn't crash".
/// Mull-xcode (Phase 194 tool) mutates the SUT and reports any surviving
/// mutants, which indicates test gaps.
public enum HighCoveragePatterns {

    /// Pattern: round-trip property.
    public static func assertRoundTrip<T: Codable & Equatable>(
        _ value: T,
        fileID: String = #fileID,
        line: Int = #line
    ) throws {
        let data = try JSONEncoder().encode(value)
        let decoded = try JSONDecoder().decode(T.self, from: data)
        #expect(value == decoded, "Round-trip failed for \(T.self)")
    }

    /// Pattern: boundary condition check.
    public static func assertBoundary<T: Comparable>(
        _ value: T,
        min: T,
        max: T,
        fileID: String = #fileID,
        line: Int = #line
    ) {
        #expect(value >= min, "Boundary check failed: \(value) < \(min)")
        #expect(value <= max, "Boundary check failed: \(value) > \(max)")
    }
}
