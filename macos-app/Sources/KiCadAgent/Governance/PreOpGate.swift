//
//  PreOpGate.swift
//  KiCadAgent
//
//  Phase 170 — Verification Loop Integration
//
//  Pre-op verification gate. Validates that the op's intent matches
//  the op being called AND that the op will plausibly achieve the goal.
//  Delegates file-type / args validation to the Python daemon's
//  `kicad.pre_check` MCP method, which wraps the existing
//  `ops/validation_gates.py` infrastructure.
//
//  GOV-03: "Pre-op verification gate (intent matches op, will achieve goal)."
//
//  Pipeline position (VerificationLoop):
//      [snapshot] → PreOpGate → [execute] → PostOpGate → [restore on fail]
//
//  Decision mapping:
//      daemon "allow" → .allow   (proceed to execute)
//      daemon "warn"  → .warn    (proceed, journal the warning)
//      daemon "block" → .block   (reject the call, no execute)
//
//  The Swift side also runs a local IntentResult sanity check before
//  calling the daemon — if the intent is malformed, we short-circuit
//  with a block to avoid the round-trip.
//

import Foundation
import OSLog

// MARK: - PreOpDecision

/// Decision returned by PreOpGate.
enum PreOpDecision: String, Codable, Sendable, Equatable {
    case allow
    case warn
    case block
}

// MARK: - PreOpResult

/// Result of a pre-op gate check.
struct PreOpResult: Codable, Sendable, Equatable {
    let decision: PreOpDecision
    let reasons: [String]
    let opType: String
    /// Individual check outcomes from the daemon.
    let checks: [String: Bool]

    /// Shorthand for "should we proceed with execution?"
    var shouldExecute: Bool {
        decision == .allow || decision == .warn
    }

    /// Static allow result used when the daemon is unreachable but the
    /// intent is trivially valid (e.g. for read-only ops). Phase 170
    /// favors availability: a daemon outage shouldn't block read-only
    /// queries, but it DOES block mutating ops (safer default).
    static func allowReadOnly(op: String) -> PreOpResult {
        return PreOpResult(
            decision: .allow,
            reasons: ["read-only op; daemon check skipped"],
            opType: op,
            checks: ["op_known": true, "file_type_ok": true, "args_present": true]
        )
    }

    /// Static block result for daemon failures on mutating ops.
    static func blockDaemonUnavailable(op: String, error: String) -> PreOpResult {
        return PreOpResult(
            decision: .block,
            reasons: ["daemon unavailable: \(error)"],
            opType: op,
            checks: ["daemon_reachable": false]
        )
    }
}

// MARK: - PreOpGateError

enum PreOpGateError: Error, LocalizedError, Equatable {
    case malformedIntent(String)
    case daemonFailure(String)

    var errorDescription: String? {
        switch self {
        case .malformedIntent(let r): return "Pre-op intent malformed: \(r)"
        case .daemonFailure(let r):   return "Pre-op daemon failure: \(r)"
        }
    }
}

// MARK: - PreOpGate

/// Pre-op verification gate. Wraps the daemon `kicad.pre_check` MCP method.
///
/// Stateless — call `check(...)` per op. Holds a reference to the MCPClient
/// so it can invoke the daemon async.
///
/// `@MainActor` to share MCPClient's actor isolation — avoids sendability
/// crossings on the `[String: Any]` params dict.
@MainActor
class PreOpGate {

    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    private let client: MCPClient?

    init(client: MCPClient? = nil) {
        self.client = client
    }

    // MARK: - Check

    /// Validate an intent against the daemon pre-check service.
    ///
    /// - Parameters:
    ///   - intent: Validated IntentResult from IntentGate.
    ///   - args: Raw args dict (will be JSON-serialized for the daemon call).
    /// - Returns: PreOpResult with decision + reasons.
    func check(
        intent: IntentResult,
        args: [String: Any]
    ) async -> PreOpResult {  // swift-testing: subclassible
        // 1. Local sanity: intent must carry an op name.
        guard !intent.op.isEmpty else {
            return PreOpResult(
                decision: .block,
                reasons: ["intent.op is empty"],
                opType: intent.op,
                checks: ["intent_valid": false]
            )
        }

        // 2. Read-only ops skip the daemon round-trip.
        //    They cannot mutate files, so file-type pre-check adds latency
        //    without correctness value. Local catalog validation already
        //    ran in IntentGate.
        if intent.isReadonly {
            return PreOpResult.allowReadOnly(op: intent.op)
        }

        // 3. Daemon pre_check.
        guard let client else {
            // No client wired (test mode without daemon) — fail soft,
            // warn rather than block so unit tests don't require a live daemon.
            Self.logger.notice(
                "PreOpGate: no MCPClient wired; allowing op '\(intent.op, privacy: .public)' (warn)"
            )
            return PreOpResult(
                decision: .warn,
                reasons: ["no MCPClient wired (test mode)"],
                opType: intent.op,
                checks: ["client_wired": false]
            )
        }

        let params: [String: Any] = [
            "op_type": intent.op,
            "args": args,
        ]

        do {
            let raw = try await client.callRaw("kicad.pre_check", params: params)
            return PreOpGate.decode(raw: raw, fallbackOp: intent.op)
        } catch {
            Self.logger.warning(
                "PreOpGate: daemon pre_check failed: \(String(describing: error), privacy: .public)"
            )
            return PreOpResult.blockDaemonUnavailable(
                op: intent.op, error: String(describing: error))
        }
    }

    // MARK: - Decoding

    /// Decode the daemon response into PreOpResult. Tolerant of missing keys.
    static func decode(raw: Any, fallbackOp: String) -> PreOpResult {
        guard let dict = raw as? [String: Any] else {
            return PreOpResult(
                decision: .block,
                reasons: ["daemon returned non-dict response"],
                opType: fallbackOp,
                checks: [:]
            )
        }
        let decisionStr = (dict["decision"] as? String) ?? "block"
        let decision = PreOpDecision(rawValue: decisionStr) ?? .block
        let reasons = (dict["reasons"] as? [String]) ?? []
        let opType = (dict["op_type"] as? String) ?? fallbackOp
        var checks: [String: Bool] = [:]
        if let ck = dict["checks"] as? [String: Any] {
            for (k, v) in ck {
                if let b = v as? Bool {
                    checks[k] = b
                } else if let s = v as? String {
                    checks[k] = (s == "true")
                }
            }
        }
        return PreOpResult(
            decision: decision,
            reasons: reasons,
            opType: opType,
            checks: checks
        )
    }
}
