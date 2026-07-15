#if os(macOS)
//
//  StdioWatchdog.swift
//  Volta
//
//  Phase 167 — Stdio MCP Client
//
//  Per-request watchdog for the stdio MCP transport. Complements
//  ProcessManager's process-level watchdog (Phase 162) with a
//  Swift-side observer that tracks the last daemon stdout timestamp
//  and fires a kill + audit-log when silence exceeds the deadline.
//
//  Two layers of protection against PITFALL 2 (stdio buffering deadlock):
//
//  Layer 1: ProcessManager.watchdogTask (Phase 162)
//      - Restarts on every stdout line via resetWatchdog()
//      - Fires after 30s of total silence (no heartbeats, no responses)
//      - Sends SIGKILL, records crash for loop detection
//
//  Layer 2: StdioWatchdog (Phase 167, this file)
//      - Tracks per-request pending state
//      - Emits structured audit-log entries BEFORE kill (DAEM-02)
//      - Checks every 5 seconds (cheap, no syscalls)
//      - Coordinated with MCPClient's per-request 30s timeout
//
//  Why a separate watchdog when ProcessManager already has one?
//  - ProcessManager's watchdog is process-lifecycle (one deadline).
//  - StdioWatchdog is RPC-aware: it knows a request is pending.
//  - Audit log entries from StdioWatchdog include request metadata
//    (method, params size, elapsed ms) for post-incident forensics.
//

import Foundation
import OSLog

// MARK: - StdioWatchdog

/// RPC-aware watchdog for the stdio MCP transport.
///
/// Lifecycle:
/// 1. ProcessManager.spawn() constructs a StdioWatchdog.
/// 2. MCPClient.callRaw() calls trackRequestStart(id:method:) before write.
/// 3. DaemonMessenger.ingest(line:) routes response → calls trackRequestEnd(id:).
/// 4. Daemon heartbeat → calls resetActivity().
/// 5. Background task polls every `checkInterval` (5s). If any request is
///    pending past `silenceTimeout` (30s), audit-log + invoke `onTimeout`.
/// 6. ProcessManager.shutdown() calls stop().
@MainActor
final class StdioWatchdog {
    /// How long without stdout activity before declaring deadlock.
    /// Default per PITFALL 2 spec. Configurable per-instance for tests.
    static let defaultSilenceTimeout: Duration = .seconds(30)

    /// Polling interval for the background checker.
    static let defaultCheckInterval: Duration = .seconds(5)

    /// Per-instance silence deadline. Defaults to `defaultSilenceTimeout`.
    /// Tests tighten this to .milliseconds(50) for fast CI.
    var silenceTimeout: Duration = StdioWatchdog.defaultSilenceTimeout

    /// Per-instance check interval. Defaults to `defaultCheckInterval`.
    var checkInterval: Duration = StdioWatchdog.defaultCheckInterval

    /// Per-request metadata. Used for audit logging on kill.
    struct PendingRequest: Sendable {
        let id: String
        let method: String
        let startTime: ContinuousClock.Instant
        let paramsByteSize: Int
    }

    /// Currently-pending requests keyed by JSON-RPC id.
    private(set) var pendingRequests: [String: PendingRequest] = [:]

    /// Timestamp of last daemon stdout activity (line or heartbeat).
    private(set) var lastActivityAt: ContinuousClock.Instant = .now

    /// Background poller task. Nil when stopped.
    private(set) var pollerTask: Task<Void, Never>?

    /// Invoked when a request exceeds the silence deadline. The closure
    /// is responsible for killing the daemon (typically SIGKILL via ProcessManager).
    /// Passes the offending request id and elapsed ms for logging.
    var onTimeout: (@MainActor (PendingRequest, Duration) -> Void)?

    /// Optional audit-log sink. Defaults to OSLog; tests can inject a
    /// capturing sink to verify kill entries are emitted before kill.
    var auditSink: ((String, [String: Any]) -> Void)?

    // MARK: - Lifecycle

    init() {
        Logger.appShell.info("StdioWatchdog initialized (silence=\(Self.defaultSilenceTimeout.components.seconds)s check=\(Self.defaultCheckInterval.components.seconds)s)")
    }

    /// Start the background poller. Idempotent.
    func start() {
        if pollerTask != nil { return }
        pollerTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: self?.checkInterval ?? Self.defaultCheckInterval)
                guard !Task.isCancelled else { return }
                self?.checkTimeouts()
            }
        }
    }

    /// Stop the background poller. Clears pending requests.
    func stop() {
        pollerTask?.cancel()
        pollerTask = nil
        pendingRequests.removeAll()
    }

    // MARK: - Activity tracking

    /// Record that a request was just sent to the daemon. Starts the
    /// silence timer for this id.
    func trackRequestStart(id: String, method: String, paramsByteSize: Int = 0) {
        let req = PendingRequest(
            id: id,
            method: method,
            startTime: .now,
            paramsByteSize: paramsByteSize
        )
        pendingRequests[id] = req
        lastActivityAt = .now
    }

    /// Record that a response for the given id arrived. Clears the
    /// silence timer for that id.
    func trackRequestEnd(id: String) {
        pendingRequests.removeValue(forKey: id)
        lastActivityAt = .now
    }

    /// Reset the activity timestamp (heartbeat, any stdout line).
    func resetActivity() {
        lastActivityAt = .now
    }

    // MARK: - Timeout check

    /// Public for tests — single iteration of the timeout check.
    func checkTimeouts() {
        guard !pendingRequests.isEmpty else { return }
        let now: ContinuousClock.Instant = .now
        let deadline = lastActivityAt.advanced(by: silenceTimeout)
        guard now > deadline else { return }

        // Find the oldest pending request for the audit entry.
        // (All pending requests are past the deadline by definition since
        // lastActivityAt is global, but we pick the oldest for logging.)
        guard let oldest = pendingRequests.values.min(by: { $0.startTime < $1.startTime }) else {
            return
        }

        let elapsed = now - oldest.startTime
        let elapsedMs = Int(elapsed.components.seconds) * 1000
            + Int(elapsed.components.attoseconds / 1_000_000_000_000_000)

        // DAEM-02 augmentation: emit audit-log entry BEFORE kill.
        // This entry survives the kill and lets the on-call engineer see
        // what request hung, for how long, and what method was called.
        let auditEntry: [String: Any] = [
            "event": "stdio_watchdog_timeout",
            "request_id": oldest.id,
            "method": oldest.method,
            "elapsed_ms": elapsedMs,
            "pending_count": pendingRequests.count,
            "params_byte_size": oldest.paramsByteSize,
            "pid": ProcessInfo.processInfo.processIdentifier,
        ]
        auditSink?("stdio_watchdog_timeout", auditEntry)
        Logger.appShell.error(
            "StdioWatchdog: KILL — request id=\(oldest.id, privacy: .public) method=\(oldest.method, privacy: .public) hung \(elapsedMs)ms; \(self.pendingRequests.count) pending"
        )

        onTimeout?(oldest, elapsed)
    }

    // MARK: - Diagnostics

    /// Number of currently-pending requests.
    var pendingCount: Int { pendingRequests.count }

    /// Elapsed since last daemon stdout activity.
    var silenceElapsed: Duration {
        .now - lastActivityAt
    }
}

#endif // os(macOS)
