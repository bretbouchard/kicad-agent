#if os(macOS)
//
//  DaemonSupervisor.swift
//  Volta
//
//  Phase 161 — App Shell Foundation
//  Phase 162 — Python Daemon Bundling (real wiring landed here)
//
//  Owns the high-level daemon state machine. The OS-level subprocess
//  concerns live in `ProcessManager`; the JSON-RPC client lives in
//  `DaemonMessenger`. This file glues them into a single `@Observable`
//  that SwiftUI views (AppRootView's recovery alert, future status bar)
//  can subscribe to.
//
//  APP-01: surfaces failure within 5 seconds (no silent hang).
//  APP-03: checksum verification lives in ProcessManager.spawn.
//  APP-05: 5s SIGTERM → SIGKILL lives in ProcessManager.shutdown.
//  DAEM-01/DAEM-05: NSWorkspace.didWakeNotification → healthCheck.
//  DAEM-06: crash loop (5 in 60s) halts auto-restart.
//

import Foundation
import AppKit
import OSLog

/// Lifecycle states for the bundled Python daemon.
enum DaemonState: Equatable, Sendable {
    case notStarted
    case starting
    case ready
    case failed(reason: String)
    case restarting
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
/// Phase 162: real wiring to ProcessManager + DaemonMessenger. State
/// transitions are driven by the ProcessManager hooks.
@MainActor
@Observable
final class DaemonSupervisor {
    /// Current daemon state. Observable so views can react.
    private(set) var state: DaemonState = .notStarted {
        didSet {
            Logger.appShell.info("DaemonState \(String(describing: oldValue), privacy: .public) -> \(String(describing: self.state), privacy: .public)")
        }
    }

    /// Number of failed spawn attempts in the last 60 seconds.
    private(set) var recentFailureCount: Int = 0

    /// Timestamps of recent failures for crash-loop detection (DAEM-06).
    private var failureTimestamps: [Date] = []

    /// Maximum time to wait for daemon ready signal before declaring failure.
    /// APP-01 hard requirement: 5 seconds.
    static let spawnTimeout: Duration = .seconds(5)

    /// Crash-loop threshold (DAEM-06).
    static let crashLoopThreshold = 5

    /// The OS-level process manager. Owned here so tests can inject mocks.
    let processManager: ProcessManager

    /// Phase 212 — cached MCPClient for daemon communication.
    /// Returns nil if the daemon hasn't started yet (no messenger).
    private var _cachedClient: MCPClient?
    var mcpClient: MCPClient? {
        if let cached = _cachedClient { return cached }
        guard let messenger = processManager.messenger else { return nil }
        let client = MCPClient(messenger: messenger)
        _cachedClient = client
        return client
    }

    /// Observer for NSWorkspace.didWakeNotification (DAEM-01/DAEM-05).
    /// Plain MainActor-isolated optional. `deinit` cannot touch this, so
    /// callers must `detachObserver()` before release. In practice the
    /// supervisor lives for the app's lifetime, so leaking the observer
    /// on early teardown is benign.
    private var wakeObserver: NSObjectProtocol?

    init(processManager: ProcessManager = ProcessManager()) {
        self.processManager = processManager
        wireHooks()
        registerWakeNotification()
        Logger.appShell.info("DaemonSupervisor initialized (Phase 162 wired)")
    }

    deinit {
        // No MainActor access from deinit. Wake observer is owned by
        // NSWorkspace's notification center; it will be cleaned up when
        // the app exits. Call `detachObserver()` explicitly for tests.
    }

    /// Explicit teardown for tests. Idempotent.
    func detachObserver() {
        if let observer = wakeObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(observer)
            wakeObserver = nil
        }
    }

    // MARK: - Public API

    /// Attempt to start the daemon. Transitions through `.starting`
    /// → `.ready` on success, `.failed` on any error.
    func start() {
        guard state != .starting && state != .ready else {
            Logger.appShell.warning("Daemon already \(String(describing: self.state)) — ignoring start()")
            return
        }
        state = .starting
        Task { @MainActor in
            await self.startAsync()
        }
    }

    /// Async start — keeps the public `start()` synchronous for SwiftUI hooks.
    private func startAsync() async {
        do {
            try await processManager.spawn()
            // Wait up to spawnTimeout for first heartbeat or any stdout.
            let deadline = ContinuousClock.now.advanced(by: Self.spawnTimeout)
            while processManager.messenger == nil, ContinuousClock.now < deadline {
                try? await Task.sleep(for: .milliseconds(100))
            }
            if processManager.messenger == nil {
                Logger.appShell.error("Daemon spawn timed out — no stdout within 5s")
                recordFailure(.spawnTimeout)
                state = .failed(reason: DaemonError.spawnTimeout.localizedDescription)
                return
            }
            // Verify liveness with a real RPC ping.
            do {
                try await processManager.healthCheck()
                state = .ready
            } catch {
                Logger.appShell.error("Daemon health check failed: \(error.localizedDescription, privacy: .public)")
                recordFailure(.unknown(error.localizedDescription))
                state = .failed(reason: error.localizedDescription)
            }
        } catch {
            Logger.appShell.error("Daemon spawn failed: \(error.localizedDescription, privacy: .public)")
            recordFailure(.unknown(error.localizedDescription))
            state = .failed(reason: error.localizedDescription)
        }
    }

    /// Attempt graceful shutdown (APP-05: 5s SIGTERM → SIGKILL).
    func shutdown() {
        Logger.appShell.info("Daemon shutdown requested")
        state = .shuttingDown
        Task { @MainActor in
            await self.processManager.shutdown()
            self.state = .shutDown
        }
    }

    /// Retry from a failed state. Clears failure history first.
    func retry() {
        Logger.appShell.info("Daemon retry requested")
        failureTimestamps.removeAll()
        recentFailureCount = 0
        processManager.resetCrashHistory()
        state = .notStarted
        start()
    }

    /// Trigger a health check after a sleep/wake transition (DAEM-01/DAEM-05).
    func handleWake() {
        guard state == .ready || state == .notStarted else { return }
        Logger.appShell.info("Sleep/wake — running health check")
        Task { @MainActor in
            do {
                try await self.processManager.healthCheck()
            } catch {
                Logger.appShell.warning("Post-wake health check failed — restarting: \(error.localizedDescription, privacy: .public)")
                self.state = .restarting
                self.processManager.resetCrashHistory()
                self.start()
            }
        }
    }

    // MARK: - Wiring

    /// Attach ProcessManager hooks to our state machine.
    private func wireHooks() {
        processManager.onUnexpectedTermination = { @MainActor [weak self] _ in
            guard let self else { return }
            // Daemon died unexpectedly — try auto-restart unless we're in crash-loop.
            if self.processManager.halted {
                self.state = .failed(reason: DaemonError.crashLoop.localizedDescription)
            } else {
                self.state = .restarting
                self.start()
            }
        }
        processManager.onCrashLoop = { @MainActor [weak self] in
            guard let self else { return }
            self.recordFailure(.crashLoop)
            self.state = .failed(reason: DaemonError.crashLoop.localizedDescription)
        }
        processManager.onWatchdogTimeout = { @MainActor [weak self] in
            // Watchdog already killed the daemon; the termination handler
            // fires next to drive state. We just log here.
            Logger.appShell.error("Daemon watchdog fired — ProcessManager killed the daemon")
            _ = self
        }
    }

    // MARK: - Sleep/Wake (DAEM-01, DAEM-05)

    private func registerWakeNotification() {
        wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.handleWake()
            }
        }
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

#endif // os(macOS)
