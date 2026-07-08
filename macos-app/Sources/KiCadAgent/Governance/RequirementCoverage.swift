//
//  RequirementCoverage.swift
//  KiCadAgent
//
//  Phase 169 — Obdurate Runtime
//
//  Requirement coverage report — checks that every op is linked to a
//  requirement and every requirement has at least one op.
//
//  GOV-11: "Requirement coverage report (every op linked to requirement,
//  every requirement has ops)."
//
//  Sourced from `IntentGate.catalog` (the Swift-side op registry mirror).
//  When Phase 170 wires the Python daemon's `tools/list` output through,
//  this report can be regenerated dynamically.
//

import Foundation

// MARK: - CoverageReport

struct CoverageReport: Equatable, Sendable {
    /// requirement_id → list of op_types
    let byRequirement: [String: [String]]
    /// Ops with no requirement mapping (orphaned — should be minimal).
    let orphanedOps: [String]
    /// Requirements declared but with zero ops (orphaned requirements).
    let orphanedRequirements: [String]
    /// Total ops in the catalog.
    let totalOps: Int
    /// Total requirements referenced.
    let totalRequirements: Int

    var isComplete: Bool {
        orphanedOps.isEmpty && orphanedRequirements.isEmpty
    }

    /// Coverage percentage — fraction of declared requirements that have
    /// at least one op.
    var requirementCoveragePct: Double {
        guard totalRequirements > 0 else { return 0 }
        let covered = byRequirement.keys.filter { !(byRequirement[$0]?.isEmpty ?? true) }.count
        return Double(covered) / Double(totalRequirements) * 100.0
    }

    /// Human-readable text report for the UI / journal.
    func render() -> String {
        var lines: [String] = []
        lines.append("Requirement Coverage Report")
        lines.append("==========================")
        lines.append("Requirements: \(byRequirement.keys.sorted().joined(separator: ", "))")
        lines.append("Total ops cataloged: \(totalOps)")
        lines.append("Coverage: \(String(format: "%.1f", requirementCoveragePct))%")
        lines.append("")
        lines.append("By Requirement:")
        for req in byRequirement.keys.sorted() {
            let ops = byRequirement[req] ?? []
            lines.append("  \(req) (\(ops.count) ops): \(ops.sorted().joined(separator: ", "))")
        }
        if !orphanedOps.isEmpty {
            lines.append("")
            lines.append("Orphaned ops (no requirement): \(orphanedOps.sorted().joined(separator: ", "))")
        }
        if !orphanedRequirements.isEmpty {
            lines.append("Orphaned requirements (no ops): \(orphanedRequirements.sorted().joined(separator: ", "))")
        }
        return lines.joined(separator: "\n")
    }
}

// MARK: - RequirementCoverage

enum RequirementCoverage {

    /// The set of declared requirements. Phase 169 ships the v6.0 GOV
    /// requirements; subsequent phases append here.
    static let declaredRequirements: Set<String> = [
        "GOV-01", "GOV-02", "GOV-03", "GOV-04", "GOV-05",
        "GOV-06", "GOV-07", "GOV-08", "GOV-09", "GOV-10", "GOV-11",
    ]

    /// Generate the coverage report from IntentGate.catalog.
    static func report() -> CoverageReport {
        var byReq: [String: [String]] = [:]
        var orphanedOps: [String] = []

        for (op, meta) in IntentGate.catalog {
            let req = meta.requirementId
            if req.isEmpty {
                orphanedOps.append(op)
                continue
            }
            byReq[req, default: []].append(op)
        }

        let referencedReqs = Set(byReq.keys)
        let declared = RequirementCoverage.declaredRequirements
        let orphanedReqs = declared.subtracting(referencedReqs).sorted()
        // Also include referenced requirements not in declared set (defensive).
        let allReqs = declared.union(referencedReqs)

        return CoverageReport(
            byRequirement: byReq,
            orphanedOps: orphanedOps,
            orphanedRequirements: orphanedReqs,
            totalOps: IntentGate.catalog.count,
            totalRequirements: allReqs.count
        )
    }
}
