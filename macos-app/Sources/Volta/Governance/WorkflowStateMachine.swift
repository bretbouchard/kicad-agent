//
//  WorkflowStateMachine.swift
//  Volta
//
//  Phase 169 — Obdurate Runtime
//
//  GSD state machine. Enforces the bureaucracy.md §1 transition table:
//
//      questioning → research → planning → review → execute → verification → complete
//
//  Two transitions carry hard guards:
//    - review → execute: requires `planApproved`
//    - verification → complete: requires `verificationPassed`
//
//  GOV-02: "Workflow State Machine enforces phase transitions (can't run
//  DRC without PCB, can't execute without approved plan)".
//
//  The machine is value-type where possible (state + flags) but uses a
//  class with NSLock for the public mutable surface so it can be passed
//  around and observed. State mutations are serialized on the lock.
//

import Foundation
import OSLog

// MARK: - WorkflowStateMachineError

/// Errors raised by the state machine.
enum WorkflowStateMachineError: Error, LocalizedError, Equatable {
    case invalidTransition(from: WorkflowState, to: WorkflowState)
    case guardFailed(WorkflowTransition, String)
    case alreadyInState(WorkflowState)

    var errorDescription: String? {
        switch self {
        case .invalidTransition(let from, let to):
            return "Invalid workflow transition: \(from.rawValue) → \(to.rawValue)"
        case .guardFailed(let transition, let reason):
            return "Guard failed for \(transition.rawValue): \(reason)"
        case .alreadyInState(let state):
            return "Workflow is already in \(state.rawValue)"
        }
    }
}

// MARK: - WorkflowStateMachine

/// GSD workflow state machine. Thread-safe via internal NSLock.
///
/// Usage:
///   let machine = WorkflowStateMachine()
///   try machine.transition(.questionToSpec)
///   try machine.transition(.specToRoadmap)
///   try machine.transition(.reviewToExecute, planApproved: true)
///
/// Hard guards:
///   - `reviewToExecute` requires `planApproved == true`
///   - `verifyingToComplete` requires `verificationPassed == true`
final class WorkflowStateMachine: @unchecked Sendable {

    /// Logger for state transitions (advisory — never blocks).
    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    private let lock = NSLock()

    /// Current state. Always read/write under `lock`.
    private var _state: WorkflowState = .questioning

    /// Public snapshot of the current state (lock-protected).
    var state: WorkflowState {
        lock.lock(); defer { lock.unlock() }
        return _state
    }

    /// Flag: has the plan been approved? Required for review→execute.
    /// Reset to false on every reset()/after entering executing.
    private var _planApproved: Bool = false
    var planApproved: Bool {
        lock.lock(); defer { lock.unlock() }
        return _planApproved
    }

    /// Flag: has verification passed? Required for verifying→complete.
    private var _verificationPassed: Bool = false
    var verificationPassed: Bool {
        lock.lock(); defer { lock.unlock() }
        return _verificationPassed
    }

    init(initialState: WorkflowState = .questioning) {
        self._state = initialState
    }

    // MARK: - Predicate

    /// Can we legally make this transition from the current state, with the
    /// given guards? Pure (read-only) — does not mutate.
    func canTransition(_ transition: WorkflowTransition,
                              planApproved: Bool = false,
                              verificationPassed: Bool = false) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return canTransitionLocked(transition,
                                   planApproved: planApproved,
                                   verificationPassed: verificationPassed)
    }

    private func canTransitionLocked(_ transition: WorkflowTransition,
                                     planApproved: Bool,
                                     verificationPassed: Bool) -> Bool {
        // Special case: reset always works (panic-button).
        if transition == .reset { return true }

        // Source state must match.
        guard _state == transition.from else { return false }

        // Hard guards.
        if transition == .reviewToExecute, !planApproved { return false }
        if transition == .verifyingToComplete, !verificationPassed { return false }

        return true
    }

    // MARK: - Transition

    /// Apply a transition. Throws on invalid transition or failed guard.
    @discardableResult
    func transition(_ transition: WorkflowTransition,
                           planApproved: Bool = false,
                           verificationPassed: Bool = false) throws -> WorkflowState {
        lock.lock()

        // Validate guards first (so reset case still works without args).
        guard canTransitionLocked(transition,
                                  planApproved: planApproved,
                                  verificationPassed: verificationPassed) else {
            lock.unlock()
            // Emit specific error for the failure mode.
            if _state != transition.from {
                throw WorkflowStateMachineError.invalidTransition(from: _state, to: transition.to)
            }
            if transition == .reviewToExecute, !planApproved {
                throw WorkflowStateMachineError.guardFailed(.reviewToExecute, "planApproved required")
            }
            if transition == .verifyingToComplete, !verificationPassed {
                throw WorkflowStateMachineError.guardFailed(.verifyingToComplete,
                                                            "verificationPassed required")
            }
            throw WorkflowStateMachineError.invalidTransition(from: _state, to: transition.to)
        }

        // Apply.
        let previous = _state
        let next = transition.to
        _state = next
        _planApproved = planApproved || (transition != .reviewToExecute ? _planApproved : false)
        _verificationPassed = verificationPassed

        // Reset cycle if we re-entered executing from verifying-fail.
        if transition == .verifyingBackToExecute {
            _verificationPassed = false
        }
        // Reset cycle if we just reset.
        if transition == .reset {
            _planApproved = false
            _verificationPassed = false
        }

        lock.unlock()

        Self.logger.info("WorkflowState \(previous.rawValue, privacy: .public) → \(next.rawValue, privacy: .public)")
        return next
    }

    // MARK: - Snapshot / Restore

    /// Serializable snapshot for persistence across app launches.
    struct Snapshot: Codable, Equatable, Sendable {
        let state: WorkflowState
        let planApproved: Bool
        let verificationPassed: Bool
    }

    func snapshot() -> Snapshot {
        lock.lock(); defer { lock.unlock() }
        return Snapshot(state: _state,
                        planApproved: _planApproved,
                        verificationPassed: _verificationPassed)
    }

    /// Restore from snapshot. Used on app restart to resume the workflow.
    /// Throws if the snapshot contains an invalid combination.
    func restore(_ snapshot: Snapshot) throws {
        lock.lock(); defer { lock.unlock() }
        // Validate invariants:
        // - Can't be in executing without planApproved.
        if snapshot.state == .executing, !snapshot.planApproved {
            throw WorkflowStateMachineError.guardFailed(.reviewToExecute,
                                                       "restored .executing without planApproved")
        }
        // - Can't be in complete without verificationPassed.
        if snapshot.state == .complete, !snapshot.verificationPassed {
            throw WorkflowStateMachineError.guardFailed(.verifyingToComplete,
                                                       "restored .complete without verificationPassed")
        }
        _state = snapshot.state
        _planApproved = snapshot.planApproved
        _verificationPassed = snapshot.verificationPassed
    }

    // MARK: - Force (testing/admin only)

    /// Force the state machine into a specific state without going through
    /// a named transition. Used by tests and the panic-reset code path.
    /// Production code should always go through `transition(...)`.
    func forceState(_ state: WorkflowState) {
        lock.lock(); defer { lock.unlock() }
        _state = state
        _planApproved = (state == .executing || state == .verifying || state == .complete)
        _verificationPassed = (state == .complete)
    }
}
