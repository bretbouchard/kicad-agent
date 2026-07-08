//
//  KiCadCLIDetector.swift
//  KiCadAgent
//
//  Phase 163 — KiCad CLI Integration
//
//  Detects an external KiCad 10+ install so the app can invoke kicad-cli
//  for ERC, DRC, render, and export operations. The CLI is NOT bundled
//  (PROJECT.md "Out of Scope (Locked Exclusions)": GPLv3 blocks App Store).
//
//  APP-04: App detects missing external KiCad install on first launch and
//  shows helpful install prompt. Main workflow is gated on `.ready`.
//
//  Detection strategy, in order:
//    1. `which kicad-cli` via /usr/bin/env — picks up user PATH installs.
//    2. /Applications/KiCad/kicad-cli — official macOS bundle location.
//    3. /usr/local/bin/kicad-cli — Homebrew default on Intel Macs.
//    4. /opt/homebrew/bin/kicad-cli — Homebrew default on Apple Silicon.
//
//  For each hit, parse `kicad-cli --version` output and verify >= 10.0.
//

import Foundation
import OSLog

/// Errors the detector can throw. Surfaces as `.wrongVersion` or
/// `.notInstalled` in the public API; the enum is for testing granularity.
enum KiCadDetectorError: LocalizedError, Equatable {
    case whichFailed(exitCode: Int32)
    case versionParseFailed(rawOutput: String)
    case spawnFailed(reason: String)

    var errorDescription: String? {
        switch self {
        case .whichFailed(let code):
            return "`which kicad-cli` exited with code \(code)"
        case .versionParseFailed(let raw):
            return "Could not parse version from: \(raw)"
        case .spawnFailed(let reason):
            return "Failed to spawn kicad-cli: \(reason)"
        }
    }
}

/// Detects an external KiCad CLI install. Injectable for tests.
///
/// `KiCadCLIDetector` itself is a thin orchestrator. All OS-level subprocess
/// work goes through the `ProcessRunner` protocol so tests can substitute
/// synthetic outputs and exercise every code path without spawning real
/// processes.
@MainActor
@Observable
final class KiCadCLIDetector {
    /// Latest cached status. SwiftUI views observe this.
    private(set) var status: KiCadInstallStatus = .notInstalled

    /// True while a detection run is in flight.
    private(set) var isChecking: Bool = false

    /// Last time `detect()` ran. Used by the onboarding view's "check again"
    /// button to show "checked N seconds ago".
    private(set) var lastCheckedAt: Date?

    /// Subprocess runner. Default `RealProcessRunner` shells out via Process.
    let runner: any ProcessRunner

    /// Static list of paths probed in addition to `which`.
    /// Public so tests can override if needed.
    static let candidatePaths: [String] = [
        "/Applications/KiCad/kicad-cli",
        "/usr/local/bin/kicad-cli",
        "/opt/homebrew/bin/kicad-cli",
    ]

    /// Official KiCad download URL for the onboarding screen.
    /// Per APP-04: one-tap install link from onboarding.
    static let downloadURL = URL(string: "https://www.kicad.org/download/macos/")!

    init(runner: any ProcessRunner = RealProcessRunner()) {
        self.runner = runner
    }

    // MARK: - Public API

    /// Synchronous cached accessor. Returns current status without spawning.
    var currentStatus: KiCadInstallStatus { status }

    /// Run detection and update `status`. Safe to call from main actor.
    /// Idempotent — re-running just refreshes the cache.
    /// Returns the new status so callers can branch without a separate read.
    @discardableResult
    func detect() async -> KiCadInstallStatus {
        isChecking = true
        defer { isChecking = false }

        let result = await detectAsync()
        status = result
        lastCheckedAt = Date()
        Logger.appShell.info("KiCadCLIDetector: \(result.debugDescription, privacy: .public)")
        return result
    }

    /// Auto-detect poll: re-runs `detect()` every `interval` seconds for up
    /// to `timeout` seconds. Stops as soon as `.ready` is found.
    /// Used by the onboarding "I've installed KiCad — check again" button.
    ///
    /// Returns the final status. The caller observes `status` for live updates.
    func autoDetectAfterInstall(
        interval: Duration = .seconds(5),
        timeout: Duration = .seconds(120)
    ) async -> KiCadInstallStatus {
        let deadline = ContinuousClock.now.advanced(by: timeout)
        while ContinuousClock.now < deadline {
            let result = await detect()
            if result.isReady { return result }
            try? await Task.sleep(for: interval)
        }
        return status
    }

    // MARK: - Detection internals

    /// Pure detection — no caching, no logging. Easier to test.
    private func detectAsync() async -> KiCadInstallStatus {
        // 1. Try `which kicad-cli` (PATH-based installs).
        if let path = await findViaWhich() {
            return await validateCandidate(path)
        }
        // 2. Fall back to well-known absolute paths.
        for candidate in Self.candidatePaths {
            if FileManager.default.isExecutableFile(atPath: candidate) {
                return await validateCandidate(candidate)
            }
        }
        return .notInstalled
    }

    /// Run `which kicad-cli` via `/usr/bin/env` so the user's shell PATH
    /// is honored. Returns the trimmed path or nil.
    private func findViaWhich() async -> String? {
        // `/usr/bin/env which kicad-cli` runs the user's `which` against PATH.
        // We use `/usr/bin/which` directly if env fails (sandboxed Mac App
        // Store builds may not see user PATH — see App Store review notes).
        let candidates = [
            ["/usr/bin/which", "kicad-cli"],
            ["/usr/bin/env", "which", "kicad-cli"],
        ]
        for cmd in candidates {
            do {
                let result = try await runner.run(
                    executable: cmd[0],
                    arguments: Array(cmd.dropFirst())
                )
                if result.exitCode == 0 {
                    let trimmed = result.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
                    if !trimmed.isEmpty { return trimmed }
                }
            } catch {
                // Try the next candidate.
                continue
            }
        }
        return nil
    }

    /// Given a candidate path, verify the file exists and run
    /// `kicad-cli --version` to check it's 10+.
    private func validateCandidate(_ path: String) async -> KiCadInstallStatus {
        let versionString: String
        do {
            let result = try await runner.run(executable: path, arguments: ["--version"])
            // kicad-cli prints to stdout; some versions print to stderr.
            // Be lenient — concat both and parse.
            let combined = (result.stdout + "\n" + result.stderr)
            guard let parsed = Version.parseFirstVersion(combined) else {
                // Couldn't parse — surface the raw output so logs/UI help debug.
                // Treat as not-installed rather than crash.
                Logger.appShell.error("KiCadCLIDetector: could not parse version from \(path, privacy: .public): \(combined.prefix(200), privacy: .public)")
                return .notInstalled
            }
            versionString = "\(parsed.major).\(parsed.minor).\(parsed.patch)"
        } catch {
            Logger.appShell.error("KiCadCLIDetector: spawn failed for \(path, privacy: .public): \(error.localizedDescription, privacy: .public)")
            return .notInstalled
        }

        guard let parsed = Version.parse(versionString) else {
            return .notInstalled
        }

        if parsed >= KiCadInstallStatus.minimumSupported {
            return .ready(path: path, version: versionString)
        } else {
            return .wrongVersion(found: versionString)
        }
    }
}

// MARK: - ProcessRunner

/// Abstraction over `Process` so tests can mock subprocess results.
///
/// Real impl: `RealProcessRunner` — uses Foundation.Process.
/// Test impls: return canned `ProcessResult` values.
protocol ProcessRunner: Sendable {
    func run(executable: String, arguments: [String]) async throws -> ProcessResult
}

/// Result of one subprocess invocation.
struct ProcessResult: Equatable, Sendable {
    let stdout: String
    let stderr: String
    let exitCode: Int32
}

/// Real subprocess runner backed by Foundation.Process.
struct RealProcessRunner: ProcessRunner {
    func run(executable: String, arguments: [String]) async throws -> ProcessResult {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global().async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: executable)
                process.arguments = arguments

                let stdoutPipe = Pipe()
                let stderrPipe = Pipe()
                process.standardOutput = stdoutPipe
                process.standardError = stderrPipe

                do {
                    try process.run()
                } catch {
                    continuation.resume(throwing: KiCadDetectorError.spawnFailed(reason: error.localizedDescription))
                    return
                }

                // Wait synchronously on this background thread.
                process.waitUntilExit()

                let stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()

                let stdout = String(data: stdoutData, encoding: .utf8) ?? ""
                let stderr = String(data: stderrData, encoding: .utf8) ?? ""

                continuation.resume(returning: ProcessResult(
                    stdout: stdout,
                    stderr: stderr,
                    exitCode: process.terminationStatus
                ))
            }
        }
    }
}

// MARK: - Version helpers

extension Version {
    /// Pull the first version-like substring out of a blob of text.
    /// kicad-cli --version output looks like "KiCad CLI 10.0.3" (or similar).
    /// We find the first \d+(\.\d+){0,2} pattern and parse it.
    static func parseFirstVersion(_ text: String) -> Version? {
        // Scan for the first run of digits, then keep consuming `.digits` groups.
        var index = text.startIndex
        while index < text.endIndex {
            if text[index].isNumber {
                // Collect the version string starting here.
                let start = index
                while index < text.endIndex {
                    let next = text.index(after: index)
                    if next >= text.endIndex { break }
                    let c = text[next]
                    if c.isNumber || c == "." {
                        index = next
                    } else {
                        break
                    }
                }
                let candidate = String(text[start...index])
                if let v = parse(candidate) { return v }
                // Otherwise keep scanning — maybe a leading "2026" date we don't want.
                index = text.index(after: index)
            } else {
                index = text.index(after: index)
            }
        }
        return nil
    }
}
