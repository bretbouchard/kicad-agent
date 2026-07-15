//
//  RollbackTests.swift
//  VoltaTests
//
//  Phase 170 — Verification Loop Integration (GOV-05)
//
//  Tests the snapshot/restore coordinator without a live daemon. The
//  no-client branches return placeholders that the VerificationLoop can
//  drive safely in tests.
//

import Testing
import Foundation
@testable import Volta

@MainActor
@Suite("Rollback")
struct RollbackTests {

    // MARK: - Empty file list

    @Test("Empty files list returns empty sentinel checkpoint")
    func emptyFilesList() async throws {
        let r = Rollback(client: nil)
        let cp = try await r.checkpoint(files: [])
        #expect(cp.snapshotId == Rollback.emptySnapshotId)
        #expect(cp.files.isEmpty)
    }

    @Test("Empty checkpoint restore is no-op")
    func emptyCheckpointRestore() async throws {
        let r = Rollback(client: nil)
        let cp = try await r.checkpoint(files: [])
        let summary = try await r.restore(cp)
        #expect(summary.restored == 0)
        #expect(summary.removed == 0)
        #expect(summary.skipped == 0)
    }

    // MARK: - No client (test mode)

    @Test("No client returns placeholder checkpoint")
    func noClientPlaceholder() async throws {
        let r = Rollback(client: nil)
        let cp = try await r.checkpoint(files: ["/tmp/x.kicad_sch"])
        #expect(cp.snapshotId == Rollback.noClientSnapshotId)
        #expect(cp.files.count == 1)
    }

    @Test("Restoring placeholder no-op returns skipped count")
    func restoringPlaceholderSkips() async throws {
        let r = Rollback(client: nil)
        let cp = try await r.checkpoint(files: ["/tmp/x.kicad_sch", "/tmp/y.kicad_pcb"])
        let summary = try await r.restore(cp)
        #expect(summary.restored == 0)
        #expect(summary.skipped == 2)
    }

    // MARK: - Sentinel stability

    @Test("Sentinel IDs are distinct")
    func sentinelsDistinct() {
        #expect(Rollback.emptySnapshotId != Rollback.noClientSnapshotId)
        #expect(Rollback.emptySnapshotId == "__empty__")
        #expect(Rollback.noClientSnapshotId == "__no_client__")
    }

    // MARK: - Checkpoint equality

    @Test("Checkpoint equality by snapshotId")
    func checkpointEquality() async throws {
        let r = Rollback(client: nil)
        let cp1 = try await r.checkpoint(files: [])
        let cp2 = Checkpoint(
            snapshotId: Rollback.emptySnapshotId,
            files: ["different.kicad_sch"],
            capturedAt: Date.distantPast
        )
        // Equal because snapshotId matches.
        #expect(cp1 == cp2)
    }

    // MARK: - Error mapping

    @Test("RestoreResult affectedCount")
    func restoreResultAffectedCount() {
        let r = RestoreResult(restored: 3, removed: 2, skipped: 1)
        #expect(r.affectedCount == 5)
    }

    @Test("RollbackError descriptions non-empty")
    func rollbackErrorDescriptions() {
        let e1 = RollbackError.snapshotFailed("disk full")
        let e2 = RollbackError.restoreFailed("missing blob")
        let e3 = RollbackError.daemonUnavailable("no client")
        #expect(e1.localizedDescription.contains("disk full"))
        #expect(e2.localizedDescription.contains("missing blob"))
        #expect(e3.localizedDescription.contains("no client"))
    }
}
