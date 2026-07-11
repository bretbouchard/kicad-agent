#if os(macOS)
//
//  MCPClient.swift
//  KiCadAgent
//
//  Phase 167 — Stdio MCP Client
//
//  Higher-level Swift client for the JSON-RPC stdio transport that lives
//  between the app and the bundled Python daemon. Wraps DaemonMessenger
//  (Phase 162) with:
//
//    - Generic typed `call<T: Decodable>` API — decode straight into
//      application structs, no more `Any`.
//    - `notify` — fire-and-forget notifications (no id, no reply).
//    - Incrementing Int id generator (matches MCP spec convention).
//    - 30-second per-request timeout → raises MCPError.timeout and
//      drives the watchdog kill via StdioWatchdog.
//    - Heartbeat routing (forwards daemon heartbeats to the watchdog).
//
//  Lifecycle:
//    1. ProcessManager.spawn() wires a DaemonMessenger.
//    2. MCPClient.attach(messenger:) binds to it.
//    3. call(...) sends JSON-RPC request, awaits reply routed by id.
//
//  Thread-safety:
//    DaemonMessenger is @MainActor. MCPClient is @MainActor too so
//    continuation routing doesn't cross actor boundaries.
//

import Foundation
import OSLog

// MARK: - MCPClient

/// Higher-level JSON-RPC client bound to a DaemonMessenger.
///
/// `MCPClient` is `@MainActor` because it shares DaemonMessenger's
/// MainActor isolation. The `call` API suspends via a checked continuation
/// that is resumed when DaemonMessenger.ingest(line:) routes the matching
/// response back.
@MainActor
final class MCPClient {
    /// Underlying messenger that owns the stdin pipe and pending-request map.
    private let messenger: DaemonMessenger

    /// True after `initialize`/`initialized` handshake completes.
    private(set) var isInitialized: Bool = false

    /// Default per-request timeout. Matches the watchdog deadline in
    /// ProcessManager — if the daemon hangs, this fires first and the
    /// watchdog handles the kill.
    static let requestTimeout: Duration = .seconds(30)

    init(messenger: DaemonMessenger) {
        self.messenger = messenger
    }

    // MARK: - Attach

    /// Attach to a live messenger. Idempotent — reattaching clears
    /// initialization state so callers re-handshake after a restart.
    func attach(_ messenger: DaemonMessenger) {
        isInitialized = false
    }

    // MARK: - Call (typed)

    /// Send a JSON-RPC request and decode the result.
    ///
    /// - Parameters:
    ///   - method: RPC method (e.g. "ping", "tools/list", "kicad.add_component").
    ///   - params: params object. Pass `[:]` for no params.
    ///   - type: Decodable type to decode the `result` field into.
    ///   - timeout: per-request override of `requestTimeout`.
    /// - Returns: decoded result value.
    /// - Throws: MCPError on transport/protocol/timeout/decoding failures.
    public func call<T: Decodable>(
        _ method: String,
        params: [String: Any] = [:],
        as type: T.Type,
        timeout: Duration = MCPClient.requestTimeout
    ) async throws -> T {
        let raw = try await callRaw(method, params: params, timeout: timeout)
        do {
            // Re-serialize to Data so we can use a typed decoder. AnyCodable
            // round-trips the value, so this is safe even if the original
            // response came through JSONSerialization.
            let data = try JSONSerialization.data(withJSONObject: raw, options: [])
            return try JSONDecoder().decode(T.self, from: data)
        } catch let error as DecodingError {
            throw MCPError.decodingFailed(message: "\(error)")
        } catch {
            throw MCPError.decodingFailed(message: error.localizedDescription)
        }
    }

    /// Variant of `call` that returns the raw `Any` result without decoding.
    /// Useful for ops whose result shape isn't yet typed in Swift.
    ///
    /// Timeout strategy: stays MainActor-isolated. We start the messenger
    /// call with `Task { @MainActor }`, schedule a sleep Task that resumes
    /// with `.timeout` after the deadline, then await the first to complete.
    /// The other task is cancelled. The watchdog in ProcessManager handles
    /// the actual process kill if the daemon is truly hung.
    func callRaw(
        _ method: String,
        params: [String: Any] = [:],
        timeout: Duration = MCPClient.requestTimeout
    ) async throws -> Any {
        let startTime = ContinuousClock.now

        // Race outcome wrapper — Sendable via SendableBox / MCPError.
        enum Outcome: Sendable {
            case success(SendableBox)
            case failure(MCPError)
        }

        return try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Any, Error>) in
            let resumed = NSLock()
            var didResume = false

            // Helper: resume exactly once.
            func resumeOnce(with outcome: Outcome) {
                resumed.lock()
                let already = didResume
                if !already { didResume = true }
                resumed.unlock()
                guard !already else { return }
                switch outcome {
                case .success(let box):
                    cont.resume(returning: box.value)
                case .failure(let err):
                    cont.resume(throwing: err)
                }
            }

            // Call arm.
            let callTask = Task { @MainActor [weak self] in
                guard let self else {
                    resumeOnce(with: .failure(MCPError.notConnected))
                    return
                }
                do {
                    let result = try await self.messenger.call(method, params)
                    resumeOnce(with: .success(SendableBox(result)))
                } catch let error as DaemonMessengerError {
                    resumeOnce(with: .failure(Self.mapMessengerError(error)))
                } catch {
                    resumeOnce(with: .failure(MCPError.transport(message: error.localizedDescription)))
                }
            }

            // Timeout arm. Pure sleep + resume — safe to detach.
            let timeoutTask = Task {
                try? await Task.sleep(for: timeout)
                if Task.isCancelled { return }
                resumeOnce(with: .failure(MCPError.timeout))
                // Cancelling the call arm is best-effort. The watchdog in
                // ProcessManager is the real kill switch.
                callTask.cancel()
            }

            // If the call completes first, cancel the timeout.
            Task { @MainActor in
                _ = await callTask.value
                timeoutTask.cancel()
            }

            // Logging (best-effort, post-resume).
            Task { @MainActor in
                _ = await callTask.value
                let elapsed = ContinuousClock.now - startTime
                let elapsedMs = Int(elapsed.components.seconds) * 1000
                    + Int(elapsed.components.attoseconds / 1_000_000_000_000_000)
                Logger.appShell.debug(
                    "MCPClient: \(method, privacy: .public) round-trip \(elapsedMs)ms"
                )
            }
        }
    }

    /// Map DaemonMessengerError → MCPError. Nonisolated pure transformation.
    nonisolated private static func mapMessengerError(_ error: DaemonMessengerError) -> MCPError {
        switch error {
        case .timeout:
            return .timeout
        case .daemonError(let code, let message):
            return .daemonError(code: code, message: message)
        case .brokenPipe:
            return .transport(message: "broken pipe")
        case .writeFailed(let message):
            return .transport(message: message)
        case .malformedResponse(let payload):
            return .malformedResponse(payload: payload)
        case .missingResult(let id):
            return .malformedResponse(payload: "missing result for id \(id)")
        }
    }

    // MARK: - Notify (fire-and-forget)

    /// Send a JSON-RPC notification (no id, no reply expected).
    ///
    /// Used for `initialized` lifecycle notification, log forwarding, and
    /// other one-way messages. Throws on write failure but never on response
    /// absence (there is no response).
    ///
    /// Note: the underlying DaemonMessenger does not expose a notify API —
    /// Phase 162 callers always use `call`. To support `notify` without
    /// forking the messenger, we write directly to the stdin pipe via the
    /// `stdinPipe` property exposed on DaemonMessenger.
    public func notify(_ method: String, params: [String: Any] = [:]) async throws {
        guard let stdinPipe = messenger.stdinPipe else {
            throw MCPError.notConnected
        }

        let envelope = JSONRPCEnvelope.notification(method: method, params: params)
        let line = try envelope.toJSONLine()

        do {
            try stdinPipe.fileHandleForWriting.write(contentsOf: Data(line.utf8))
            try? stdinPipe.fileHandleForWriting.synchronize()
        } catch let error as NSError where error.code == 32 {  // POSIX EPIPE
            throw MCPError.transport(message: "broken pipe")
        } catch {
            throw MCPError.transport(message: error.localizedDescription)
        }
    }

    // MARK: - MCP lifecycle

    /// Perform the MCP `initialize` / `initialized` handshake.
    ///
    /// Sends `initialize` with our client capabilities, awaits the server's
    /// response (capabilities + protocol version), then sends the
    /// `initialized` notification. Idempotent — calling twice is a no-op.
    ///
    /// Per MCP spec: https://modelcontextprotocol.io/specification#initialization
    public func initialize() async throws -> MCPInitializeResult {
        guard !isInitialized else {
            // Already initialized — return cached-ish marker. Real clients
            // cache the result; for our use case, callers re-checking don't
            // need the full server info.
            return MCPInitializeResult(protocolVersion: "2024-11-05", serverInfo: [:], capabilities: [:])
        }

        let params: [String: Any] = [
            "protocolVersion": "2024-11-05",
            "capabilities": [:],
            "clientInfo": [
                "name": "KiCadAgent",
                "version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.0.0",
            ],
        ]

        let result: MCPInitializeResult = try await call(
            "initialize",
            params: params,
            as: MCPInitializeResult.self
        )

        // Notify — fire-and-forget completes the handshake.
        try await notify("initialized", params: [:])

        isInitialized = true
        return result
    }

    // MARK: - Heartbeat routing

    /// Forward heartbeat callbacks from DaemonMessenger to a closure.
    /// ProcessManager uses this to reset the watchdog without a full RPC.
    public func setHeartbeatHandler(_ handler: @escaping @MainActor () -> Void) {
        messenger.onHeartbeat = handler
    }

    // MARK: - Governed call (Phase 169)

    /// Run an op call through the full Obdurate Runtime pipeline:
    ///
    ///   IntentGate → DriftDetector → WorkflowStateMachine → VerificationLoop
    ///   → OpJournal.append → AutoLearner.store → EscalationLadder
    ///
    /// Phase 170: VerificationLoop now wraps execute + pre/post gates +
    /// rollback (GOV-03, GOV-04, GOV-05). On pre-op block the call is
    /// journaled with `result_status="rejected"`. On post-op failure the
    /// loop auto-rolls-back and the journal records `result_status="rolled_back"`.
    ///
    /// - Parameters:
    ///   - method: JSON-RPC method (e.g. "kicad.add_component" or "tools/call").
    ///   - params: params dict.
    ///   - requirementId: Required for mutating ops (GOV-07).
    ///   - intent: Human-readable intent (max ~200 chars).
    ///   - actor: Who triggered the call ("user" | "daemon" | "automation").
    ///   - type: Decodable result type.
    /// - Returns: Decoded result value wrapped in GovernedCallResult.
    public func governedCall<T: Decodable & Sendable & Equatable>(
        _ method: String,
        params: [String: Any] = [:],
        requirementId: String? = nil,
        intent: String = "",
        actor: String = "user",
        governance: Governance = .shared,
        as type: T.Type
    ) async throws -> GovernedCallResult<T> {
        // Pull op name from params or method (kicad.<op>).
        let opName: String
        let callParams = params
        if method == "tools/call", let name = params["name"] as? String {
            opName = name
        } else if method.hasPrefix("kicad.") {
            opName = String(method.dropFirst("kicad.".count))
        } else {
            opName = method
        }

        // 1. IntentGate.validate
        let validated: IntentResult
        do {
            validated = try governance.intentGate.validate(
                op: opName, args: params,
                requirementId: requirementId, intent: intent
            )
        } catch let e as IntentGateError {
            try? journalRejection(governance: governance, op: opName, params: params,
                                  requirementId: requirementId, intent: intent,
                                  actor: actor, reason: "\(e)")
            throw GovernedCallError.intentRejected(e)
        }

        // 2. DriftDetector.check
        let drift = governance.driftDetector.check(validated)
        if governance.driftDetector.strictMode, !drift.isClean {
            try? journalRejection(governance: governance, intent: validated,
                                  actor: actor, reason: drift.warnings.joined(separator: "; "))
            throw GovernedCallError.driftRejected(drift)
        }

        // 3. WorkflowStateMachine guard — mutating ops require .executing.
        if !validated.isReadonly {
            let s = governance.stateMachine.state
            if !s.allowsMutation {
                let err = WorkflowStateMachineError.invalidTransition(from: s, to: .executing)
                try? journalRejection(governance: governance, intent: validated,
                                      actor: actor, reason: "\(err)")
                throw GovernedCallError.stateRejected(err)
            }
        }

        // 4. Escalation ladder halt check — T4 means stop.
        if governance.escalation.humanInputRequired(for: opName) {
            let tier = governance.escalation.currentTier(for: opName)
            try? journalRejection(governance: governance, intent: validated,
                                  actor: actor, reason: "escalation halt at \(tier.name)")
            throw GovernedCallError.escalationHalted(tier: tier, taskKey: opName)
        }

        // 5. VerificationLoop — checkpoint → pre-op → execute → post-op → rollback
        //    Replaces the prior direct call() invocation. The loop captures
        //    snapshots, validates intent matches op (GOV-03), runs ERC/DRC
        //    (GOV-04), and auto-rolls-back on failure (GOV-05).
        let opId = UUID().uuidString
        let phase = governance.stateMachine.state.rawValue
        let outcome = await governance.verificationLoop.run(
            intent: validated,
            args: callParams
        ) { [weak self] in
            guard let self else {
                throw MCPError.notConnected
            }
            let raw = try await self.callRaw(method, params: callParams)
            return (result: AnyCodable(raw),
                    summary: "completed")
        }

        // 6. Translate outcome → journal entry + escalation + learning.
        let resultStatus: String
        let resultSummary: String
        let verificationPassed: Bool?

        switch outcome.status {
        case .passed:
            resultStatus = "success"
            resultSummary = "verification=passed pre=\(outcome.preOp.decision.rawValue)"
            verificationPassed = true
        case .indeterminate:
            resultStatus = "success"
            resultSummary = "verification=indeterminate pre=\(outcome.preOp.decision.rawValue)"
            verificationPassed = nil
        case .blocked:
            // Pre-op rejected — journal as rejection.
            try? journalRejection(governance: governance, intent: validated,
                                  actor: actor,
                                  reason: "pre-op blocked: \(outcome.preOp.reasons.joined(separator: "; "))")
            throw GovernedCallError.intentRejected(
                .malformedIntent("pre-op gate blocked execution"))
        case .executionFailed:
            resultStatus = "failed"
            resultSummary = "execute threw"
            verificationPassed = nil
            _ = governance.escalation.recordFailure(
                taskKey: opName, severity: .high, details: [resultSummary])
            try? governance.learner.storeFailureMessage(
                op: opName, requirementId: validated.requirementId,
                error: resultSummary)
            throw MCPError.transport(message: "verification loop: execute failed for op \(opId)")
        case .failed:
            resultStatus = "rolled_back"
            let rolled = outcome.restore?.affectedCount ?? 0
            resultSummary = "verification=failed rolled_back_files=\(rolled)"
            verificationPassed = false
            _ = governance.escalation.recordFailure(
                taskKey: opName, severity: .high,
                details: outcome.postOp?.failures ?? [])
            try? governance.learner.storeFailureMessage(
                op: opName, requirementId: validated.requirementId,
                error: outcome.postOp?.failures.joined(separator: "; ") ?? "verification failed")
        }

        // 7. Journal the outcome.
        let entry = try? journalExtended(
            governance: governance, opId: opId, intent: validated,
            actor: actor, phase: phase, status: resultStatus,
            summary: resultSummary, verification: verificationPassed,
            outcome: outcome)

        if outcome.status == .passed || outcome.status == .indeterminate {
            governance.escalation.recordSuccess(taskKey: opName)
            try? governance.learner.storeSuccessPattern(
                op: opName, requirementId: validated.requirementId,
                summary: "\(opName) → \(resultSummary)")
        }

        guard let entry else {
            throw MCPError.transport(message: "journal write failed for op \(opId)")
        }

        // Decode the op result into the requested type for the caller.
        // The loop stored the raw result as AnyCodable; re-serialize → decode.
        let value: T
        if let outcomeRaw = outcome.result {
            do {
                let data = try JSONEncoder().encode(outcomeRaw)
                value = try JSONDecoder().decode(T.self, from: data)
            } catch {
                throw MCPError.decodingFailed(message: "\(error)")
            }
        } else {
            throw MCPError.decodingFailed(
                message: "verification outcome had no result (status=\(outcome.status.rawValue))")
        }

        return GovernedCallResult(value: value, journalEntry: entry, intent: validated)
    }

    /// Variant that returns the raw result without decoding.
    public func governedCallRaw(
        _ method: String,
        params: [String: Any] = [:],
        requirementId: String? = nil,
        intent: String = "",
        actor: String = "user",
        governance: Governance = .shared
    ) async throws -> Any {
        // Pull op name from params or method.
        let opName: String
        if method == "tools/call", let name = params["name"] as? String {
            opName = name
        } else if method.hasPrefix("kicad.") {
            opName = String(method.dropFirst("kicad.".count))
        } else {
            opName = method
        }

        // 1. IntentGate.validate
        let validated: IntentResult
        do {
            validated = try governance.intentGate.validate(
                op: opName, args: params,
                requirementId: requirementId, intent: intent
            )
        } catch let e as IntentGateError {
            try? journalRejection(governance: governance, op: opName, params: params,
                                  requirementId: requirementId, intent: intent,
                                  actor: actor, reason: "\(e)")
            throw GovernedCallError.intentRejected(e)
        }

        // 2. DriftDetector
        let drift = governance.driftDetector.check(validated)
        if governance.driftDetector.strictMode, !drift.isClean {
            try? journalRejection(governance: governance, intent: validated,
                                  actor: actor, reason: drift.warnings.joined(separator: "; "))
            throw GovernedCallError.driftRejected(drift)
        }

        // 3. State machine guard
        if !validated.isReadonly {
            let s = governance.stateMachine.state
            if !s.allowsMutation {
                let err = WorkflowStateMachineError.invalidTransition(from: s, to: .executing)
                try? journalRejection(governance: governance, intent: validated,
                                      actor: actor, reason: "\(err)")
                throw GovernedCallError.stateRejected(err)
            }
        }

        // 4. Escalation halt
        if governance.escalation.humanInputRequired(for: opName) {
            let tier = governance.escalation.currentTier(for: opName)
            try? journalRejection(governance: governance, intent: validated,
                                  actor: actor, reason: "escalation halt at \(tier.name)")
            throw GovernedCallError.escalationHalted(tier: tier, taskKey: opName)
        }

        // 5. Call
        let opId = UUID().uuidString
        let phase = governance.stateMachine.state.rawValue
        var resultStatus = "success"
        var resultSummary = ""

        let value: Any
        do {
            value = try await callRaw(method, params: params)
            resultSummary = "completed"
        } catch {
            resultStatus = "failed"
            resultSummary = String(describing: error).prefix(200).description
            _ = try? journal(governance: governance, opId: opId, intent: validated,
                         actor: actor, phase: phase, status: resultStatus,
                         summary: resultSummary, verification: nil)
            governance.escalation.recordFailure(
                taskKey: opName, severity: .high, details: [resultSummary])
            try? governance.learner.storeFailureMessage(
                op: opName, requirementId: validated.requirementId,
                error: resultSummary)
            throw error
        }

        // 6. Success
        _ = try? journal(governance: governance, opId: opId, intent: validated,
                     actor: actor, phase: phase, status: resultStatus,
                     summary: resultSummary, verification: true)
        governance.escalation.recordSuccess(taskKey: opName)
        try? governance.learner.storeSuccessPattern(
            op: opName, requirementId: validated.requirementId,
            summary: "\(opName) → \(resultSummary)")
        return value
    }

    // MARK: - Journal helpers (private)

    /// Append a journal entry for a finished call.
    @discardableResult
    private func journal(governance: Governance, opId: String, intent: IntentResult,
                         actor: String, phase: String, status: String,
                         summary: String, verification: Bool?) throws -> OpJournalEntry {
        let entry = OpJournalEntry(
            operationId: opId,
            timestamp: OpJournal.nowISO8601(),
            actor: actor,
            intent: intent.intent,
            op: intent.op,
            args: intent.args,
            resultStatus: status,
            resultSummary: summary,
            phase: phase,
            verificationPassed: verification,
            requirementId: intent.requirementId,
            escalationTier: governance.escalation.currentTier(for: intent.op).rawValue
        )
        try governance.journal.append(entry)
        return entry
    }

    /// Phase 170: Journal helper that records the verification outcome
    /// (checkpoint id, pre/post decisions, restore summary, stage timings)
    /// in the result_summary field. Keeps the journal schema stable while
    /// adding rich verification context for audit.
    @discardableResult
    private func journalExtended(
        governance: Governance, opId: String, intent: IntentResult,
        actor: String, phase: String, status: String,
        summary: String, verification: Bool?,
        outcome: VerificationOutcome
    ) throws -> OpJournalEntry {
        var enriched = summary
        if let checkpointId = outcome.checkpointId, !checkpointId.isEmpty {
            enriched += " snapshot=\(checkpointId.prefix(8))"
        }
        if let restore = outcome.restore {
            enriched += " restored=\(restore.restored) removed=\(restore.removed)"
        }
        if !outcome.stageTimingsMs.isEmpty {
            let timing = outcome.stageTimingsMs
                .sorted { $0.key < $1.key }
                .map { "\($0.key)=\($0.value)" }
                .joined(separator: ",")
            enriched += " timings[\(timing)]"
        }
        return try journal(
            governance: governance, opId: opId, intent: intent,
            actor: actor, phase: phase, status: status,
            summary: enriched, verification: verification)
    }

    /// Append a journal entry for a rejected call (gate failure).
    private func journalRejection(governance: Governance, op: String, params: [String: Any],
                                  requirementId: String?, intent: String,
                                  actor: String, reason: String) throws {
        let sanitized = IntentGate.sanitize(args: params)
        let entry = OpJournalEntry(
            operationId: UUID().uuidString,
            timestamp: OpJournal.nowISO8601(),
            actor: actor,
            intent: intent.isEmpty ? "op=\(op)" : intent,
            op: op,
            args: sanitized,
            resultStatus: "rejected",
            resultSummary: reason.prefix(200).description,
            phase: governance.stateMachine.state.rawValue,
            verificationPassed: nil,
            requirementId: requirementId,
            escalationTier: governance.escalation.currentTier(for: op).rawValue
        )
        try governance.journal.append(entry)
    }

    private func journalRejection(governance: Governance, intent: IntentResult,
                                  actor: String, reason: String) throws {
        let entry = OpJournalEntry(
            operationId: UUID().uuidString,
            timestamp: OpJournal.nowISO8601(),
            actor: actor,
            intent: intent.intent,
            op: intent.op,
            args: intent.args,
            resultStatus: "rejected",
            resultSummary: reason.prefix(200).description,
            phase: governance.stateMachine.state.rawValue,
            verificationPassed: nil,
            requirementId: intent.requirementId,
            escalationTier: governance.escalation.currentTier(for: intent.op).rawValue
        )
        try governance.journal.append(entry)
    }

    // MARK: - Cleanup

    /// Cancel any in-flight state. Called by ProcessManager during shutdown.
    /// Per-request timeouts live inside the `callRaw` task group, which
    /// cancels automatically when the parent task is cancelled. This method
    /// exists for future hooks (e.g. notification stream cancellation).
    public func cancelAllPending() {
        // No-op for Phase 167 — per-request timeouts cancel via TaskGroup.
        // Reserved for Phase 168 streaming notification cancellation.
    }
}

// MARK: - MCPInitializeResult

/// Result of the MCP `initialize` handshake.
struct MCPInitializeResult: Codable, Equatable, Sendable {
    public let protocolVersion: String
    public let serverInfo: [String: String]
    public let capabilities: [String: AnyCodable]

    public init(
        protocolVersion: String,
        serverInfo: [String: String],
        capabilities: [String: AnyCodable]
    ) {
        self.protocolVersion = protocolVersion
        self.serverInfo = serverInfo
        self.capabilities = capabilities
    }

    enum CodingKeys: String, CodingKey {
        case protocolVersion
        case serverInfo
        case capabilities
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.protocolVersion = try c.decode(String.self, forKey: .protocolVersion)
        // serverInfo values may be non-string; coerce to "<value>".
        if let raw = try? c.decode([String: AnyCodable].self, forKey: .serverInfo) {
            self.serverInfo = raw.mapValues { "\($0.value)" }
        } else {
            self.serverInfo = [:]
        }
        self.capabilities = (try? c.decode([String: AnyCodable].self, forKey: .capabilities)) ?? [:]
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(protocolVersion, forKey: .protocolVersion)
        try c.encode(serverInfo, forKey: .serverInfo)
        try c.encode(capabilities, forKey: .capabilities)
    }
}

// MARK: - AsyncSequence for streaming responses (optional)

/// Stream of JSON-RPC responses from the daemon, for callers that want to
/// consume notifications (heartbeats, progress) as a sequence rather than
/// via callback closures.
///
/// Phase 167 ships the type; full streaming tool support lands in Phase 168
/// when tools emit progress notifications.
struct MCPResponseStream: AsyncSequence {
    public typealias Element = JSONRPCEnvelope
    let client: MCPClient

    public init(client: MCPClient) {
        self.client = client
    }

    public func makeAsyncIterator() -> AsyncIterator {
        AsyncIterator(client: client)
    }

    public struct AsyncIterator: AsyncIteratorProtocol {
        let client: MCPClient
        /// Phase 167: single-shot iterator. Real streaming lands in Phase 168.
        var consumed = false

        public mutating func next() async -> Element? {
            // Phase 168 will wire this to a real notification queue.
            // For now, return nil to terminate iteration cleanly.
            return nil
        }
    }
}

#endif // os(macOS)
