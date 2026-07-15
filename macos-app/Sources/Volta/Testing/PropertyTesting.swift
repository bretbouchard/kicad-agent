//
//  PropertyTesting.swift
//  Volta
//
//  Phase 193 — Property-Based Testing
//
//  Lightweight property-based testing utilities. Generates random inputs
//  for invariant verification. Uses xorshift128+ for deterministic seeds.
//
//  TEST-04: property-based tests with random input generation.
//

import Foundation
import Testing

/// Property-based testing utilities.
public enum PropertyTesting {

    /// Run a property check with N random iterations.
    ///
    /// Usage:
    /// ```
    /// PropertyTesting.check("SpecValidator rejects >1000 chars",
    ///     iterations: 100
    /// ) { rng in
    ///     let length = rng.int(in: 1001...5000)
    ///     let text = String(repeating: "a", count: length)
    ///     return SpecValidator.isWithinLength(text) == false
    /// }
    /// ```
    public static func check(
        _ property: String,
        iterations: Int = 100,
        fileID: String = #fileID,
        line: Int = #line,
        _ body: (inout PRNG) -> Bool
    ) {
        var rng = PRNG(seed: 0x1234_5678_9ABC_DEF0) // Fixed seed for reproducibility
        for iter in 0..<iterations {
            if !body(&rng) {
                Issue.record(
                    "Property '\(property)' failed at iteration \(iter)"
                )
                return
            }
        }
    }
}

/// Pseudo-random number generator (xorshift128+) — deterministic, fast, no deps.
public struct PRNG: Sendable {
    private var state: (UInt64, UInt64)

    public init(seed: UInt64) {
        // Splitmix64 to expand a single seed into two state halves.
        var s = seed
        func next() -> UInt64 {
            s &+= 0x9E3779B97F4A7C15
            var z = s
            z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
            z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
            return z ^ (z >> 31)
        }
        state = (next(), next())
    }

    /// Generate a random UInt64.
    public mutating func next() -> UInt64 {
        var s0 = state.0
        var s1 = state.1
        let result = s0 &+ s1
        s1 ^= s0
        let newS0 = (s0 << 24) | (s0 >> 40)
        s0 = newS0 ^ s1 ^ (s1 << 37)
        s1 = (s1 << 5) | (s1 >> 59)
        state = (s0, s1)
        return result
    }

    /// Random Int in the given closed range.
    public mutating func int(in range: ClosedRange<Int>) -> Int {
        let span = UInt64(range.upperBound - range.lowerBound + 1)
        if span == 0 { return range.lowerBound }
        let scaled = Int(next() % span)
        return range.lowerBound + scaled
    }

    /// Random Bool with even probability.
    public mutating func bool() -> Bool {
        next() & 1 == 1
    }

    /// Random String of given length from alphanumeric chars.
    public mutating func string(length: Int) -> String {
        let chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        let charCount = chars.count
        return String((0..<length).map { _ in
            let idx = int(in: 0...(charCount - 1))
            return chars[chars.index(chars.startIndex, offsetBy: idx)]
        })
    }

    /// Random UUID (deterministic from current state).
    public mutating func uuid() -> UUID {
        UUID(uuid: (
            UInt8(next() & 0xFF),
            UInt8((next() >> 8) & 0xFF),
            UInt8((next() >> 16) & 0xFF),
            UInt8((next() >> 24) & 0xFF),
            UInt8(next() & 0xFF),
            UInt8((next() >> 8) & 0xFF),
            UInt8((next() >> 16) & 0xFF),
            UInt8((next() >> 24) & 0xFF),
            UInt8(next() & 0xFF),
            UInt8((next() >> 8) & 0xFF),
            UInt8((next() >> 16) & 0xFF),
            UInt8((next() >> 24) & 0xFF),
            UInt8(next() & 0xFF),
            UInt8((next() >> 8) & 0xFF),
            UInt8((next() >> 16) & 0xFF),
            UInt8((next() >> 24) & 0xFF)
        ))
    }
}
