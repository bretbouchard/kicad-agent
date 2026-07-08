//
//  WorkflowState.swift
//  KiCadAgent
//
//  Phase 169 — Obdurate Runtime
//
//  GSD workflow phase enum. Mirrors ~/.claude/rules/bureaucracy.md §1:
//
//      questioning → research → planning → review → execute → verification → complete
//
//  The state machine enforces these transitions on the Swift side so the
//  UI cannot dispatch a `kicad.pcb_run_drc` op while still in questioning,
//  and cannot skip review to reach execute. Each transition has a guard
//  (e.g. review→execute requires `planApproved`).
//
//  GOV-02: Workflow State Machine enforces phase transitions.
//

import Foundation

// MARK: - WorkflowState

/// GSD workflow phase. Order matches bureaucracy.md §1 state machine.
///
/// Raw values are the strings persisted in journal entries and state-file
/// exports — keep them stable across versions.
enum WorkflowState: String, Codable, Sendable, CaseIterable {
    case questioning
    case specGenerated
    case roadmapApproved
    case executing
    case verifying
    case complete

    /// Human-readable label for the UI.
    var label: String {
        switch self {
        case .questioning:     return "Questioning"
        case .specGenerated:   return "Spec Generated"
        case .roadmapApproved: return "Roadmap Approved"
        case .executing:       return "Executing"
        case .verifying:       return "Verifying"
        case .complete:        return "Complete"
        }
    }

    /// True when ops that mutate KiCad files are permitted in this phase.
    /// Mutating ops are blocked outside `.executing` (per GOV-02).
    var allowsMutation: Bool {
        self == .executing
    }

    /// True when read-only inspection ops are permitted.
    /// Query ops are allowed from `.roadmapApproved` onward — earlier phases
    /// have no artifacts to inspect.
    var allowsReadonlyOps: Bool {
        switch self {
        case .questioning, .specGenerated:
            return false
        case .roadmapApproved, .executing, .verifying, .complete:
            return true
        }
    }
}

// MARK: - WorkflowTransition

/// Named transitions between workflow states. Encoding every legal move as
/// a case makes the state-machine table easy to audit (one enum case per
/// arrow in the bureaucracy diagram, plus the two hard-guarded moves).
enum WorkflowTransition: String, Codable, Sendable {
    case questionToSpec          // questioning → specGenerated
    case specToRoadmap           // specGenerated → roadmapApproved
    case roadmapToReview         // roadmapApproved → reviewing (no state for review in v1)
    case reviewToExecute         // requires planApproved
    case executeToVerifying      // execute → verifying
    case verifyingToComplete     // requires verificationPassed
    case verifyingBackToExecute  // failed verification — loop back
    case reset                   // panic-reset to questioning

    /// Source state for this transition.
    var from: WorkflowState {
        switch self {
        case .questionToSpec:          return .questioning
        case .specToRoadmap:           return .specGenerated
        case .roadmapToReview:         return .roadmapApproved
        case .reviewToExecute:         return .roadmapApproved   // gate checked in machine
        case .executeToVerifying:      return .executing
        case .verifyingToComplete:     return .verifying
        case .verifyingBackToExecute:  return .verifying
        case .reset:                   return .complete   // special — see StateMachine
        }
    }

    /// Destination state for this transition.
    var to: WorkflowState {
        switch self {
        case .questionToSpec:          return .specGenerated
        case .specToRoadmap:           return .roadmapApproved
        case .roadmapToReview:         return .roadmapApproved   // review is implicit in v1
        case .reviewToExecute:         return .executing
        case .executeToVerifying:      return .verifying
        case .verifyingToComplete:     return .complete
        case .verifyingBackToExecute:  return .executing
        case .reset:                   return .questioning
        }
    }
}
