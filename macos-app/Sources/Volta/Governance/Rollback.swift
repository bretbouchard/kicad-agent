#if os(macOS)
//
//  Rollback.swift
//  Volta
//
//  Phase 170 — Verification Loop Integration
//
//  Auto-rollback on verification failure (GOV-05).
//
//  Wraps the daemon `kicad.snapshot` and `kicad.restore` MCP methods which
//  use the snapshot.py atomic-file-snapshot helper. The Swift side holds
//  the snapshot_id returned by `kicad.snapshot` and passes it to
//  `kicad.restore` when PostOpGate fails.
//
//  Pipeline position (VerificationLoop):
//      Checkpoint → PreOpGate → Execute → PostOpGate → (Rollback on fail)
//
//  The Checkpoint is captured BEFORE the op executes. If PostOpGate
//  returns .failed, Rollback.restore() is invoked to revert files.
//  The journal records every checkpoint and restore event with the
//  snapshot_id so the audit trail is complete (GOV-06).
//

import Foundation
import OSLog

// MARK: - Checkpoint

/// A captured snapshot of files before an op executed.
/// Holds the daemon-issued snapshot_id and the file list.
struct Checkpoint: Sendable, Equatable {
    let snapshotId: String
    let files: [String]
    let capturedAt: Date

    static func == (lhs: Checkpoint, rhs: Checkpoint) -> Bool {
        lhs.snapshotId == rhs.snapshotId
    }
}

// MARK: - RestoreResult

/// Result of a rollback restore operation.
struct RestoreResult: Codable, Sendable, Equatable {
    let restored: Int
    let removed: Int
    let skipped: Int

    /// Total files affected (restored + removed).
    var affectedCount: Int { restored + removed }
}

// MARK: - RollbackError

enum RollbackError: Error, LocalizedError, Equatable {
    case snapshotFailed(String)
    case restoreFailed(String)
    case daemonUnavailable(String)

    var errorDescription: String? {
        switch self {
        case .snapshotFailed(let r):  return "Snapshot failed: \(r)"
        case .restoreFailed(let r):   return "Restore failed: \(r)"
        case .daemonUnavailable(let r): return "Daemon unavailable: \(r)"
        }
    }
}

// MARK: - Rollback

/// File snapshot + restore coordinator for the verification loop.
///
/// Stateless between calls — each `checkpoint(...)` produces an
/// independent Checkpoint that must be tracked by the caller.
///
/// `@MainActor` to share MCPClient's actor isolation.
@MainActor
class Rollback {

    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    private let client: MCPClient?

    init(client: MCPClient? = nil) {
        self.client = client
    }

    // MARK: - Checkpoint (pre-op)

    /// Capture a snapshot of the given files before an op executes.
    ///
    /// - Parameters:
    ///   - files: Absolute file paths to snapshot. Missing files are
    ///     recorded as "to-be-removed-on-restore".
    ///   - baseDir: Optional project root for path-traversal defense.
    /// - Returns: Checkpoint holding the daemon-issued snapshot_id.
    func checkpoint(
        files: [String],
        baseDir: String? = nil
    ) async throws -> Checkpoint {
        guard !files.isEmpty else {
            // Nothing to snapshot — return a no-op checkpoint.
            // restore() will be a no-op too.
            return Checkpoint(
                snapshotId: Rollback.emptySnapshotId,
                files: [],
                capturedAt: Date()
            )
        }
        guard let client else {
            // Test mode without daemon — return an empty placeholder.
            // restore() will detect this and no-op.
            Self.logger.notice(
                "Rollback: no MCPClient wired; returning placeholder checkpoint"
            )
            return Checkpoint(
                snapshotId: Rollback.noClientSnapshotId,
                files: files,
                capturedAt: Date()
            )
        }

        var params: [String: Any] = ["files": files]
        if let baseDir { params["base_dir"] = baseDir }

        do {
            let raw = try await client.callRaw("kicad.snapshot", params: params)
            guard let dict = raw as? [String: Any],
                  let snapshotId = dict["snapshot_id"] as? String else {
                throw RollbackError.snapshotFailed(
                    "daemon returned malformed response: \(raw)")
            }
            Self.logger.debug(
                "Rollback: snapshot captured id=\(snapshotId, privacy: .public) files=\(files.count)"
            )
            return Checkpoint(
                snapshotId: snapshotId,
                files: files,
                capturedAt: Date()
            )
        } catch let rerr as RollbackError {
            throw rerr
        } catch {
            throw RollbackError.snapshotFailed(String(describing: error))
        }
    }

    /// Restore files from a checkpoint.
    ///
    /// Calls daemon `kicad.restore` with the snapshot_id. The daemon
    /// restores all files in the manifest atomically (per-file os.replace).
    ///
    /// - Parameter checkpoint: The checkpoint to restore.
    /// - Returns: RestoreResult with restored/removed/skipped counts.
    func restore(_ checkpoint: Checkpoint) async throws -> RestoreResult {
        // Empty / placeholder checkpoints — no-op.
        if checkpoint.snapshotId == Rollback.emptySnapshotId {
            return RestoreResult(restored: 0, removed: 0, skipped: 0)
        }
        if checkpoint.snapshotId == Rollback.noClientSnapshotId {
            Self.logger.notice(
                "Rollback: cannot restore placeholder checkpoint (no client wired)"
            )
            // Return skipped = file count so callers can detect the no-op.
            return RestoreResult(
                restored: 0,
                removed: 0,
                skipped: checkpoint.files.count
            )
        }

        guard let client else {
            throw RollbackError.daemonUnavailable("no MCPClient wired")
        }

        let params: [String: Any] = ["snapshot_id": checkpoint.snapshotId]
        do {
            let raw = try await client.callRaw("kicad.restore", params: params)
            guard let dict = raw as? [String: Any] else {
                throw RollbackError.restoreFailed(
                    "daemon returned non-dict response: \(raw)")
            }
            let restored = (dict["restored"] as? Int) ?? 0
            let removed = (dict["removed"] as? Int) ?? 0
            let skipped = (dict["skipped"] as? Int) ?? 0
            Self.logger.notice(
                "Rollback: restored id=\(checkpoint.snapshotId, privacy: .public) restored=\(restored) removed=\(removed) skipped=\(skipped)"
            )
            return RestoreResult(restored: restored, removed: removed, skipped: skipped)
        } catch let rerr as RollbackError {
            throw rerr
        } catch {
            throw RollbackError.restoreFailed(String(describing: error))
        }
    }

    // MARK: - Special snapshot IDs

    /// Sentinel: no files to snapshot (empty target list).
    static let emptySnapshotId = "__empty__"

    /// Sentinel: test mode, no MCPClient wired. Restore is a no-op.
    static let noClientSnapshotId = "__no_client__"
}

#endif // os(macOS)
