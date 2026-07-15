//
//  DriftDetector.swift
//  Volta
//
//  Phase 169 — Obdurate Runtime
//
//  Drift detector — compares the target files of an op call against the
//  approved scope. Out-of-scope files trigger a warning (and, in strict
//  mode, an error). The detector is invoked by the governed call pipeline
//  after IntentGate.validate and before WorkflowStateMachine.transition.
//
//  GOV-07: "Drift detection (out-of-scope files trigger warning,
//  requirement_id required)."
//
//  Phase 169 ships the detector itself; the "approved scope" comes from
//  either (a) a statically configured set per requirement ID, or (b) a
//  runtime-registered plan scope. Default is permissive (no registered
//  scope = all files allowed, warn only).
//

import Foundation
import OSLog

// MARK: - DriftResult

/// Result of a drift check.
struct DriftResult: Equatable, Sendable {
    let inScope: [String]       // files inside approved scope
    let outOfScope: [String]    // files outside approved scope
    let warnings: [String]

    var isClean: Bool { outOfScope.isEmpty }

    init(inScope: [String], outOfScope: [String], warnings: [String]) {
        self.inScope = inScope
        self.outOfScope = outOfScope
        self.warnings = warnings
    }
}

// MARK: - DriftDetector

final class DriftDetector: @unchecked Sendable {

    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    /// Approved file scope per requirement_id. Empty means "all files
    /// allowed" — drift detection is permissive until a scope is set.
    /// Keyed by requirement_id (e.g. "GOV-01") to value (set of path
    /// suffixes/patterns).
    private var registeredScopes: [String: Set<String>] = [:]
    private let lock = NSLock()

    /// Strict mode: out-of-scope files raise an error instead of a warning.
    var strictMode: Bool = false

    init(strictMode: Bool = false) {
        self.strictMode = strictMode
    }

    // MARK: - Scope registration

    /// Register the approved file scope for a requirement_id. Subsequent
    /// drift checks for ops linked to this requirement will compare the
    /// op's target files against this set.
    func registerScope(for requirementId: String, files: Set<String>) {
        lock.lock(); defer { lock.unlock() }
        registeredScopes[requirementId] = files
    }

    /// Clear the scope for a requirement_id.
    func clearScope(for requirementId: String) {
        lock.lock(); defer { lock.unlock() }
        registeredScopes.removeValue(forKey: requirementId)
    }

    /// Get the registered scope for a requirement (test helper).
    func scope(for requirementId: String) -> Set<String>? {
        lock.lock(); defer { lock.unlock() }
        return registeredScopes[requirementId]
    }

    // MARK: - Check

    /// Check an op call for drift.
    ///
    /// - Parameters:
    ///   - intent: Validated intent (carries requirement_id + targetFiles).
    /// - Returns: DriftResult describing in-scope vs out-of-scope files.
    func check(_ intent: IntentResult) -> DriftResult {
        let scope = self.scope(for: intent.requirementId)

        // No registered scope → permissive (warn).
        guard let approved = scope, !approved.isEmpty else {
            let warning = intent.targetFiles.isEmpty
                ? "no scope registered for requirement=\(intent.requirementId) (permissive)"
                : "no scope registered for requirement=\(intent.requirementId); allowing files: \(intent.targetFiles)"
            return DriftResult(inScope: intent.targetFiles,
                               outOfScope: [],
                               warnings: [warning])
        }

        var inScope: [String] = []
        var outOfScope: [String] = []
        for file in intent.targetFiles {
            if DriftDetector.matches(file: file, in: approved) {
                inScope.append(file)
            } else {
                outOfScope.append(file)
            }
        }

        var warnings: [String] = []
        if !outOfScope.isEmpty {
            let msg = "drift: op=\(intent.op) requirement=\(intent.requirementId) out-of-scope files: \(outOfScope)"
            warnings.append(msg)
            if strictMode {
                Self.logger.error("\(msg, privacy: .public)")
            } else {
                Self.logger.warning("\(msg, privacy: .public)")
            }
        }

        return DriftResult(inScope: inScope, outOfScope: outOfScope, warnings: warnings)
    }

    /// Returns true if `file` matches any pattern in `approved`. Matching
    /// is suffix-based (e.g. "myboard.kicad_sch" matches "kicad_sch").
    static func matches(file: String, in approved: Set<String>) -> Bool {
        // Normalize: lowercase, strip whitespace.
        let f = file.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        for pattern in approved {
            let p = pattern.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
            if f == p { return true }
            if f.hasSuffix("." + p) { return true }
            if f.hasSuffix("/" + p) { return true }
            if f.contains(p) { return true }
        }
        return false
    }
}
