#if os(macOS)
//
//  GovernedCall.swift
//  Volta
//
//  Phase 169 — Obdurate Runtime
//
//  Orchestrates the full governance pipeline for a single op call:
//
//      1. IntentGate.validate     (parse + op + requirementId)
//      2. DriftDetector.check     (out-of-scope files)
//      3. WorkflowStateMachine    (mutating ops require .executing)
//      4. MCPClient.call          (the actual op)
//      5. OpJournal.append        (fsync audit trail)
//      6. AutoLearner.store       (success pattern)
//      7. EscalationLadder        (record failure / success)
//
//  GOV-01 (intent gate) — step 1
//  GOV-02 (state machine) — step 3
//  GOV-06 (op journal) — step 5
//  GOV-07 (drift) — step 2
//  GOV-08 (escalation) — step 7
//  GOV-10 (auto-learn) — step 6
//
//  Pipelined as a single `governedCall<T>` method on `MCPClient`. The
//  wrapper returns the decoded result on success and throws on any gate
//  rejection, escalation halt (T4), or transport error.
//

import Foundation
import OSLog

// MARK: - GovernedCallError

enum GovernedCallError: Error, LocalizedError, Equatable {
    case intentRejected(IntentGateError)
    case driftRejected(DriftResult)
    case stateRejected(WorkflowStateMachineError)
    case escalationHalted(tier: EscalationTier, taskKey: String)

    var errorDescription: String? {
        switch self {
        case .intentRejected(let e):       return "Intent rejected: \(e.localizedDescription)"
        case .driftRejected(let r):        return "Drift rejected: \(r.warnings.joined(separator: "; "))"
        case .stateRejected(let e):        return "State machine rejected: \(e.localizedDescription)"
        case .escalationHalted(let tier, let task):
            return "Escalation halted at \(tier.name) for task '\(task)' — human input required"
        }
    }

    static func == (lhs: GovernedCallError, rhs: GovernedCallError) -> Bool {
        switch (lhs, rhs) {
        case (.intentRejected(let a), .intentRejected(let b)):   return a == b
        case (.driftRejected(let a), .driftRejected(let b)):     return a == b
        case (.stateRejected(let a), .stateRejected(let b)):     return a == b
        case (.escalationHalted(let a1, let a2), .escalationHalted(let b1, let b2)):
            return a1 == b1 && a2 == b2
        default: return false
        }
    }
}

// MARK: - Governance shared state

/// Holds the shared governance components. Injected into MCPClient via
/// the environment. The default singleton wires up production instances.
///
/// `@MainActor` because Phase 170's VerificationLoop + gates share
/// MCPClient's MainActor isolation.
@MainActor
final class Governance {

    let stateMachine: WorkflowStateMachine
    let intentGate: IntentGate
    let driftDetector: DriftDetector
    let journal: OpJournal
    let learner: AutoLearner
    let escalation: EscalationLadder
    let verificationLoop: VerificationLoop

    init(stateMachine: WorkflowStateMachine = WorkflowStateMachine(),
                intentGate: IntentGate = IntentGate(),
                driftDetector: DriftDetector = DriftDetector(),
                journal: OpJournal = OpJournal(),
                learner: AutoLearner = AutoLearner(),
                escalation: EscalationLadder = EscalationLadder(),
                verificationLoop: VerificationLoop = VerificationLoop()) {
        self.stateMachine = stateMachine
        self.intentGate = intentGate
        self.driftDetector = driftDetector
        self.journal = journal
        self.learner = learner
        self.escalation = escalation
        self.verificationLoop = verificationLoop
    }

    /// Default shared instance — used by app code.
    static let shared = Governance()
}

// MARK: - Governed call result

/// Wraps a successful governed call. Carries the decoded value plus the
/// journal entry that was written, so callers can log it or chain off it.
struct GovernedCallResult<T: Sendable & Equatable>: Equatable, Sendable {
    let value: T
    let journalEntry: OpJournalEntry
    let intent: IntentResult

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.value == rhs.value && lhs.journalEntry == rhs.journalEntry
    }
}

#endif // os(macOS)
