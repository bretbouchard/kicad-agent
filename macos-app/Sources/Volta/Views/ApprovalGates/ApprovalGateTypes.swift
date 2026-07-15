//
//  ApprovalGateTypes.swift
//  Volta
//
//  Phase 174 — Approval Gates UI
//
//  Value types for approval gates: GateType, GateContext, GateResolution,
//  GateDecision. Maps Obdurate Runtime gates to user-facing prompts.
//
//  GSD-05: Approval gates surface decisions visually.
//  GSD-06: Approve/reject/show-me with full context.
//  GSD-07: Verification failures become user decisions.
//

import Foundation

/// Canonical approval gate types — when does the app pause for user input?
enum GateType: String, Codable, Sendable, CaseIterable {
    case ercWarning           // ERC detected warnings (non-blocking but worth surfacing)
    case drcFailure           // DRC failed
    case opConfirmation       // Destructive operation pending (delete, clear, etc.)
    case phaseTransition      // Moving between GSD workflow phases
    case verificationFailure  // Post-op verification failed (PreOp/PostOp)
    case escalation           // Obdurate T1/T2/T3/T4 escalation triggered

    var label: String {
        switch self {
        case .ercWarning: return "ERC Warning"
        case .drcFailure: return "DRC Failure"
        case .opConfirmation: return "Confirm Operation"
        case .phaseTransition: return "Phase Transition"
        case .verificationFailure: return "Verification Failed"
        case .escalation: return "Escalation"
        }
    }

    var systemImage: String {
        switch self {
        case .ercWarning: return "exclamationmark.triangle"
        case .drcFailure: return "xmark.octagon"
        case .opConfirmation: return "questionmark.circle"
        case .phaseTransition: return "arrow.triangle.swap"
        case .verificationFailure: return "checkmark.shield"
        case .escalation: return "exclamationmark.octagon.fill"
        }
    }

    var severityColor: String {
        switch self {
        case .ercWarning: return "warning"
        case .drcFailure: return "destructive"
        case .opConfirmation: return "info"
        case .phaseTransition: return "info"
        case .verificationFailure: return "destructive"
        case .escalation: return "destructive"
        }
    }
}

/// The full context of an approval gate — what the user needs to decide on.
struct GateContext: Identifiable, Sendable, Equatable {
    let id: UUID
    let type: GateType
    let intent: String
    let operation: String
    let verificationResult: VerificationSnapshot?
    let requirementId: String?
    let timestamp: Date
    /// Optional escalation tier (only set for `.escalation` gates).
    let escalationTier: Int?

    init(
        id: UUID = UUID(),
        type: GateType,
        intent: String,
        operation: String,
        verificationResult: VerificationSnapshot? = nil,
        requirementId: String? = nil,
        timestamp: Date = .now,
        escalationTier: Int? = nil
    ) {
        self.id = id
        self.type = type
        self.intent = intent
        self.operation = operation
        self.verificationResult = verificationResult
        self.requirementId = requirementId
        self.timestamp = timestamp
        self.escalationTier = escalationTier
    }
}

/// Snapshot of a verification result (mirrors what Obdurate Runtime emits).
struct VerificationSnapshot: Sendable, Equatable {
    let passed: Bool
    let warningCount: Int
    let errorCount: Int
    let notes: String

    init(passed: Bool, warningCount: Int = 0, errorCount: Int = 0, notes: String = "") {
        self.passed = passed
        self.warningCount = warningCount
        self.errorCount = errorCount
        self.notes = notes
    }
}

/// The three actions a user can take at an approval gate.
enum GateResolution: Sendable, Equatable {
    case approve(decision: GateDecision)
    case reject(reason: String)
    case showMe  // Drill into detail before deciding
}

/// The four-state resolution taxonomy (bureaucracy.md §7).
///
/// Every gate decision maps to one of these states. No silent dismissals.
enum GateDecision: String, Sendable, Equatable {
    case implemented       // Approved — proceed now
    case addedAsPhase      // Approved — but logs as future work
    case superseded        // Rejected — alternative handles it
    case deferred          // Rejected — deferred to named target

    var label: String {
        switch self {
        case .implemented: return "Implemented"
        case .addedAsPhase: return "Added as Phase"
        case .superseded: return "Superseded by Alternative"
        case .deferred: return "Deferred to Named Target"
        }
    }
}

/// Snapshot of a completed gate decision — for audit / SwiftData persistence.
struct GateDecisionRecord: Identifiable, Sendable, Equatable {
    let id: UUID
    let gateId: UUID
    let resolution: GateResolution
    let decidedAt: Date

    init(id: UUID = UUID(), gateId: UUID, resolution: GateResolution, decidedAt: Date = .now) {
        self.id = id
        self.gateId = gateId
        self.resolution = resolution
        self.decidedAt = decidedAt
    }
}
