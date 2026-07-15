//
//  QualitySecondHalfTests.swift
//  VoltaTests
//
//  Phase 196 + 197 + 198 + 200 — UI automation, performance, concurrency,
//  CI coverage gates.
//

import Testing
import Foundation
@testable import Volta

@Suite("Quality Track H second half (196-201)", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil))
struct QualitySecondHalfTests {

    // MARK: - Phase 196 — UI Automation

    @Test("GoldenFlows lists 3 canonical flows", .tags(.ui))
    func goldenFlowsList() {
        #expect(GoldenFlows.firstDesignFlow.name == "first-design")
        #expect(GoldenFlows.openExistingFlow.name == "open-existing")
        #expect(GoldenFlows.timeTravelFlow.name == "time-travel")
    }

    @Test("UIAutomationFlow has step count", .tags(.ui))
    func flowStepCount() {
        #expect(GoldenFlows.firstDesignFlow.stepCount == 4)
        #expect(GoldenFlows.openExistingFlow.stepCount == 3)
        #expect(GoldenFlows.timeTravelFlow.stepCount == 4)
    }

    @Test("UIAutomationFlow checks identifiers", .tags(.ui, .a11y))
    func flowIdentifiers() {
        #expect(GoldenFlows.firstDesignFlow.allStepsIdentifiable == true)
        #expect(GoldenFlows.openExistingFlow.allStepsIdentifiable == true)
        #expect(GoldenFlows.timeTravelFlow.allStepsIdentifiable == true)
    }

    @Test("UIAutomationStep encodes + decodes round-trip")
    func stepRoundTrip() throws {
        let step = UIAutomationStep(action: "tap", target: "Send", accessibilityIdentifier: "compose.send")
        let data = try JSONEncoder().encode(step)
        let decoded = try JSONDecoder().decode(UIAutomationStep.self, from: data)
        #expect(decoded.action == "tap")
        #expect(decoded.accessibilityIdentifier == "compose.send")
    }

    // MARK: - Phase 197 — Performance Testing

    @Test("PerformanceTesting.measure returns value and records log")
    func performanceMeasure() throws {
        PerformanceLog.shared.reset()
        let result = PerformanceTesting.measure("test-op") { 42 }
        #expect(result == 42)
        let max = PerformanceLog.shared.max(forName: "test-op")
        #expect(max != nil)
        #expect((max ?? 0) >= 0)
    }

    @Test("PerformanceTesting.assertCompletesWithin passes for fast closure")
    func performanceWithinPass() {
        PerformanceTesting.assertCompletesWithin(1000) {
            _ = (1...100).reduce(0, +)
        }
    }

    @Test("PerformanceTesting.benchmark returns stats")
    func performanceBenchmark() {
        let result = PerformanceTesting.benchmark(iterations: 50, warmup: 5) {
            _ = (1...100).reduce(0, +)
        }
        #expect(result.durationsMs.count == 50)
        #expect(result.minMs <= result.maxMs)
        #expect(result.meanMs >= 0)
        #expect(result.allWithin(10.0) == true) // Should be very fast
    }

    @Test("BenchmarkResult computes percentiles")
    func benchmarkPercentiles() {
        let result = BenchmarkResult(durationsMs: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        #expect(result.minMs == 1)
        #expect(result.maxMs == 10)
        #expect(result.meanMs == 5.5)
        #expect(result.medianMs == 6) // sorted[5]
    }

    // MARK: - Phase 198 — Concurrency Testing

    @Test("ConcurrentCounter is safe under stress", .tags(.mutation))
    func concurrentCounterStress() async {
        let counter = ConcurrentCounter()
        await withTaskGroup(of: Void.self) { group in
            for _ in 0..<10 {
                group.addTask {
                    for _ in 0..<100 {
                        await counter.increment()
                    }
                }
            }
        }
        let final = await counter.get()
        #expect(final == 1000)
    }

    @Test("ConcurrentCounter reset works")
    func concurrentCounterReset() async {
        let counter = ConcurrentCounter()
        await counter.increment()
        await counter.increment()
        await counter.reset()
        let value = await counter.get()
        #expect(value == 0)
    }

    @Test("ConcurrencyTesting.assertSendable passes for Sendable type")
    func concurrencySendable() {
        ConcurrencyTesting.assertSendable(PipelineStep.self)
        ConcurrencyTesting.assertSendable(StepStatus.self)
        ConcurrencyTesting.assertSendable(PipelineProgressEvent.self)
    }

    // MARK: - Phase 200 — Coverage Gates

    @Test("CoverageGateEvaluator passes for all-covered inputs")
    func coverageGatePass() {
        let evaluator = CoverageGateEvaluator()
        let coverages = [
            CoverageGateEvaluator.FileCoverage(path: "Models/Project.swift", layer: "Models", lineRate: 1.0, coveredLines: 50, totalLines: 50),
            CoverageGateEvaluator.FileCoverage(path: "Governance/IntentGate.swift", layer: "Governance", lineRate: 1.0, coveredLines: 80, totalLines: 80),
            CoverageGateEvaluator.FileCoverage(path: "UI/Shell.swift", layer: "UI", lineRate: 1.0, coveredLines: 40, totalLines: 40)
        ]
        let result = evaluator.evaluate(coverages)
        #expect(result.passesAllGates == true)
        #expect(result.failingLayers.isEmpty == true)
    }

    @Test("CoverageGateEvaluator fails when layer below minimum")
    func coverageGateFailLayer() {
        let evaluator = CoverageGateEvaluator()
        let coverages = [
            CoverageGateEvaluator.FileCoverage(path: "UI/Shell.swift", layer: "UI", lineRate: 0.50, coveredLines: 20, totalLines: 40)
        ]
        let result = evaluator.evaluate(coverages)
        #expect(result.passesPerLayerGate == false)
        #expect(result.failingLayers.isEmpty == false)
    }

    @Test("CoverageGateEvaluator reports overall rate below 0.80")
    func coverageGateOverallFail() {
        let evaluator = CoverageGateEvaluator()
        let coverages = [
            CoverageGateEvaluator.FileCoverage(path: "Models/X.swift", layer: "Models", lineRate: 0.50, coveredLines: 25, totalLines: 50),
            CoverageGateEvaluator.FileCoverage(path: "Models/Y.swift", layer: "Models", lineRate: 0.50, coveredLines: 25, totalLines: 50)
        ]
        let result = evaluator.evaluate(coverages)
        #expect(result.overallRate == 0.50)
        #expect(result.passesOverallGate == false)
    }

    @Test("CoverageGateEvaluator failureMessage is descriptive")
    func coverageGateMessage() {
        let result = CoverageGateEvaluator().evaluate([
            CoverageGateEvaluator.FileCoverage(path: "X", layer: "UI", lineRate: 0.10, coveredLines: 1, totalLines: 10)
        ])
        #expect(result.failureMessage.contains("UI"))
    }
}
