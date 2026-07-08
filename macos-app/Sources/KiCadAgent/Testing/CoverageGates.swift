//
//  CoverageGates.swift
//  KiCadAgent
//
//  Phase 200 — CI Coverage Gates
//
//  CI coverage gate logic. Reads coverage report, applies per-layer
//  minimums, fails build if any layer is below threshold.
//
//  TEST-10: CI coverage gate enforcement.
//

import Foundation

/// CI coverage gate. Reads coverage report, applies thresholds.
public struct CoverageGateEvaluator {

    /// Coverage report entry — one per source file.
    public struct FileCoverage: Sendable, Codable, Equatable {
        public let path: String
        public let layer: String        // Models, Governance, UI, etc.
        public let lineRate: Double     // 0.0 - 1.0
        public let coveredLines: Int
        public let totalLines: Int
    }

    /// Coverage gate evaluation result.
    public struct EvaluationResult: Sendable, Codable, Equatable {
        public let overallRate: Double
        public let perLayerRates: [String: Double]
        public let failingLayers: [String]
        public let passesOverallGate: Bool
        public let passesPerLayerGate: Bool

        public var passesAllGates: Bool { passesOverallGate && passesPerLayerGate }
        public var failureMessage: String {
            guard !passesAllGates else { return "All coverage gates pass" }
            if !passesOverallGate {
                return "Overall coverage \(String(format: "%.1f%%", overallRate * 100)) < \(String(format: "%.1f%%", CoverageGate.minimumCoverage * 100))"
            }
            return "Layers below minimum: \(failingLayers.joined(separator: ", "))"
        }
    }

    public init() {}

    /// Evaluate a list of file coverages against the per-layer + overall gates.
    public func evaluate(_ coverages: [FileCoverage]) -> EvaluationResult {
        // Overall rate = sum of covered lines / sum of total lines.
        let totalCovered = coverages.reduce(0) { $0 + $1.coveredLines }
        let totalLines = coverages.reduce(0) { $0 + $1.totalLines }
        let overall = totalLines > 0 ? Double(totalCovered) / Double(totalLines) : 0

        // Per-layer rates.
        var perLayer: [String: (covered: Int, total: Int)] = [:]
        for c in coverages {
            let existing = perLayer[c.layer] ?? (0, 0)
            perLayer[c.layer] = (existing.covered + c.coveredLines, existing.total + c.totalLines)
        }
        let perLayerRates = perLayer.mapValues { $0.total > 0 ? Double($0.covered) / Double($0.total) : 0 }

        // Find failing layers.
        let failingLayers = perLayerRates.compactMap { (layer, rate) -> String? in
            let minimum = CoverageGate.perLayerMinimums[layer] ?? 0
            return rate < minimum ? "\(layer) \(String(format: "%.1f%%", rate * 100)) < \(String(format: "%.1f%%", minimum * 100))" : nil
        }

        return EvaluationResult(
            overallRate: overall,
            perLayerRates: perLayerRates,
            failingLayers: failingLayers,
            passesOverallGate: overall >= CoverageGate.minimumCoverage,
            passesPerLayerGate: failingLayers.isEmpty
        )
    }
}
