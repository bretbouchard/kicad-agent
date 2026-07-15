//
//  PerformanceTesting.swift
//  Volta
//
//  Phase 197 — Performance Testing
//
//  Helpers for measuring latency, memory, and regression detection.
//  XCTest measure{} blocks require XCTest; these helpers provide a
//  framework-agnostic measurement API for use in swift-testing.
//
//  TEST-08: performance tests with regression detection.
//

import Foundation
import Testing

/// Performance measurement helpers.
public enum PerformanceTesting {

    /// Measure the wall-clock time of a closure in milliseconds.
    @discardableResult
    public static func measure<T>(
        _ name: String,
        fileID: String = #fileID,
        line: Int = #line,
        _ body: () throws -> T
    ) rethrows -> T {
        let start = DispatchTime.now()
        defer {
            let end = DispatchTime.now()
            let ms = Double(end.uptimeNanoseconds - start.uptimeNanoseconds) / 1_000_000
            // Performance log — tests verify via PerformanceReport.
            PerformanceLog.shared.record(name: name, durationMs: ms)
        }
        return try body()
    }

    /// Assert that a closure completes within `maxMs` milliseconds.
    public static func assertCompletesWithin(
        _ maxMs: Double,
        _ name: String = "operation",
        fileID: String = #fileID,
        line: Int = #line,
        _ body: () throws -> Void
    ) rethrows {
        let start = DispatchTime.now()
        try body()
        let end = DispatchTime.now()
        let ms = Double(end.uptimeNanoseconds - start.uptimeNanoseconds) / 1_000_000
        #expect(ms <= maxMs, "\(name) took \(ms)ms, expected <= \(maxMs)ms")
    }

    /// Run a benchmark N times and return stats.
    public static func benchmark(
        iterations: Int = 100,
        warmup: Int = 5,
        _ body: () -> Void
    ) -> BenchmarkResult {
        // Warmup (not measured).
        for _ in 0..<warmup { body() }

        var durationsMs: [Double] = []
        durationsMs.reserveCapacity(iterations)
        for _ in 0..<iterations {
            let start = DispatchTime.now()
            body()
            let end = DispatchTime.now()
            durationsMs.append(Double(end.uptimeNanoseconds - start.uptimeNanoseconds) / 1_000_000)
        }
        return BenchmarkResult(durationsMs: durationsMs)
    }
}

/// One benchmark result with statistical summary.
public struct BenchmarkResult: Sendable, Equatable {
    public let durationsMs: [Double]
    public let minMs: Double
    public let maxMs: Double
    public let meanMs: Double
    public let medianMs: Double
    public let p95Ms: Double
    public let p99Ms: Double

    public init(durationsMs: [Double]) {
        self.durationsMs = durationsMs
        let sorted = durationsMs.sorted()
        self.minMs = sorted.first ?? 0
        self.maxMs = sorted.last ?? 0
        let sum = durationsMs.reduce(0, +)
        self.meanMs = durationsMs.isEmpty ? 0 : sum / Double(durationsMs.count)
        self.medianMs = sorted.isEmpty ? 0 : sorted[sorted.count / 2]
        self.p95Ms = sorted.isEmpty ? 0 : sorted[Int(Double(sorted.count) * 0.95)]
        self.p99Ms = sorted.isEmpty ? 0 : sorted[Int(Double(sorted.count) * 0.99)]
    }

    /// True if every iteration was within `thresholdMs`.
    public func allWithin(_ thresholdMs: Double) -> Bool {
        maxMs <= thresholdMs
    }
}

/// Shared performance log — tests read this to assert performance gates.
public final class PerformanceLog: @unchecked Sendable {
    public static let shared = PerformanceLog()
    private let lock = NSLock()
    private(set) var entries: [(name: String, durationMs: Double, timestamp: Date)] = []

    private init() {}

    public func record(name: String, durationMs: Double) {
        lock.lock()
        defer { lock.unlock() }
        entries.append((name, durationMs, .now))
    }

    public func reset() {
        lock.lock()
        defer { lock.unlock() }
        entries.removeAll()
    }

    public func max(forName name: String) -> Double? {
        lock.lock()
        defer { lock.unlock() }
        return entries.filter { $0.name == name }.map(\.durationMs).max()
    }
}
