//
//  ConflictResolver.swift
//  Volta
//
//  Phase 177 — CloudKit Sync
//
//  LWW conflict resolution with prompts. Most fields auto-resolve via
//  Last-Write-Wins (LWW). User-facing value changes (spec fields) prompt
//  the user to choose local / remote / merge.
//
//  MEM-02: conflict resolution with prompts for value changes.
//

import Foundation
import OSLog

/// LWW conflict resolver with selective prompts.
///
/// ponytail: stateless functions. Each resolve call returns a decision.
/// UI layer (Phase 179 Timeline) wires the prompts to actual sheets.
final class ConflictResolver: Sendable {
    /// Init with default LWW policy.
    init() {}

    /// Resolve a generic field conflict using pure LWW.
    ///
    /// MEM-02: LWW for most fields. Latest timestamp wins.
    func resolveLWW<T>(local: T, localTimestamp: Date, remote: T, remoteTimestamp: Date) -> T {
        remoteTimestamp >= localTimestamp ? remote : local
    }

    /// Resolve a value-change conflict.
    ///
    /// Returns the resolution. If user prompt is required, returns .needsPrompt
    /// and the UI shows a sheet (Phase 179).
    func resolveValueChange(
        local: ValueChangePayload,
        remote: ValueChangePayload
    ) -> ValueChangeResolution {
        // Auto-resolve: same actor, equal newValueJSON → take either.
        if local.actorRaw == remote.actorRaw && local.newValueJSON == remote.newValueJSON {
            return .auto(remote) // Idempotent — pick remote to dedupe
        }

        // LWW: latest timestamp wins.
        if remote.changedAt > local.changedAt {
            return .auto(remote)
        }
        if local.changedAt > remote.changedAt {
            return .auto(local)
        }

        // Same timestamp, different values → prompt user.
        return .needsPrompt(local: local, remote: remote)
    }
}

/// Snapshot of a ValueChange for conflict resolution (decoupled from SwiftData).
struct ValueChangePayload: Sendable, Equatable {
    let id: UUID
    let fieldPath: String
    let oldValueJSON: String
    let newValueJSON: String
    let changedAt: Date
    let actorRaw: String

    init(
        id: UUID = UUID(),
        fieldPath: String,
        oldValueJSON: String = "{}",
        newValueJSON: String = "{}",
        changedAt: Date,
        actorRaw: String
    ) {
        self.id = id
        self.fieldPath = fieldPath
        self.oldValueJSON = oldValueJSON
        self.newValueJSON = newValueJSON
        self.changedAt = changedAt
        self.actorRaw = actorRaw
    }

    static let empty = ValueChangePayload(
        id: UUID(),
        fieldPath: "",
        oldValueJSON: "{}",
        newValueJSON: "{}",
        changedAt: .distantPast,
        actorRaw: "user"
    )
}

/// Resolution outcome — either auto-resolved or needs user prompt.
enum ValueChangeResolution: Sendable, Equatable {
    case auto(ValueChangePayload)
    case needsPrompt(local: ValueChangePayload, remote: ValueChangePayload)

    var isAuto: Bool {
        if case .auto = self { return true }
        return false
    }

    var needsPrompt: Bool {
        if case .needsPrompt = self { return true }
        return false
    }
}
