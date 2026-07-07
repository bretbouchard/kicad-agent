//
//  DaemonMessenger.swift
//  KiCadAgent
//
//  Phase 162 — Python Daemon Bundling
//
//  Minimal JSON-RPC 2.0 client over the daemon's stdin/stdout pipes.
//  Phase 167 will swap this for a full MCP client; the API surface
//  (`call(_:_:)`) is intentionally MCP-shaped so callers don't need to
//  change when we upgrade.
//
//  Hardening:
//  - JSON parsing is strict; malformed payloads throw `DaemonMessengerError.malformedResponse`.
//  - Each request gets a UUID; replies are routed by id via a `[String: CheckedContinuation]` map.
//  - Broken pipe / write failure throws and bubbles to ProcessManager,
//    which treats it as a crash.
//  - Heartbeat messages (id-less notifications from daemon → app) reset the
//    ProcessManager watchdog via `onHeartbeat`.
//

import Foundation
import OSLog

// MARK: - Errors

enum DaemonMessengerError: LocalizedError, Equatable {
    case malformedResponse(payload: String)
    case missingResult(id: String)
    case daemonError(code: Int, message: String)
    case brokenPipe
    case writeFailed(message: String)
    case timeout

    var errorDescription: String? {
        switch self {
        case .malformedResponse(let payload):
            return "Malformed daemon response: \(payload.prefix(200))"
        case .missingResult(let id):
            return "Daemon response missing result for id \(id)"
        case .daemonError(let code, let message):
            return "Daemon error [\(code)]: \(message)"
        case .brokenPipe:
            return "Daemon pipe closed (broken pipe)."
        case .writeFailed(let message):
            return "Failed to write to daemon stdin: \(message)"
        case .timeout:
            return "Daemon call timed out."
        }
    }
}

// MARK: - DaemonMessenger

/// JSON-RPC 2.0 client for the bundled Python daemon.
///
/// Lifecycle:
/// 1. `ProcessManager.spawn()` creates pipes; ProcessManager owns them.
/// 2. First stdout line constructs a `DaemonMessenger` and binds it.
/// 3. `ingest(line:)` is called by ProcessManager's readability handler
///    for every received line.
/// 4. `call(_:_:)` writes a request to stdin and awaits the matching reply.
@MainActor
final class DaemonMessenger {
    /// Pipe the messenger writes requests to. Set by ProcessManager.
    var stdinPipe: Pipe?

    /// Called whenever the daemon emits a heartbeat notification. Used by
    /// ProcessManager to reset the watchdog without a full RPC round-trip.
    var onHeartbeat: (@MainActor () -> Void)?

    /// Pending requests keyed by JSON-RPC id. Each awaiting `call`.
    /// The continuation payload is `SendableBox` (an @unchecked Sendable
    /// Any) because JSON-RPC results are heterogeneous and Swift 6
    /// refuses to send raw `Any` across actor boundaries.
    private var pending: [String: CheckedContinuation<SendableBox, Error>] = [:]

    /// Used so tests can construct a messenger without a real pipe. The
    /// first arg is intentionally unused — it exists to keep the API stable.
    init(stdoutLine: String = "") {
        // No-op. Real wire-up happens via `attach(stdinPipe:)`.
    }

    /// Attach to a stdin pipe owned by ProcessManager.
    func attach(stdinPipe: Pipe) {
        self.stdinPipe = stdinPipe
    }

    // MARK: - Ingest

    /// Route one stdout line. Called by ProcessManager.
    func ingest(line: String) {
        guard let data = line.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            Logger.appShell.error("DaemonMessenger: malformed line — \(line.prefix(200), privacy: .public)")
            return
        }

        // Heartbeat notification (no id, method=heartbeat).
        if json["id"] == nil, let method = json["method"] as? String, method == "heartbeat" {
            Task { @MainActor in
                self.onHeartbeat?()
            }
            return
        }

        guard let id = json["id"] as? String else {
            // Notification or malformed — log and drop.
            Logger.appShell.warning("DaemonMessenger: dropping id-less message \(String(describing: json), privacy: .public)")
            return
        }

        // Error response.
        if let err = json["error"] as? [String: Any] {
            let code = (err["code"] as? Int) ?? -1
            let message = (err["message"] as? String) ?? "(no message)"
            resume(id: id, with: .failure(DaemonMessengerError.daemonError(code: code, message: message)))
            return
        }

        // Result response.
        guard json["result"] != nil else {
            resume(id: id, with: .failure(DaemonMessengerError.missingResult(id: id)))
            return
        }
        resume(id: id, with: .success(SendableBox(json["result"] as Any)))
    }

    // MARK: - Call

    /// Send a JSON-RPC request and await the response.
    ///
    /// - Parameters:
    ///   - method: RPC method (e.g. "ping").
    ///   - params: params object; pass `[:]` for none.
    /// - Returns: the `result` field of the response (Any for forward-compat
    ///   with MCP, which returns heterogeneous payloads). Wrapped in
    ///   `SendableBox` because Swift 6 cannot verify `Any` is Sendable.
    func call(_ method: String, _ params: [String: Any]) async throws -> Any {
        guard let stdinPipe else {
            throw DaemonMessengerError.brokenPipe
        }

        let id = UUID().uuidString
        var payload: [String: Any] = [
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
        ]
        if !params.isEmpty {
            payload["params"] = params
        }

        let data = try JSONSerialization.data(withJSONObject: payload)
        guard var line = String(data: data, encoding: .utf8) else {
            throw DaemonMessengerError.writeFailed(message: "could not encode payload as utf-8")
        }
        line += "\n"

        let box = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<SendableBox, Error>) in
            self.pending[id] = continuation

            do {
                try stdinPipe.fileHandleForWriting.write(contentsOf: Data(line.utf8))
                // Try to flush — best-effort, not all FileHandle impls support this.
                try? stdinPipe.fileHandleForWriting.synchronize()
            } catch let error as NSError where error.code == 32 {  // POSIX EPIPE
                self.resume(id: id, with: .failure(DaemonMessengerError.brokenPipe))
            } catch {
                self.resume(id: id, with: .failure(DaemonMessengerError.writeFailed(message: error.localizedDescription)))
            }
        }
        return box.value
    }

    // MARK: - Helpers

    private func resume(id: String, with result: Result<SendableBox, Error>) {
        guard let continuation = pending.removeValue(forKey: id) else {
            Logger.appShell.warning("DaemonMessenger: resume for unknown id=\(id, privacy: .public)")
            return
        }
        switch result {
        case .success(let value):
            continuation.resume(returning: value)
        case .failure(let error):
            continuation.resume(throwing: error)
        }
    }

    /// Test helper: simulate a daemon response.
    func _testSimulateReply(id: String, result: Any) {
        resume(id: id, with: .success(SendableBox(result)))
    }

    /// Test helper: simulate a daemon heartbeat.
    func _testSimulateHeartbeat() {
        onHeartbeat?()
    }
}

// MARK: - SendableBox

/// Heterogeneous payload wrapper for JSON-RPC results.
///
/// `Any` is not `Sendable`, so Swift 6 refuses to pass it across actor
/// boundaries via `CheckedContinuation`. We mark the box `@unchecked
/// Sendable` because JSON deserialization always produces value types
/// (`[String: Any]`, `String`, `NSNumber`, `NSNull`, `[Any]`) — these are
/// safe to share. If a future caller stuffs a reference type in here, that
/// is the caller's bug.
@usableFromInline
struct SendableBox: @unchecked Sendable {
    @usableFromInline let value: Any
    @inlinable init(_ value: Any) { self.value = value }
}
