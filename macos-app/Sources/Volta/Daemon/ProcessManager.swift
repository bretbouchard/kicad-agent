#if os(macOS)
//
//  ProcessManager.swift
//  Volta
//
//  Phase 162 — Python Daemon Bundling
//
//  Spawns and supervises the bundled Python daemon (PyInstaller binary).
//  Owns the `Process`, stdio pipes, watchdog, and crash-loop counter.
//
//  Lifecycle states are surfaced to `DaemonSupervisor`, which is the
//  `@Observable` consumers (UI, tests) actually subscribe to. This file
//  deliberately keeps the OS-level concerns here and the SwiftUI-facing
//  concerns in DaemonSupervisor.swift.
//
//  Hardening:
//  - APP-03: SHA-256 checksum of bundled binary verified on spawn.
//  - APP-05: 5-second SIGTERM timeout, then SIGKILL with audit log.
//  - DAEM-01/DAEM-05: NSWorkspace.didWakeNotification triggers healthCheck.
//  - DAEM-06: 5 crashes in 60s halts auto-restart.
//  - PITFALL 2: PYTHONUNBUFFERED=1 enforced; 30s stdout watchdog kills hang.
//

import Foundation
import OSLog
import CryptoKit

// MARK: - Errors

/// Errors raised by `ProcessManager`. Surfaced via `DaemonSupervisor.state`.
enum ProcessManagerError: LocalizedError, Equatable {
    case binaryMissing(path: String)
    case checksumMismatch(expected: String, actual: String)
    case spawnFailed(message: String)
    case watchdogTimeout
    case crashLoop
    case brokenPipe
    case unknown(String)

    var errorDescription: String? {
        switch self {
        case .binaryMissing(let path):
            return "Daemon binary not found at \(path). The app bundle may be incomplete."
        case .checksumMismatch(let expected, let actual):
            return "Daemon checksum mismatch (expected \(expected.prefix(8))…, got \(actual.prefix(8))…). The bundle may be corrupt."
        case .spawnFailed(let message):
            return "Failed to launch daemon: \(message)"
        case .watchdogTimeout:
            return "Daemon did not produce output for 30 seconds (watchdog killed it)."
        case .crashLoop:
            return "Daemon crash loop detected (5 crashes in 60 seconds)."
        case .brokenPipe:
            return "Daemon pipe closed unexpectedly."
        case .unknown(let message):
            return message
        }
    }
}

// MARK: - ProcessManager

/// Subprocess lifecycle for the bundled Python daemon.
///
/// `@MainActor` because Process.terminationHandler and Pipe readability
/// handlers fire on background queues; we hop back to main before mutating
/// observable state. DaemonSupervisor (also @MainActor) holds the only
/// reference to a ProcessManager instance.
@MainActor
@Observable
final class ProcessManager {
    // MARK: Configuration

    /// Maximum time to wait for the daemon to emit any output before
    /// declaring a watchdog timeout (PITFALL 2 — stdio buffering deadlock).
    static let watchdogTimeout: Duration = .seconds(30)

    /// Maximum time to wait for graceful SIGTERM shutdown before SIGKILL (APP-05).
    static let shutdownTimeout: Duration = .seconds(5)

    /// Crash-loop threshold (DAEM-06): 5 crashes in 60s halts restart.
    static let crashLoopThreshold = 5
    static let crashLoopWindow: TimeInterval = 60.0

    // MARK: State (observable for tests + supervisor)

    /// The current OS-level process, if any. Nil when never launched or
    /// after termination completes.
    private(set) var process: Process?

    /// Timestamps of recent crashes for sliding-window loop detection.
    private(set) var recentCrashTimestamps: [Date] = []

    /// True if the manager has permanently given up due to crash-loop.
    private(set) var halted: Bool = false

    /// Counts total launches since init (debug aid).
    private(set) var launchCount: Int = 0

    /// Pipes — retained so tests can read/write them post-launch.
    private(set) var stdinPipe: Pipe?
    private(set) var stdoutPipe: Pipe?

    /// Line buffer for stdout reads. Retained on `self` so the readability
    /// handler's weak capture resolves for the daemon's lifetime — without
    /// this, the local `let buffer` in `spawn()` is deallocated when the
    /// function returns and every line is silently dropped (PITFALL: the
    /// watchdog then fires after 30s of "no stdout").
    private var stdoutLineBuffer: LineBuffer?

    /// Messenger bound to the most recent successful spawn. Nil until the
    /// first response line is received (so callers can detect readiness).
    private(set) var messenger: DaemonMessenger?

    // MARK: Watchdog

    /// Task that fires after `watchdogTimeout` of stdout silence. Reset
    /// every time the daemon emits a line.
    private var watchdogTask: Task<Void, Never>?

    /// Serial queue for stdout reads. Avoids Swift 6 sendability pitfalls
    /// around capturing mutable state in readability handlers.
    private let stdoutQueue = DispatchQueue(label: "com.kicadagent.daemon.stdout")

    // MARK: Lifecycle hooks

    /// Called whenever the process terminates unexpectedly. Default no-op;
    /// DaemonSupervisor overrides to drive state transitions.
    var onUnexpectedTermination: (@MainActor (Int) -> Void)?

    /// Called when stdout goes silent past the watchdog window.
    var onWatchdogTimeout: (@MainActor () -> Void)?

    /// Called when the crash-loop threshold is reached.
    var onCrashLoop: (@MainActor () -> Void)?

    // MARK: Init

    init() {
        Logger.appShell.info("ProcessManager initialized")
    }

    deinit {
        // Cannot reference MainActor-isolated `process` from nonisolated
        // deinit under Swift 6. Cleanup is best-effort: callers must invoke
        // `shutdown()` explicitly before releasing the manager.
    }

    // MARK: - Spawn

    /// Locate the bundled daemon executable.
    ///
    /// Resolution order:
    /// 1. `<Bundle.main.resourcePath>/volta-daemon/volta-daemon` (production).
    /// 2. `Bundle.main.url(forResource: "volta-daemon", withExtension: nil)`
    ///    (fallback if the resource is registered as a top-level file).
    /// 3. `macos-app/daemon/dist/volta-daemon/volta-daemon` (dev SPM).
    /// 4. `daemon/dist/volta-daemon/volta-daemon` (dev relative).
    /// 5. Hardcoded dev path.
    ///
    /// The .app bundle path is preferred so the sandboxed app finds the
    /// binary inside its own bundle (sandbox blocks launching executables
    /// from arbitrary user paths). The hardcoded fallback intentionally
    /// points inside the user's clone — dev convenience only, and the
    /// sandbox will block it in shipping builds.
    nonisolated static func resolveDaemonURL() -> URL? {
        // 1. App bundle: Contents/Resources/volta-daemon/volta-daemon
        if let resourcePath = Bundle.main.resourcePath {
            let bundled = (resourcePath as NSString)
                .appendingPathComponent("volta-daemon/volta-daemon")
            if FileManager.default.isExecutableFile(atPath: bundled) {
                return URL(fileURLWithPath: bundled)
            }
        }
        // 2. Top-level bundle resource (registered as file, not directory).
        if let bundleURL = Bundle.main.url(forResource: "volta-daemon", withExtension: nil),
           FileManager.default.isExecutableFile(atPath: bundleURL.path) {
            return bundleURL
        }
        // 3. Dev paths (cwd-relative + known repo path).
        let cwd = FileManager.default.currentDirectoryPath
        let distCandidates = [
            "\(cwd)/macos-app/daemon/dist/volta-daemon/volta-daemon",
            "\(cwd)/daemon/dist/volta-daemon/volta-daemon",
            "/Users/bretbouchard/apps/volta/macos-app/daemon/dist/volta-daemon/volta-daemon",
        ]
        for path in distCandidates {
            if FileManager.default.isExecutableFile(atPath: path) {
                return URL(fileURLWithPath: path)
            }
        }
        return nil
    }

    /// Locate a Python interpreter for last-resort dev mode.
    nonisolated static func resolvePythonURL() -> URL? {
        let candidates = [
            "/Users/bretbouchard/apps/volta/.venv/bin/python",
            "/usr/local/bin/python3",
            "/opt/homebrew/bin/python3",
        ]
        for path in candidates where FileManager.default.isExecutableFile(atPath: path) {
            return URL(fileURLWithPath: path)
        }
        return nil
    }

    /// Compute SHA-256 hex of a file at `url`. Returns nil on I/O error.
    nonisolated static func sha256(of url: URL) -> String? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        let digest = SHA256.hash(data: data)
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    /// Verify the bundled binary's checksum against `<binary>.sha256`.
    /// Returns true if the sidecar is missing (dev mode tolerates this).
    nonisolated static func verifyChecksum(of binaryURL: URL) -> Bool {
        let sidecar = binaryURL.appendingPathExtension("sha256")
        guard FileManager.default.fileExists(atPath: sidecar.path) else {
            // No checksum file → accept (Phase 200 makes this mandatory).
            return true
        }
        guard let raw = try? String(contentsOf: sidecar, encoding: .utf8) else {
            return false
        }
        // `shasum` format is "<hex>  <file>"; first token is the hash.
        let expected = raw.split(whereSeparator: { $0.isWhitespace }).first.map(String.init)?.lowercased()
        guard let expected, let actual = sha256(of: binaryURL)?.lowercased() else {
            return false
        }
        return expected == actual
    }

    /// Spawn the daemon. Throws on missing binary, checksum mismatch, or
    /// process spawn failure. Idempotent: if already running, returns silently.
    func spawn() async throws {
        if halted {
            throw ProcessManagerError.crashLoop
        }
        if let process, process.isRunning {
            Logger.appShell.warning("ProcessManager.spawn called while daemon already running — ignoring")
            return
        }

        // Resolve executable + arguments.
        let executableURL: URL
        let arguments: [String]
        if let binary = Self.resolveDaemonURL() {
            // APP-03 — checksum verification.
            guard Self.verifyChecksum(of: binary) else {
                Logger.appShell.error("Daemon checksum mismatch for \(binary.path)")
                throw ProcessManagerError.checksumMismatch(expected: "(see sidecar)", actual: "(computed)")
            }
            executableURL = binary
            arguments = []
        } else if let python = Self.resolvePythonURL() {
            // Dev fallback: run daemon_entry.py directly under .venv python.
            let entry = "macos-app/daemon/daemon_entry.py"
            guard FileManager.default.fileExists(atPath: entry) else {
                throw ProcessManagerError.binaryMissing(path: entry)
            }
            executableURL = python
            arguments = ["-u", entry]
            Logger.appShell.warning("ProcessManager falling back to dev-mode python invocation")
        } else {
            throw ProcessManagerError.binaryMissing(path: "(bundled daemon not found)")
        }

        // Configure process.
        let proc = Process()
        proc.executableURL = executableURL
        proc.arguments = arguments

        // PITFALL 2 prevention — force unbuffered stdout.
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        proc.environment = env

        // Pipes — owned by us for the lifetime of the process.
        let stdin = Pipe()
        let stdout = Pipe()
        let stderr = Pipe()  // log only, do not consume programmatically.
        proc.standardInput = stdin
        proc.standardOutput = stdout
        proc.standardError = stderr

        // Wrap mutable accumulators in a class so we can capture a stable
        // reference inside the readability handler (Swift 6 sendability).
        // Store on self so the buffer outlives `spawn()` — the readability
        // handler's `[weak buffer]` capture would otherwise resolve to nil
        // once the function returns, silently dropping every stdout line.
        let buffer = LineBuffer()
        stdoutLineBuffer = buffer

        // Termination handler — runs on background queue.
        let terminationClosure: @Sendable (Process) -> Void = { [weak self] terminated in
            let status = terminated.terminationStatus
            let reason = terminated.terminationReason
            Task { @MainActor in
                self?.handleTermination(status: Int(status), reason: reason)
            }
        }
        proc.terminationHandler = terminationClosure

        // Readability handler — runs on a background queue. We hand lines
        // to a serial queue, then hop to MainActor for state mutation.
        stdout.fileHandleForReading.readabilityHandler = { [weak self, weak buffer] handle in
            let chunk = handle.availableData
            guard !chunk.isEmpty, let buffer else { return }
            let lines = buffer.append(chunk)
            for line in lines {
                let captured = line
                Task { @MainActor in
                    self?.handleStdoutLine(captured)
                }
            }
        }

        do {
            try proc.run()
        } catch {
            throw ProcessManagerError.spawnFailed(message: error.localizedDescription)
        }

        process = proc
        stdinPipe = stdin
        stdoutPipe = stdout
        launchCount += 1
        Logger.appShell.info("Daemon spawned (pid=\(proc.processIdentifier), launch #\(self.launchCount))")

        // Wire messenger once pipes exist.
        let messenger = DaemonMessenger()
        messenger.attach(stdinPipe: stdin)
        self.messenger = messenger

        // Arm watchdog — must show first output within 30s.
        armWatchdog()
    }

    // MARK: - Shutdown

    /// Graceful shutdown: SIGTERM, wait 5s, force-kill (APP-05).
    func shutdown() async {
        guard let proc = process else { return }
        guard proc.isRunning else {
            process = nil
            return
        }

        Logger.appShell.info("Daemon shutdown: sending SIGTERM to pid=\(proc.processIdentifier)")
        // Detach readability handler so we don't race the messenger.
        stdoutPipe?.fileHandleForReading.readabilityHandler = nil

        proc.terminate()  // SIGTERM

        // Wait up to shutdownTimeout for clean exit.
        let deadline = ContinuousClock.now.advanced(by: Self.shutdownTimeout)
        while proc.isRunning, ContinuousClock.now < deadline {
            try? await Task.sleep(for: .milliseconds(100))
        }

        if proc.isRunning {
            Logger.appShell.error("Daemon did not exit within \(Self.shutdownTimeout.components.seconds)s — sending SIGKILL")
            auditLog(event: "daemon_force_kill", detail: "pid=\(proc.processIdentifier)")
            kill(proc.processIdentifier, SIGKILL)
            // SIGKILL is async; give the kernel a beat to reap.
            try? await Task.sleep(for: .milliseconds(200))
        }

        auditLog(event: "daemon_shutdown", detail: "status=\(proc.terminationStatus)")
        watchdogTask?.cancel()
        watchdogTask = nil
        process = nil
        stdinPipe = nil
        stdoutPipe = nil
        stdoutLineBuffer = nil
        messenger = nil
    }

    // MARK: - Health check

    /// Send a `ping` request; reset watchdog on response. Throws on failure.
    func healthCheck() async throws {
        guard let messenger else {
            throw ProcessManagerError.unknown("messenger not yet ready")
        }
        let result = try await messenger.call("ping", [:])
        guard let dict = result as? [String: Any], dict["pong"] as? Bool == true else {
            throw ProcessManagerError.unknown("malformed ping response")
        }
        resetWatchdog()
    }

    // MARK: - Watchdog

    /// Arm (or re-arm) the stdout-silence watchdog.
    private func armWatchdog() {
        watchdogTask?.cancel()
        let timeoutSecs = Self.watchdogTimeout.components.seconds
        watchdogTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: Self.watchdogTimeout)
            guard let self, !Task.isCancelled else { return }
            Logger.appShell.error("Daemon watchdog fired — no stdout for \(timeoutSecs)s")
            self.auditLog(event: "daemon_watchdog_kill", detail: "no stdout for \(timeoutSecs)s")
            self.onWatchdogTimeout?()
            // Kill + record a crash for loop detection.
            if let proc = self.process, proc.isRunning {
                kill(proc.processIdentifier, SIGKILL)
            }
            self.recordCrash()
        }
    }

    private func resetWatchdog() {
        watchdogTask?.cancel()
        armWatchdog()
    }

    // MARK: - Stdout handling

    private func handleStdoutLine(_ line: String) {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        resetWatchdog()
        // Route to messenger.
        messenger?.ingest(line: trimmed)
    }

    // MARK: - Termination

    private func handleTermination(status: Int, reason: Process.TerminationReason) {
        Logger.appShell.info("Daemon terminated status=\(status) reason=\(reason.rawValue)")
        watchdogTask?.cancel()
        watchdogTask = nil
        stdoutPipe?.fileHandleForReading.readabilityHandler = nil

        // 0 = graceful exit. SIGTERM (15) during shutdown is also expected.
        let isPlannedExit = (status == 0) || (status == 15)
        if !isPlannedExit {
            recordCrash()
            auditLog(event: "daemon_crash", detail: "status=\(status) reason=\(reason.rawValue)")
            onUnexpectedTermination?(status)
        } else {
            auditLog(event: "daemon_exit_clean", detail: "status=\(status)")
        }

        process = nil
        stdinPipe = nil
        stdoutPipe = nil
        stdoutLineBuffer = nil
        messenger = nil
    }

    // MARK: - Crash-loop detection (DAEM-06)

    private func recordCrash() {
        let now = Date.now
        recentCrashTimestamps.append(now)
        // Sliding window: drop anything older than 60s.
        recentCrashTimestamps = recentCrashTimestamps.filter {
            now.timeIntervalSince($0) < Self.crashLoopWindow
        }
        Logger.appShell.info("Crash recorded — \(self.recentCrashTimestamps.count) in last 60s")
        if recentCrashTimestamps.count >= Self.crashLoopThreshold {
            Logger.appShell.error("DAEM-06 crash loop: \(self.recentCrashTimestamps.count) crashes in 60s — halting")
            halted = true
            onCrashLoop?()
        }
    }

    /// Reset crash history (called when manual retry from UI).
    func resetCrashHistory() {
        recentCrashTimestamps.removeAll()
        halted = false
    }

    // MARK: - Audit log

    /// Append a structured audit entry. Phase 168 will swap this for a
    /// proper OSLog signpost-based audit trail.
    private func auditLog(event: String, detail: String) {
        Logger.appShell.notice("audit event=\(event, privacy: .public) detail=\(detail, privacy: .public)")
    }
}

// MARK: - LineBuffer

/// Mutable line buffer captured by reference inside the readability handler.
/// Lives on `stdoutQueue`-owned timelines; not Sendable because callers
/// serialize through `stdoutQueue` themselves.
final class LineBuffer: @unchecked Sendable {
    private var buffer = Data()
    private let lock = NSLock()

    /// Append a chunk and return any complete lines it produced.
    func append(_ chunk: Data) -> [String] {
        lock.lock()
        defer { lock.unlock() }
        buffer.append(chunk)
        var lines: [String] = []
        while let idx = buffer.firstIndex(of: 0x0A) {
            // Extract [0...idx], inclusive of newline. Convert to Range.
            let range = 0..<(idx + 1)
            let lineData = buffer.subdata(in: range)
            buffer.removeSubrange(range)
            if let s = String(data: lineData, encoding: .utf8) {
                lines.append(s)
            }
        }
        return lines
    }
}

#endif // os(macOS)
