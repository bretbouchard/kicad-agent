//
//  JavaLocator.swift
//  Volta
//
//  Phase 253 Task 2 / Gate 2 P2 — Java detection extracted from
//  FreeroutingProvider so it's testable via ProcessRunner mocks and
//  does not block the cooperative thread pool.
//
//  Detection strategy, in order:
//    1. $JAVA_HOME/bin/java (user-set env var = explicit user intent)
//    2. /usr/libexec/java_home via the injected ProcessRunner
//       (DispatchQueue.global().async + continuation = non-blocking)
//
//  ponytail: zero IO during availability if previously-cached path is
//  still valid. Re-probe only on demand (lazy invalidation via the
//  parent provider's app-launch reset).
//

import Foundation

/// Locates a usable `java` executable without spawning blocking Process
/// calls on the cooperative thread pool. All subprocess IO is routed
/// through an injected `ProcessRunner`.
struct JavaLocator: Sendable {
    let runner: any ProcessRunner

    init(runner: any ProcessRunner) {
        self.runner = runner
    }

    /// Probe for a working Java install. Returns the absolute path of
    /// the `java` binary, or nil if no install was detected.
    ///
    /// Sandbox-clean: never invokes `which`/`type` or walks `$PATH`.
    /// Only `$JAVA_HOME` and `/usr/libexec/java_home` (macOS framework).
    func locate() async -> String? {
        // 1. $JAVA_HOME first — explicit user intent wins over framework.
        if let home = ProcessInfo.processInfo.environment["JAVA_HOME"] {
            let url = URL(fileURLWithPath: "\(home)/bin/java")
            if FileManager.default.isExecutableFile(atPath: url.path) {
                return url.path
            }
        }

        // 2. /usr/libexec/java_home via the cooperative-safe runner.
        // The runner protocol uses DispatchQueue.global() + a continuation
        // internally, so this async call never blocks the cooperative
        // thread pool on a synchronous wait.
        let result: ProcessResult
        do {
            result = try await runner.run(
                executable: "/usr/libexec/java_home",
                arguments: []
            )
        } catch {
            return nil
        }
        guard result.exitCode == 0 else { return nil }

        let home = result.stdout
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !home.isEmpty else { return nil }

        let javaURL = URL(fileURLWithPath: "\(home)/bin/java")
        return FileManager.default.isExecutableFile(atPath: javaURL.path)
            ? javaURL.path
            : nil
    }
}
