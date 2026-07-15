#if os(macOS)
//
//  PostOpGate.swift
//  Volta
//
//  Phase 170 — Verification Loop Integration
//
//  Post-op verification gate. Runs:
//    1. Deterministic check: ERC (schematic) / DRC (PCB) via kicad-cli,
//       driven through the daemon `kicad.post_check` MCP method which
//       wraps the existing `validation/erc_drc.py` + `ops/validation_gates.py`
//       infrastructure.
//    2. Semantic check: brief LLM call asking "did this op achieve its
//       stated intent?" Optional — only runs if a KiCadModelProvider is
//       wired. Skip silently when no provider is available.
//
//  GOV-04: "Post-op verification gate (deterministic check + semantic check)."
//
//  Pipeline position (VerificationLoop):
//      [snapshot] → PreOpGate → [execute] → PostOpGate → [restore on fail]
//
//  Decision mapping:
//      daemon "passed"        + (no LLM or LLM says yes) → .passed
//      daemon "failed"        → .failed (rollback trigger)
//      daemon "indeterminate" → .indeterminate (journal, no rollback)
//      LLM says "no"          → .failed (semantic veto)
//

import Foundation
import OSLog

// MARK: - PostOpDecision

enum PostOpDecision: String, Codable, Sendable, Equatable {
    case passed
    case failed
    case indeterminate
}

// MARK: - PostOpResult

struct PostOpResult: Codable, Sendable, Equatable {
    let decision: PostOpDecision
    let failures: [String]
    /// Raw ERC summary from the daemon (may be nil if check skipped).
    let ercSummary: [String: AnyCodable]?
    /// Raw DRC summary from the daemon (may be nil if check skipped).
    let drcSummary: [String: AnyCodable]?
    /// Semantic LLM verdict — true if intent was achieved.
    let semanticVerdict: Bool?

    /// Shorthand — did all checks pass and semantic agrees (or was skipped)?
    var isPassed: Bool {
        decision == .passed
    }

    /// Static skip result for read-only ops.
    static func skipReadOnly(op: String) -> PostOpResult {
        return PostOpResult(
            decision: .passed,
            failures: ["read-only op; post-check skipped"],
            ercSummary: nil,
            drcSummary: nil,
            semanticVerdict: nil
        )
    }
}

// MARK: - SemanticJudge protocol

/// Minimal protocol the PostOpGate uses for the semantic LLM check.
/// Wired to the real KiCadModelProvider in production; mocked in tests.
protocol SemanticJudge: Sendable {
    /// Ask the judge whether the op achieved its stated intent.
    /// - Returns: true (yes), false (no), or nil (indeterminate).
    func judge(intent: String, op: String, result: String) async -> Bool?
}

/// Default no-op judge used when no provider is available.
/// Always returns nil (indeterminate) — deterministic check still runs.
struct NoSemanticJudge: SemanticJudge {
    func judge(intent: String, op: String, result: String) async -> Bool? {
        return nil
    }
}

// MARK: - PostOpGate

/// Post-op verification gate. Combines daemon-driven ERC/DRC with an
/// optional semantic LLM check.
///
/// `@MainActor` to share MCPClient's actor isolation.
@MainActor
class PostOpGate {

    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    private let client: MCPClient?
    private let judge: SemanticJudge

    init(client: MCPClient? = nil, judge: SemanticJudge = NoSemanticJudge()) {
        self.client = client
        self.judge = judge
    }

    // MARK: - Verify

    /// Run post-op checks.
    ///
    /// - Parameters:
    ///   - intent: The validated IntentResult (carries op + targetFiles).
    ///   - opResult: Brief description of what the op returned (for LLM).
    /// - Returns: PostOpResult with decision + raw check data.
    func verify(
        intent: IntentResult,
        opResult: String
    ) async -> PostOpResult {
        // 1. Read-only ops skip — they cannot have changed file state.
        if intent.isReadonly {
            return PostOpResult.skipReadOnly(op: intent.op)
        }

        // 2. Deterministic check via daemon.
        var daemonResult: [String: Any] = [:]
        if let client {
            let params: [String: Any] = [
                "op_type": intent.op,
                "files": intent.targetFiles,
                "require_erc": intent.targetFiles.contains(where: { $0.hasSuffix(".kicad_sch") }),
                "require_drc": intent.targetFiles.contains(where: { $0.hasSuffix(".kicad_pcb") }),
            ]
            do {
                let raw = try await client.callRaw("kicad.post_check", params: params)
                if let dict = raw as? [String: Any] {
                    daemonResult = dict
                } else {
                    daemonResult = ["decision": "indeterminate",
                                    "failures": ["daemon returned non-dict response"]]
                }
            } catch {
                Self.logger.warning(
                    "PostOpGate: daemon post_check failed: \(String(describing: error), privacy: .public)"
                )
                daemonResult = [
                    "decision": "indeterminate",
                    "failures": ["daemon unavailable: \(String(describing: error))"],
                ]
            }
        } else {
            // Test mode without daemon — indeterminate.
            daemonResult = [
                "decision": "indeterminate",
                "failures": ["no MCPClient wired (test mode)"],
            ]
        }

        let decisionStr = (daemonResult["decision"] as? String) ?? "indeterminate"
        let deterministicDecision = PostOpDecision(rawValue: decisionStr) ?? .indeterminate
        let failures = (daemonResult["failures"] as? [String]) ?? []
        let ercSummary = PostOpGate.toCodable(daemonResult["erc"])
        let drcSummary = PostOpGate.toCodable(daemonResult["drc"])

        // 3. Semantic check — only if deterministic passed.
        //    If deterministic failed, no point asking the LLM.
        var semanticVerdict: Bool? = nil
        if deterministicDecision == .passed {
            semanticVerdict = await judge.judge(
                intent: intent.intent,
                op: intent.op,
                result: opResult
            )
        }

        // 4. Compose final decision.
        //    - daemon "failed" → .failed (rollback trigger)
        //    - daemon "indeterminate" → .indeterminate (no rollback)
        //    - daemon "passed" + LLM says yes / nil → .passed
        //    - daemon "passed" + LLM says no → .failed (semantic veto)
        let finalDecision: PostOpDecision
        var finalFailures = failures
        if deterministicDecision == .failed {
            finalDecision = .failed
        } else if deterministicDecision == .indeterminate {
            finalDecision = .indeterminate
        } else {
            // Deterministic passed.
            if let v = semanticVerdict {
                if v {
                    finalDecision = .passed
                } else {
                    finalDecision = .failed
                    finalFailures.append(
                        "semantic judge: intent not achieved"
                    )
                }
            } else {
                finalDecision = .passed
            }
        }

        return PostOpResult(
            decision: finalDecision,
            failures: finalFailures,
            ercSummary: ercSummary,
            drcSummary: drcSummary,
            semanticVerdict: semanticVerdict
        )
    }

    // MARK: - Helpers

    /// Convert an Any (from JSON deserialization) to [String: AnyCodable].
    static func toCodable(_ value: Any?) -> [String: AnyCodable]? {
        guard let dict = value as? [String: Any] else { return nil }
        return dict.mapValues { AnyCodable($0) }
    }
}

#endif // os(macOS)
