//
//  DaemonSupervisor.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//
//  Daemon lifecycle stub.
//
//  APP-01 augmentation: "If daemon fails to spawn within 5s, app shows recovery UI"
//  APP-03 augmentation: "Daemon binary checksum verified on launch"
//  APP-05 augmentation: "Daemon shutdown 5s timeout + force-kill"
//
//  Phase 162 (Python Daemon Bundling) replaces this stub with real PyInstaller
//  subprocess spawn. For Phase 161, this provides the state machine so the
//  recovery UI can be developed and tested against real transitions.
//

import Foundation
import OSLog

/// Lifecycle states for the bundled Python daemon.
enum DaemonState: Equatable, Sendable {
    case notStarted
    case starting
    case ready
    case failed(reason: String)
    case shuttingDown
    case shutDown
}

/// Errors that can occur during daemon supervision.
enum DaemonError: LocalizedError, Equatable {
    case spawnTimeout
    case checksumMismatch
    case crashLoop
    case unknown(String)

    var errorDescription: String? {
        switch self {
        case .spawnTimeout:
            return "Daemon did not start within 5 seconds."
        case .checksumMismatch:
            return "Daemon binary checksum verification failed. The bundle may be corrupt."
        case .crashLoop:
            return "Daemon crashed repeatedly. Crash loop detected (5 in 60s)."
        case .unknown(let msg):
            return msg
        }
    }
}

/// Supervisor for the bundled Python daemon subprocess.
///
/// Phase 161: state machine only — `start()` immediately fails with a structured
/// error so the recovery UI is exercised. Phase 162 wires real Process spawn.
///
/// APP-01: surfaces failure within 5 seconds (no silent hang).
@MainActor
@Observable
final class DaemonSupervisor {
    /// Current daemon state. Observable so views can react.
    private(set) var state: DaemonState = .notStarted

    /// Number of failed spawn attempts in the last 60 seconds.
    private(set) var recentFailureCount: Int = 0

    /// Timestamps of recent failures for crash-loop detection (DAEM-06).
    private var failureTimestamps: [Date] = []

    /// Maximum time to wait for daemon ready signal before declaring failure.
    /// APP-01 hard requirement: 5 seconds.
    static let spawnTimeout: Duration = .seconds(5)

    /// Crash-loop threshold (DAEM-06).
    static let crashLoopThreshold = 5

    init() {
        Logger.appShell.info("DaemonSupervisor initialized (Phase 161 stub)")
    }

    /// Attempt to start the daemon.
    ///
    /// Phase 161 behavior: transitions through `.starting` then immediately
    /// to `.failed(.spawnTimeout)` so the recovery UI is reachable and tested.
    /// Phase 162 will replace this with real Process spawn + health check.
    func start() {
        guard state != .starting && state != .ready else {
            Logger.appShell.warning("Daemon already \(String(describing: self.state)) — ignoring start()")
            return
        }
        Logger.appShell.info("Daemon start requested — Phase 161 stub returns spawnTimeout")
        state = .starting
        recordFailure(.spawnTimeout)
        state = .failed(reason: DaemonError.spawnTimeout.localizedDescription)
    }

    /// Attempt graceful shutdown.
    ///
    /// Phase 162: 5-second timeout, then force-kill (APP-05).
    func shutdown() {
        Logger.appShell.info("Daemon shutdown requested — Phase 161 stub marks shutDown")
        state = .shuttingDown
        state = .shutDown
    }

    /// Retry from a failed state. Clears failure if start succeeds (Phase 162).
    func retry() {
        Logger.appShell.info("Daemon retry requested")
        failureTimestamps.removeAll()
        recentFailureCount = 0
        state = .notStarted
        start()
    }

    // MARK: - Crash-loop detection (DAEM-06)

    private func recordFailure(_ error: DaemonError) {
        let now = Date.now
        failureTimestamps.append(now)
        // Drop failures older than 60s.
        failureTimestamps = failureTimestamps.filter { now.timeIntervalSince($0) < 60 }
        recentFailureCount = failureTimestamps.count
        if recentFailureCount >= Self.crashLoopThreshold {
            Logger.appShell.error("Daemon crash loop detected — \(self.recentFailureCount) failures in 60s")
            state = .failed(reason: DaemonError.crashLoop.localizedDescription)
        }
    }
}
