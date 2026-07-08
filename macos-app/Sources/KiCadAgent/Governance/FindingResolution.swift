//
//  FindingResolution.swift
//  KiCadAgent
//
//  Phase 169 — Obdurate Runtime
//
//  Four-state resolution taxonomy per bureaucracy.md §7.
//
//      1. IMPLEMENTED              — Fix applied in current phase
//      2. ADDED_AS_PHASE           — Work enters current milestone TODAY
//      3. SUPERSEDED_BY_ALTERNATIVE — Need met differently (with evidence)
//      4. DEFERRED_TO_NAMED_TARGET — Named future milestone or trigger
//
//  GOV-09: "Four-state resolution taxonomy — no silent deferrals."
//
//  P0/P1 (critical/high) findings CANNOT end the phase in state 3 or 4
//  per bureaucracy.md §7.7 — `validate()` rejects those combinations.
//  State 3 requires evidence (alternative name + auto-promote trigger).
//  State 4 requires a trigger condition (named milestone or signal).
//

import Foundation
import OSLog

// MARK: - ResolutionState

enum ResolutionState: String, Codable, Sendable, CaseIterable {
    case implemented                = "IMPLEMENTED"
    case addedAsPhase               = "ADDED_AS-PHASE"
    case supersededByAlternative    = "SUPERSEDED-BY-ALTERNATIVE"
    case deferredToNamedTarget      = "DEFERRED-TO-NAMED-TARGET"

    /// Numeric state ID for stable comparison.
    var id: Int {
        switch self {
        case .implemented:               return 1
        case .addedAsPhase:              return 2
        case .supersededByAlternative:   return 3
        case .deferredToNamedTarget:     return 4
        }
    }
}

// MARK: - Finding

/// A finding from a review, audit, or out-of-scope discovery. Each finding
/// must end up in one of the four resolution states — silent dismissal
/// is forbidden.
struct Finding: Codable, Equatable, Sendable {
    let id: String                  // e.g. "P0-01", "T-169-01"
    let severity: FindingSeverity
    let title: String
    let description: String
    let detectedAt: String          // ISO 8601
    let source: String              // "council" | "drift" | "audit"

    init(id: String, severity: FindingSeverity, title: String,
                description: String, detectedAt: String, source: String) {
        self.id = id
        self.severity = severity
        self.title = title
        self.description = description
        self.detectedAt = detectedAt
        self.source = source
    }
}

// MARK: - FindingResolution record

/// A resolution record — one finding + its assigned state + evidence.
struct FindingResolution: Codable, Equatable, Sendable {
    let findingId: String
    let state: ResolutionState
    let severity: FindingSeverity
    let evidence: String?               // commit hash, test results
    let triggerCondition: String?       // for state 4
    let alternativeName: String?        // for state 3
    let phaseTarget: String?            // for state 2 (e.g. "Phase 169")
    let autoPromoteTrigger: String?     // date or condition
    let resolvedAt: String              // ISO 8601

    init(findingId: String,
                state: ResolutionState,
                severity: FindingSeverity,
                evidence: String? = nil,
                triggerCondition: String? = nil,
                alternativeName: String? = nil,
                phaseTarget: String? = nil,
                autoPromoteTrigger: String? = nil,
                resolvedAt: String) {
        self.findingId = findingId
        self.state = state
        self.severity = severity
        self.evidence = evidence
        self.triggerCondition = triggerCondition
        self.alternativeName = alternativeName
        self.phaseTarget = phaseTarget
        self.autoPromoteTrigger = autoPromoteTrigger
        self.resolvedAt = resolvedAt
    }
}

// MARK: - ValidationResult

enum ResolutionValidationError: Error, LocalizedError, Equatable {
    case p0p1CannotDefer(findingId: String, severity: FindingSeverity)
    case missingAlternativeEvidence(findingId: String)
    case missingTriggerCondition(findingId: String)
    case missingPhaseTarget(findingId: String)
    case missingImplementationEvidence(findingId: String)

    var errorDescription: String? {
        switch self {
        case .p0p1CannotDefer(let id, let sev):
            return "P0/P1 finding \(id) (\(sev.rawValue)) cannot defer — must be IMPLEMENTED or ADDED-AS-PHASE"
        case .missingAlternativeEvidence(let id):
            return "Finding \(id): SUPERSEDED-BY-ALTERNATIVE requires alternativeName + autoPromoteTrigger"
        case .missingTriggerCondition(let id):
            return "Finding \(id): DEFERRED-TO-NAMED-TARGET requires triggerCondition"
        case .missingPhaseTarget(let id):
            return "Finding \(id): ADDED-AS-PHASE requires phaseTarget"
        case .missingImplementationEvidence(let id):
            return "Finding \(id): IMPLEMENTED requires evidence (commit hash)"
        }
    }
}

// MARK: - ResolutionTracker

/// Tracks all findings and their resolutions. Enforces the four-state
/// taxonomy at write time. Provides summary queries for milestone gates.
final class FindingResolutionTracker: @unchecked Sendable {

    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    private let lock = NSLock()
    private var resolutions: [String: FindingResolution] = [:]   // findingId → resolution

    init() {}

    // MARK: - Track

    /// Record a resolution. Throws if the resolution violates the rules
    /// (e.g. P0/P1 in a deferred state, missing evidence).
    @discardableResult
    func track(_ resolution: FindingResolution) throws -> FindingResolution {
        try Self.validate(resolution)
        lock.lock(); defer { lock.unlock() }
        resolutions[resolution.findingId] = resolution
        Self.logger.info("Resolution tracked: \(resolution.findingId, privacy: .public) → \(resolution.state.rawValue, privacy: .public)")
        return resolution
    }

    /// Convenience: validate then track with builder-style API.
    func track(findingId: String,
                      state: ResolutionState,
                      severity: FindingSeverity,
                      evidence: String? = nil,
                      triggerCondition: String? = nil,
                      alternativeName: String? = nil,
                      phaseTarget: String? = nil,
                      autoPromoteTrigger: String? = nil,
                      resolvedAt: String = ISO8601DateFormatter().string(from: Date())) throws -> FindingResolution {
        let r = FindingResolution(
            findingId: findingId, state: state, severity: severity,
            evidence: evidence, triggerCondition: triggerCondition,
            alternativeName: alternativeName, phaseTarget: phaseTarget,
            autoPromoteTrigger: autoPromoteTrigger, resolvedAt: resolvedAt
        )
        return try track(r)
    }

    // MARK: - Query

    func get(_ findingId: String) -> FindingResolution? {
        lock.lock(); defer { lock.unlock() }
        return resolutions[findingId]
    }

    func all() -> [FindingResolution] {
        lock.lock(); defer { lock.unlock() }
        return Array(resolutions.values)
    }

    func byState(_ state: ResolutionState) -> [FindingResolution] {
        lock.lock(); defer { lock.unlock() }
        return resolutions.values.filter { $0.state == state }
    }

    func summary() -> [ResolutionState: Int] {
        lock.lock(); defer { lock.unlock() }
        var out: [ResolutionState: Int] = [:]
        for r in resolutions.values {
            out[r.state, default: 0] += 1
        }
        return out
    }

    // MARK: - Auto-promotion

    /// Promote DEFERRED findings whose trigger date has fired, and
    /// SUPERSEDED findings whose auto-promote trigger has fired. Returns
    /// the resolutions that were promoted (caller can journal them).
    func autoPromote(now: Date = Date(), triggerResolver: (String) -> Bool = { _ in false }) -> [FindingResolution] {
        var promoted: [FindingResolution] = []
        let nowISO = ISO8601DateFormatter().string(from: now)
        for r in all() {
            guard let trigger = r.autoPromoteTrigger else { continue }
            let shouldPromote: Bool
            if let triggerDate = ISO8601DateFormatter().date(from: trigger) {
                shouldPromote = now >= triggerDate
            } else {
                shouldPromote = triggerResolver(trigger)
            }
            if shouldPromote {
                let newState: ResolutionState = (r.state == .deferredToNamedTarget) ? .addedAsPhase : .addedAsPhase
                let promoted_ = FindingResolution(
                    findingId: r.findingId, state: newState, severity: r.severity,
                    evidence: r.evidence, triggerCondition: nil,
                    alternativeName: nil, phaseTarget: r.phaseTarget ?? "auto-promoted",
                    autoPromoteTrigger: nil, resolvedAt: nowISO
                )
                if (try? track(promoted_)) != nil {
                    promoted.append(promoted_)
                }
            }
        }
        return promoted
    }

    // MARK: - Validation

    /// Validate a resolution against the four-state rules. Throws on
    /// violation. Returns the resolution unchanged on success.
    static func validate(_ resolution: FindingResolution) throws {
        let sev = resolution.severity
        let state = resolution.state

        // P0/P1 cannot defer or supersede (unless alternative is
        // production-hardened — Phase 169 does not implement that exception,
        // treat all SUPERSEDED-BY-ALTERNATIVE as needing evidence).
        if sev == .critical || sev == .high {
            if state == .deferredToNamedTarget || state == .supersededByAlternative {
                throw ResolutionValidationError.p0p1CannotDefer(
                    findingId: resolution.findingId, severity: sev)
            }
        }

        // State-specific evidence requirements.
        switch state {
        case .implemented:
            if resolution.evidence?.isEmpty ?? true {
                throw ResolutionValidationError.missingImplementationEvidence(
                    findingId: resolution.findingId)
            }
        case .addedAsPhase:
            if resolution.phaseTarget?.isEmpty ?? true {
                throw ResolutionValidationError.missingPhaseTarget(
                    findingId: resolution.findingId)
            }
        case .supersededByAlternative:
            if resolution.alternativeName?.isEmpty ?? true ||
                resolution.autoPromoteTrigger?.isEmpty ?? true {
                throw ResolutionValidationError.missingAlternativeEvidence(
                    findingId: resolution.findingId)
            }
        case .deferredToNamedTarget:
            if resolution.triggerCondition?.isEmpty ?? true {
                throw ResolutionValidationError.missingTriggerCondition(
                    findingId: resolution.findingId)
            }
        }
    }

    /// Quick predicate: would this (severity, state) combination pass
    /// validation? Used by UI to grey out invalid choices.
    static func isValidCombination(severity: FindingSeverity,
                                          state: ResolutionState) -> Bool {
        let dummy = FindingResolution(
            findingId: "_test", state: state, severity: severity,
            evidence: "_", triggerCondition: "_",
            alternativeName: "_", phaseTarget: "_",
            autoPromoteTrigger: "_", resolvedAt: "_"
        )
        return (try? validate(dummy)) != nil
    }
}
