//
//  DiffUtil.swift
//  Volta
//
//  Phase 178 — Time-Travel Engine
//
//  Field-level diff between two conversation states. Used by TimeTravelView
//  to show what changed between two timestamps.
//
//  TT-04: compare two points (diff view).
//

import Foundation

/// Enum of field-level diff operations.
enum DiffUtil {

    /// Compute diff entries between two field maps.
    ///
    /// Returns entries sorted by fieldPath. Only changed/added/removed fields appear.
    static func diffFields(from: [String: String], to: [String: String]) -> [TimelineDiffEntry] {
        let allPaths = Set(from.keys).union(to.keys).sorted()

        return allPaths.compactMap { path in
            let oldVal = from[path]
            let newVal = to[path]

            if oldVal == newVal { return nil }

            let op: DiffOp
            if oldVal == nil { op = .added }
            else if newVal == nil { op = .removed }
            else { op = .changed }

            return TimelineDiffEntry(
                fieldPath: path,
                op: op,
                oldValueJSON: oldVal,
                newValueJSON: newVal
            )
        }
    }
}

/// One diff entry for timeline display.
struct TimelineDiffEntry: Identifiable, Sendable, Equatable {
    let id = UUID()
    let fieldPath: String
    let op: DiffOp
    let oldValueJSON: String?
    let newValueJSON: String?
}

/// Diff operation kind.
enum DiffOp: String, Sendable, Equatable {
    case added
    case changed
    case removed

    var label: String {
        switch self {
        case .added: return "Added"
        case .changed: return "Changed"
        case .removed: return "Removed"
        }
    }

    var systemImage: String {
        switch self {
        case .added: return "plus.circle.fill"
        case .changed: return "arrow.left.arrow.right.circle.fill"
        case .removed: return "minus.circle.fill"
        }
    }

    var color: String {
        switch self {
        case .added: return "success"
        case .changed: return "warning"
        case .removed: return "destructive"
        }
    }
}
