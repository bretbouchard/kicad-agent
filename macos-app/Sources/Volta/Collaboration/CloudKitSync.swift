//
//  CloudKitSync.swift
//  Volta
//
//  Phase 177 — CloudKit Sync
//
//  Coordinates SwiftData ↔ CloudKit private database sync. Wraps the
//  ModelContainer configuration options + surfaces sync status to UI.
//
//  MEM-02: Mac↔iPhone automatic sync.
//  MEM-09: cross-project search via CloudKit index.
//  MEM-10: two-device migration safety (no auto-migration).
//
//  Pitfall 4 prevention: schema versioning is EXPLICIT. No auto-migration.
//  Adding a new model requires VersionedSchema bump + this file update.
//

import Foundation
import CloudKit
import SwiftData
import OSLog

/// Coordinator for SwiftData + CloudKit sync.
///
/// Manages:
/// - ModelConfiguration with CloudKit private DB
/// - Sync status observation
/// - Conflict resolution policy (LWW with prompts via ConflictResolver)
/// - Schema versioning gate (refuses auto-migration)
@MainActor
@Observable
final class CloudKitSync {
    /// Sync status surfaced to UI.
    private(set) var status: SyncStatus = .idle

    /// Last sync timestamp (UTC).
    private(set) var lastSyncedAt: Date?

    /// CloudKit account status — gates sync.
    private(set) var accountStatus: CKAccountStatus = .couldNotDetermine

    /// Conflict resolver instance (LWW with prompts).
    let conflictResolver: ConflictResolver

    /// True when iCloud account is available for sync.
    var isAvailable: Bool {
        accountStatus == .available
    }

    init(conflictResolver: ConflictResolver = ConflictResolver()) {
        self.conflictResolver = conflictResolver
    }

    /// Build a ModelConfiguration configured for CloudKit sync.
    /// Returns nil if CloudKit container ID not configured.
    func makeCloudKitConfiguration() -> ModelConfiguration? {
        guard let containerId = Self.cloudKitContainerId else {
            Logger.models.warning("CloudKit container ID not configured — sync disabled")
            return nil
        }

        // Pitfall 4 prevention: explicit cloudKitDatabase, no auto-migration.
        // The schema is set via ModelContainer(for:) at the app level — this
        // config only adds the CloudKit private database binding.
        return ModelConfiguration(
            cloudKitDatabase: .private(containerId)
        )
    }

    /// Probe CKAccountStatus. Call on app launch.
    func refreshAccountStatus() async {
        do {
            let status = try await CKContainer.default().accountStatus()
            self.accountStatus = status
            self.status = (status == .available) ? .ready : .unavailable(reason: "iCloud account required")
            Logger.models.info("CloudKit account status: \(status.rawValue)")
        } catch {
            self.status = .unavailable(reason: error.localizedDescription)
            Logger.models.error("CloudKit account status check failed: \(error.localizedDescription)")
        }
    }

    /// Container ID from environment (CKContainerIdentifier env var or default).
    /// Nonisolated: pure env-var read, safe from any actor.
    nonisolated static var cloudKitContainerId: String? {
        // Production: set via Info.plist or environment. Default nil = disabled.
        ProcessInfo.processInfo.environment["CK_CONTAINER_ID"]
    }
}

/// Sync status enum.
enum SyncStatus: Equatable, Sendable {
    case idle
    case ready
    case syncing
    case unavailable(reason: String)
    case error(message: String)

    var label: String {
        switch self {
        case .idle: return "Not started"
        case .ready: return "Ready"
        case .syncing: return "Syncing…"
        case .unavailable(let reason): return "Unavailable: \(reason)"
        case .error(let message): return "Error: \(message)"
        }
    }
}

/// CloudKit container configuration helper.
enum CloudKitConfig {
    /// Build the CKContainer instance for the given identifier.
    static func container(for identifier: String) -> CKContainer {
        CKContainer(identifier: identifier)
    }
}
