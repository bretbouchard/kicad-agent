//
//  VerificationLoop.swift
//  KiCadAgent
//
//  Phase 170 — Verification Loop Integration
//
//  Orchestrates the full verification pipeline for one governed op:
//
//      1. Checkpoint (Rollback)       — capture file snapshots
//      2. PreOpGate                   — validate intent vs op
//      3. Execute (caller-provided)   — the actual op
//      4. PostOpGate                  — ERC/DRC + semantic check
//      5. Restore (Rollback)          — if PostOpGate failed
//      6. Journal append              — full stage history
//
//  Replaces the simple IntentGate + journal wiring that lived in
//  MCPClient.governedCall before Phase 170. The loop is constructed
//  once per MCPClient (via Governance.verification) and invoked by
//  governedCall for each op.
//
//  GOV-03 (pre-op), GOV-04 (post-op), GOV-05 (rollback) — all three
//  requirements land here as a single pipeline.
//

import Foundation
import OSLog

// MARK: - VerificationOutcome

/// Result of running the full verification loop for one op.
struct VerificationOutcome: Sendable, Equatable {
    /// The op result returned by the executor (nil on pre-op block).
    let result: AnyCodable?
    /// Decision across all stages.
    let status: Status
    /// Pre-op gate result.
    let preOp: PreOpResult
    /// Post-op gate result (nil if pre-op blocked or execution threw).
    let postOp: PostOpResult?
    /// Snapshot id captured before execution (nil if no files to snapshot).
    let checkpointId: String?
    /// Restore summary if rollback fired (nil otherwise).
    let restore: RestoreResult?
    /// Stage timings in milliseconds.
    let stageTimingsMs: [String: Int]

    enum Status: String, Codable, Sendable, Equatable {
        case passed           // full pass — op committed
        case failed           // post-op failed, rollback fired
        case blocked          // pre-op blocked — op never ran
        case executionFailed  // op threw — no post-op check
        case indeterminate    // post-op couldn't determine — op committed
    }

    /// True if the op is committed (no rollback needed).
    var isCommitted: Bool {
        status == .passed || status == .indeterminate
    }

    /// True if rollback fired.
    var didRollback: Bool {
        restore != nil
    }
}

// MARK: - VerificationLoop

/// Orchestrates pre-op → execute → post-op → rollback pipeline.
///
/// Holds references to the gates and rollback coordinator. The executor
/// itself is provided per-call (so callers control transport + decoding).
///
/// `@MainActor` because PreOpGate/PostOpGate/Rollback are @MainActor
/// (they share MCPClient's isolation).
@MainActor
class VerificationLoop {

    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    let preOpGate: PreOpGate
    let postOpGate: PostOpGate
    let rollback: Rollback

    init(preOpGate: PreOpGate = PreOpGate(),
                postOpGate: PostOpGate = PostOpGate(),
                rollback: Rollback = Rollback()) {
        self.preOpGate = preOpGate
        self.postOpGate = postOpGate
        self.rollback = rollback
    }

    // MARK: - Run

    /// Run the full verification loop for one op.
    ///
    /// - Parameters:
    ///   - intent: Validated IntentResult (from IntentGate).
    ///   - args: Raw args dict for the op.
    ///   - executor: Async closure that performs the actual op call and
    ///     returns the raw result + brief summary string. Throwing from
    ///     here marks the outcome as `.executionFailed`.
    /// - Returns: VerificationOutcome with all stage data.
    func run(
        intent: IntentResult,
        args: [String: Any],
        executor: () async throws -> (result: AnyCodable, summary: String)
    ) async -> VerificationOutcome {
        var timings: [String: Int] = [:]
        let checkpointStart = ContinuousClock.now

        // 1. Checkpoint (skip if no files).
        var checkpoint: Checkpoint? = nil
        if !intent.targetFiles.isEmpty {
            do {
                checkpoint = try await rollback.checkpoint(files: intent.targetFiles)
            } catch {
                Self.logger.error(
                    "VerificationLoop: checkpoint failed: \(String(describing: error), privacy: .public)"
                )
                // Snapshot failure is non-fatal — we proceed but lose rollback.
                // The journal records this; post-op failure then surfaces as
                // .failed without rollback rather than blocking the op entirely.
            }
        }
        timings["checkpoint_ms"] = VerificationLoop.elapsedMs(since: checkpointStart)

        // 2. Pre-op gate.
        let preStart = ContinuousClock.now
        let preResult = await preOpGate.check(intent: intent, args: args)
        timings["pre_op_ms"] = VerificationLoop.elapsedMs(since: preStart)

        if !preResult.shouldExecute {
            Self.logger.notice(
                "VerificationLoop: pre-op blocked op '\(intent.op, privacy: .public)': \(preResult.reasons)"
            )
            return VerificationOutcome(
                result: nil,
                status: .blocked,
                preOp: preResult,
                postOp: nil,
                checkpointId: checkpoint?.snapshotId,
                restore: nil,
                stageTimingsMs: timings
            )
        }

        // 3. Execute.
        let execStart = ContinuousClock.now
        let executed: (result: AnyCodable, summary: String)
        do {
            executed = try await executor()
        } catch {
            timings["execute_ms"] = VerificationLoop.elapsedMs(since: execStart)
            Self.logger.warning(
                "VerificationLoop: execute failed: \(String(describing: error), privacy: .public)"
            )
            return VerificationOutcome(
                result: nil,
                status: .executionFailed,
                preOp: preResult,
                postOp: nil,
                checkpointId: checkpoint?.snapshotId,
                restore: nil,
                stageTimingsMs: timings
            )
        }
        timings["execute_ms"] = VerificationLoop.elapsedMs(since: execStart)

        // 4. Post-op gate.
        let postStart = ContinuousClock.now
        let postResult = await postOpGate.verify(intent: intent, opResult: executed.summary)
        timings["post_op_ms"] = VerificationLoop.elapsedMs(since: postStart)

        // 5. Rollback if failed.
        var restoreResult: RestoreResult? = nil
        var finalStatus: VerificationOutcome.Status
        if postResult.decision == .failed {
            finalStatus = .failed
            if let checkpoint {
                let restoreStart = ContinuousClock.now
                do {
                    restoreResult = try await rollback.restore(checkpoint)
                } catch {
                    Self.logger.error(
                        "VerificationLoop: rollback failed: \(String(describing: error), privacy: .public)"
                    )
                    // Rollback failure is severe — surface in journal but don't
                    // mask the verification failure. Restore summary stays nil.
                }
                timings["restore_ms"] = VerificationLoop.elapsedMs(since: restoreStart)
            }
        } else if postResult.decision == .indeterminate {
            finalStatus = .indeterminate
        } else {
            finalStatus = .passed
        }

        return VerificationOutcome(
            result: executed.result,
            status: finalStatus,
            preOp: preResult,
            postOp: postResult,
            checkpointId: checkpoint?.snapshotId,
            restore: restoreResult,
            stageTimingsMs: timings
        )
    }

    // MARK: - Helpers

    private static func elapsedMs(since start: ContinuousClock.Instant) -> Int {
        let elapsed = ContinuousClock.now - start
        return Int(elapsed.components.seconds) * 1000
            + Int(elapsed.components.attoseconds / 1_000_000_000_000_000)
    }
}
