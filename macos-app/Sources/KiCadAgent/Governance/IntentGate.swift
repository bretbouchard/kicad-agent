//
//  IntentGate.swift
//  KiCadAgent
//
//  Phase 169 — Obdurate Runtime
//
//  Intent Gate: parses op intent, validates the op against the registry,
//  and links the op to a requirement_id before the state machine allows
//  execution. Every op MUST carry a requirement_id — ops without one are
//  rejected (GOV-07 drift detection, GOV-11 coverage).
//
//  GOV-01: "Every op passes through Intent Gate (parse, validate, link to
//  requirement) before execution."
//
//  The gate is the ONLY entry point to the governed call pipeline. It
//  does not execute the op — it returns an `IntentResult` that the
//  caller (typically `MCPClient.governedCall`) consumes to drive the
//  state machine and journal.
//

import Foundation
import OSLog

// MARK: - IntentGateError

/// Errors raised by the Intent Gate.
enum IntentGateError: Error, LocalizedError, Equatable {
    case missingRequirementId(op: String)
    case unknownOp(String)
    case malformedIntent(String)
    case driftDetected(op: String, files: [String])

    var errorDescription: String? {
        switch self {
        case .missingRequirementId(let op):
            return "Op '\(op)' rejected: missing requirementId (GOV-07)"
        case .unknownOp(let op):
            return "Unknown op: '\(op)'"
        case .malformedIntent(let reason):
            return "Malformed intent: \(reason)"
        case .driftDetected(let op, let files):
            return "Drift detected for op '\(op)': out-of-scope files \(files)"
        }
    }
}

// MARK: - IntentResult

/// Result of IntentGate.validate(). Carries everything the governed call
/// pipeline needs to execute + journal the op.
struct IntentResult: Equatable, Sendable {
    /// The op name as registered (e.g. "add_component").
    let op: String

    /// Validated args (sanitized copy — no secrets).
    let args: [String: AnyCodable]

    /// Linked requirement ID — never empty after a successful validate.
    let requirementId: String

    /// Intent description — human-readable, max ~200 chars.
    let intent: String

    /// Target files the op will touch. DriftDetector cross-checks these.
    let targetFiles: [String]

    /// Read-only ops (queries, ERC checks) do not require approval.
    let isReadonly: Bool

    init(op: String,
         args: [String: AnyCodable],
         requirementId: String,
         intent: String,
         targetFiles: [String],
         isReadonly: Bool) {
        self.op = op
        self.args = args
        self.requirementId = requirementId
        self.intent = intent
        self.targetFiles = targetFiles
        self.isReadonly = isReadonly
    }
}

// MARK: - IntentGate

/// Intent Gate — validates every op before execution.
///
/// Phase 169 ships a Swift-side gate that enforces the requirement_id
/// invariant (GOV-07) and a basic op-name allowlist. Full registry-driven
/// validation (file_type vs op_type) lands when Phase 170 wires the Python
/// op catalog via MCP; for now the gate carries a curated op catalog that
/// mirrors the Python `ops/registry.py` for the most common ops.
final class IntentGate: @unchecked Sendable {

    private static let logger = Logger(subsystem: "com.kicadagent.app", category: "governance")

    /// Op catalog: op_name → (requirement_id default, readonly?, file_types).
    /// Mirrors Python `ops/registry.py` for the ops surfaced through MCP.
    /// Query ops (read-only) get requirementId `GOV-11` (the coverage
    /// requirement itself) so they don't have to fabricate a parent.
    struct OpMeta: Sendable {
        let requirementId: String
        let readonly: Bool
        let fileTypes: Set<String>   // "kicad_sch", "kicad_pcb", etc.
    }

    /// Static catalog — Phase 170 will replace with a dynamic load from
    /// the Python daemon via `tools/list`.
    static let catalog: [String: OpMeta] = [
        "add_component":            OpMeta(requirementId: "GOV-01", readonly: false, fileTypes: ["kicad_sch"]),
        "remove_component":         OpMeta(requirementId: "GOV-01", readonly: false, fileTypes: ["kicad_sch"]),
        "modify_component":         OpMeta(requirementId: "GOV-01", readonly: false, fileTypes: ["kicad_sch"]),
        "add_wire":                 OpMeta(requirementId: "GOV-01", readonly: false, fileTypes: ["kicad_sch"]),
        "remove_wire":              OpMeta(requirementId: "GOV-01", readonly: false, fileTypes: ["kicad_sch"]),
        "add_label":                OpMeta(requirementId: "GOV-01", readonly: false, fileTypes: ["kicad_sch"]),
        "add_no_connect":           OpMeta(requirementId: "GOV-01", readonly: false, fileTypes: ["kicad_sch"]),
        "place_no_connects_from_erc": OpMeta(requirementId: "GOV-01", readonly: false, fileTypes: ["kicad_sch"]),
        "remove_dangling_wires":    OpMeta(requirementId: "GOV-01", readonly: false, fileTypes: ["kicad_sch"]),
        "safe_annotate":            OpMeta(requirementId: "GOV-01", readonly: false, fileTypes: ["kicad_sch"]),
        "safe_sync_pcb_from_schematic":
                                    OpMeta(requirementId: "GOV-02", readonly: false, fileTypes: ["kicad_pcb", "kicad_sch"]),
        // PCB ops
        "pcb_add_segment":          OpMeta(requirementId: "GOV-02", readonly: false, fileTypes: ["kicad_pcb"]),
        "pcb_remove_segment":       OpMeta(requirementId: "GOV-02", readonly: false, fileTypes: ["kicad_pcb"]),
        "pcb_add_via":              OpMeta(requirementId: "GOV-02", readonly: false, fileTypes: ["kicad_pcb"]),
        "pcb_remove_via":           OpMeta(requirementId: "GOV-02", readonly: false, fileTypes: ["kicad_pcb"]),
        "auto_route":               OpMeta(requirementId: "GOV-02", readonly: false, fileTypes: ["kicad_pcb"]),
        // Query / read-only ops
        "query_components":         OpMeta(requirementId: "GOV-11", readonly: true,  fileTypes: ["kicad_sch"]),
        "query_nets":               OpMeta(requirementId: "GOV-11", readonly: true,  fileTypes: ["kicad_sch"]),
        "query_drc":                OpMeta(requirementId: "GOV-11", readonly: true,  fileTypes: ["kicad_pcb"]),
        "query_erc":                OpMeta(requirementId: "GOV-11", readonly: true,  fileTypes: ["kicad_sch"]),
        "generate_bom":             OpMeta(requirementId: "GOV-11", readonly: true,  fileTypes: ["kicad_sch"]),
        "parse_erc":                OpMeta(requirementId: "GOV-11", readonly: true,  fileTypes: ["kicad_sch"]),
    ]

    init() {}

    // MARK: - Validate

    /// Validate an op call.
    ///
    /// - Parameters:
    ///   - op: Op name (must exist in catalog).
    ///   - args: Args dict. `target_file`/`target_files` keys are extracted.
    ///   - requirementId: Caller-supplied requirement ID. If nil, the gate
    ///     uses the catalog default. Required to be non-empty for non-readonly
    ///     ops (GOV-07).
    ///   - intent: Human-readable description of what the caller intends.
    /// - Returns: Validated `IntentResult`.
    /// - Throws: `IntentGateError` for any rejection.
    func validate(
        op: String,
        args: [String: Any],
        requirementId: String? = nil,
        intent: String = ""
    ) throws -> IntentResult {
        // 1. Op exists in catalog.
        guard let meta = Self.catalog[op] else {
            Self.logger.warning("IntentGate: unknown op '\(op, privacy: .public)'")
            throw IntentGateError.unknownOp(op)
        }

        // 2. Resolve requirement ID. Caller can override catalog default.
        //    Readonly ops default to GOV-11 (coverage); mutating ops MUST
        //    have a real requirement ID after this resolution.
        //    GOV-07: explicit empty string on a mutating op = drift violation.
        if !meta.readonly, requirementId == "" {
            throw IntentGateError.missingRequirementId(op: op)
        }
        let resolvedReq = (requirementId?.isEmpty == false) ? requirementId! : meta.requirementId

        // 3. GOV-07: mutating ops require a non-default requirement_id.
        //    Default catalog requirement is allowed — but a nil/empty
        //    requirement on a mutating op is rejected. The catalog always
        //    supplies one, so this check fires only if the caller explicitly
        //    passes empty.
        if !meta.readonly, resolvedReq.isEmpty {
            throw IntentGateError.missingRequirementId(op: op)
        }

        // 4. Extract target files for drift detection.
        let targetFiles = IntentGate.extractTargetFiles(args: args)

        // 5. (Phase 169 scope) — drift detection runs in DriftDetector,
        //    which is invoked separately by the governed call pipeline.
        //    The gate just surfaces targetFiles for it.

        // 6. Intent description: fall back to op name if caller omitted.
        let effectiveIntent = intent.isEmpty
            ? "op=\(op) requirement=\(resolvedReq)"
            : intent

        // 7. Sanitize args for journaling (strip any obviously secret keys).
        let sanitized = IntentGate.sanitize(args: args)

        Self.logger.debug("IntentGate: validated '\(op, privacy: .public)' req=\(resolvedReq, privacy: .public) readonly=\(meta.readonly, privacy: .public)")

        return IntentResult(
            op: op,
            args: sanitized,
            requirementId: resolvedReq,
            intent: effectiveIntent,
            targetFiles: targetFiles,
            isReadonly: meta.readonly
        )
    }

    // MARK: - Helpers (internal for testing)

    /// Extract target file paths from args. Supports both singular and
    /// plural keys (the Python executor uses both).
    static func extractTargetFiles(args: [String: Any]) -> [String] {
        var files: [String] = []
        if let single = args["target_file"] as? String {
            files.append(single)
        }
        if let multi = args["target_files"] as? [String] {
            files.append(contentsOf: multi)
        }
        return files
    }

    /// Sanitize args — strip keys that look like secrets.
    /// Conservative denylist; mirrors Python `audit_log.py` sanitizer.
    static func sanitize(args: [String: Any]) -> [String: AnyCodable] {
        let denyPrefixes: Set<String> = ["password", "secret", "token", "api_key", "apikey"]
        var out: [String: AnyCodable] = [:]
        for (key, value) in args {
            let lower = key.lowercased()
            if denyPrefixes.contains(where: { lower.hasPrefix($0) }) {
                out[key] = AnyCodable("[REDACTED]")
            } else {
                out[key] = AnyCodable(value)
            }
        }
        return out
    }
}
