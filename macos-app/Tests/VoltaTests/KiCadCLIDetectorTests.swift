//
//  KiCadCLIDetectorTests.swift
//  VoltaTests
//
//  Phase 163 — KiCad CLI Integration
//
//  Tests for KiCadCLIDetector using a mock ProcessRunner so no real
//  kicad-cli subprocess is spawned. Coverage:
//
//    - .ready happy path (v10.0.3)
//    - .ready with patch and minor variations (v10.5.1, v11.0.0)
//    - .wrongVersion (v9.0.2)
//    - .notInstalled (which fails, no candidate paths exist)
//    - version parsing from "KiCad CLI 10.0.3" output
//    - version parsing from "10.0" partial output
//    - detection with kiCad at /Applications/KiCad/kicad-cli
//    - detection with kiCad at /usr/local/bin/kicad-cli
//    - detection with kiCad at /opt/homebrew/bin/kicad-cli
//    - autoDetectAfterInstall polls and returns ready on first hit
//    - autoDetectAfterInstall times out when kicad-cli never appears
//

import Testing
import Foundation
@testable import Volta

@MainActor
@Suite("KiCad CLI Detector")
struct KiCadCLIDetectorTests {

    // MARK: - Happy path

    @Test("Detects KiCad 10.0.3 via `which`")
    func detectsReadyViaWhich() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/usr/local/bin/kicad-cli")
        await runner.setVersion(executable: "/usr/local/bin/kicad-cli", stdout: "KiCad CLI 10.0.3\n")
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.detect()

        guard case .ready(let path, let version) = status else {
            Issue.record("Expected .ready, got \(status)")
            return
        }
        #expect(path == "/usr/local/bin/kicad-cli")
        #expect(version == "10.0.3")
    }

    @Test("Detects KiCad 11.0.0 as ready (forward compat)")
    func detectsFutureVersion() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/Applications/KiCad/kicad-cli")
        await runner.setVersion(executable: "/Applications/KiCad/kicad-cli", stdout: "11.0.0\n")
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.detect()
        if case .ready(_, let v) = status {
            #expect(v == "11.0.0")
        } else {
            Issue.record("Expected .ready for v11, got \(status)")
        }
    }

    @Test("Detects KiCad 10.5.1 as ready (minor + patch variations)")
    func detectsMinorPatchVariations() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/usr/local/bin/kicad-cli")
        await runner.setVersion(executable: "/usr/local/bin/kicad-cli", stdout: "10.5.1\n")
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.detect()
        if case .ready(_, let v) = status {
            #expect(v == "10.5.1")
        } else {
            Issue.record("Expected .ready for v10.5.1, got \(status)")
        }
    }

    // MARK: - Wrong version

    @Test("Rejects KiCad 9.0.2 with .wrongVersion")
    func rejectsOldKiCad() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/usr/local/bin/kicad-cli")
        await runner.setVersion(executable: "/usr/local/bin/kicad-cli", stdout: "9.0.2\n")
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.detect()
        if case .wrongVersion(let found) = status {
            #expect(found == "9.0.2")
        } else {
            Issue.record("Expected .wrongVersion, got \(status)")
        }
    }

    @Test("Rejects KiCad 8.99 (pre-release of 9.0)")
    func rejectsPreV10() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/usr/local/bin/kicad-cli")
        await runner.setVersion(executable: "/usr/local/bin/kicad-cli", stdout: "8.99.4\n")
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.detect()
        if case .wrongVersion = status {
            // pass
        } else {
            Issue.record("Expected .wrongVersion for v8.99, got \(status)")
        }
    }

    // MARK: - Not installed

    @Test("Returns .notInstalled when which fails and no candidate paths exist")
    func notInstalledWhenAbsent() async {
        let runner = MockProcessRunner()
        await runner.setWhichFailing()
        if hasCandidatePath() {
            // Some test machine has kicad-cli installed at one of our paths.
            // Skip — covered by the candidate-path test below.
            return
        }
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.detect()
        #expect(status == .notInstalled)
    }

    @Test("Falls back to candidate paths when which fails")
    func fallsBackToCandidatePaths() async {
        // We can't easily force FileManager.isExecutableFile to return true
        // for a fake path without a real file. So this test only runs when
        // a real candidate path exists on the test host.
        guard let path = realCandidatePath() else {
            return // No real candidate path on this host; covered by which test.
        }
        let runner = MockProcessRunner()
        await runner.setWhichFailing()
        await runner.setVersion(executable: path, stdout: "10.0.0\n")
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.detect()
        if case .ready(let foundPath, _) = status {
            #expect(foundPath == path)
        } else {
            Issue.record("Expected .ready via candidate path, got \(status)")
        }
    }

    // MARK: - Version output parsing

    @Test("Parses version with leading label")
    func parsesLabeledVersion() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/usr/local/bin/kicad-cli")
        await runner.setVersion(executable: "/usr/local/bin/kicad-cli", stdout: "kicad-cli 10.0.3\n")
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.detect()
        if case .ready(_, let v) = status {
            #expect(v == "10.0.3")
        }
    }

    @Test("Parses version from stderr when stdout is empty")
    func parsesVersionFromStderr() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/usr/local/bin/kicad-cli")
        await runner.setVersion(executable: "/usr/local/bin/kicad-cli", stdout: "", stderr: "KiCad 10.0.3\n")
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.detect()
        if case .ready(_, let v) = status {
            #expect(v == "10.0.3")
        }
    }

    @Test("Returns .notInstalled when version output is unparseable")
    func unparseableVersion() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/usr/local/bin/kicad-cli")
        await runner.setVersion(executable: "/usr/local/bin/kicad-cli", stdout: "garbage output\n")
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.detect()
        #expect(status == .notInstalled)
    }

    @Test("Handles version with v prefix (v10.0.3)")
    func handlesVPrefix() {
        let v = Version.parse("v10.0.3")
        #expect(v?.major == 10)
        #expect(v?.minor == 0)
        #expect(v?.patch == 3)
    }

    @Test("Handles partial version (10.0)")
    func handlesPartialVersion() {
        let v = Version.parse("10.0")
        #expect(v?.major == 10)
        #expect(v?.minor == 0)
        #expect(v?.patch == 0)
    }

    @Test("Handles major-only version (10)")
    func handlesMajorOnly() {
        let v = Version.parse("10")
        #expect(v?.major == 10)
    }

    @Test("Returns nil for non-numeric string")
    func nilForNonNumeric() {
        #expect(Version.parse("abc") == nil)
    }

    @Test("Version comparison works")
    func versionComparison() {
        #expect(Version(major: 10) < Version(major: 11))
        #expect(Version(major: 9) < Version(major: 10))
        #expect(Version(major: 10, minor: 0) < Version(major: 10, minor: 1))
        #expect(Version(major: 10, minor: 0, patch: 0) < Version(major: 10, minor: 0, patch: 1))
        #expect(!(Version(major: 11) < Version(major: 10)))
    }

    @Test("parseFirstVersion finds version in mixed text")
    func parseFirstVersionFromText() {
        let v = Version.parseFirstVersion("KiCad Command Line Interface\nVersion: 10.0.3\nCompiled with...")
        #expect(v?.major == 10)
        #expect(v?.minor == 0)
        #expect(v?.patch == 3)
    }

    // MARK: - Caching behavior

    @Test("detect() updates lastCheckedAt")
    @MainActor
    func updatesLastCheckedAt() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/usr/local/bin/kicad-cli")
        await runner.setVersion(executable: "/usr/local/bin/kicad-cli", stdout: "10.0.3\n")
        let detector = KiCadCLIDetector(runner: runner)

        #expect(detector.lastCheckedAt == nil)
        _ = await detector.detect()
        #expect(detector.lastCheckedAt != nil)
    }

    @Test("detect() sets isChecking during run")
    @MainActor
    func setsIsChecking() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/usr/local/bin/kicad-cli")
        await runner.setVersion(executable: "/usr/local/bin/kicad-cli", stdout: "10.0.3\n")
        let detector = KiCadCLIDetector(runner: runner)

        #expect(detector.isChecking == false)
        // detect() is async; we can't easily intercept mid-run, but after
        // completion it should be false again.
        _ = await detector.detect()
        #expect(detector.isChecking == false)
    }

    // MARK: - autoDetectAfterInstall

    @Test("autoDetectAfterInstall returns immediately when kicad-cli is ready")
    func autoDetectImmediate() async {
        let runner = MockProcessRunner()
        await runner.setWhich(path: "/usr/local/bin/kicad-cli")
        await runner.setVersion(executable: "/usr/local/bin/kicad-cli", stdout: "10.0.3\n")
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.autoDetectAfterInstall(interval: .milliseconds(50), timeout: .seconds(5))
        #expect(status.isReady)
    }

    @Test("autoDetectAfterInstall times out when kicad-cli never appears")
    func autoDetectTimeout() async {
        let runner = MockProcessRunner()
        await runner.setWhichFailing()
        if hasCandidatePath() {
            return // skip on machines with real kicad-cli
        }
        let detector = KiCadCLIDetector(runner: runner)

        let status = await detector.autoDetectAfterInstall(interval: .milliseconds(50), timeout: .seconds(1))
        #expect(status == .notInstalled)
    }

    // MARK: - Real kicad-cli integration smoke test
    // If the test host has kicad-cli installed, verify the REAL runner can
    // detect it. This catches regressions in RealProcessRunner that mock
    // tests cannot.

    @Test("Real runner detects kicad-cli if installed on test host")
    func realRunnerIntegration() async {
        guard FileManager.default.isExecutableFile(atPath: "/usr/local/bin/kicad-cli")
                || FileManager.default.isExecutableFile(atPath: "/opt/homebrew/bin/kicad-cli")
                || FileManager.default.isExecutableFile(atPath: "/Applications/KiCad/kicad-cli") else {
            // Skip on hosts without kicad-cli.
            return
        }
        let detector = KiCadCLIDetector(runner: RealProcessRunner())
        let status = await detector.detect()
        // Should be ready (any dev machine with kicad-cli is on 10+).
        #expect(status.isReady, "Expected real kicad-cli to be detected as ready, got \(status)")
    }

    // MARK: - Helpers

    private func hasCandidatePath() -> Bool {
        Self.candidatePaths.contains { FileManager.default.isExecutableFile(atPath: $0) }
    }

    private func realCandidatePath() -> String? {
        Self.candidatePaths.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    private static let candidatePaths = [
        "/Applications/KiCad/kicad-cli",
        "/usr/local/bin/kicad-cli",
        "/opt/homebrew/bin/kicad-cli",
    ]
}

// MARK: - KiCadInstallStatus helpers

@Suite("KiCadInstallStatus")
struct KiCadInstallStatusTests {
    @Test("isReady is true only for .ready")
    func isReadyLogic() {
        #expect(KiCadInstallStatus.ready(path: "/x", version: "10.0").isReady == true)
        #expect(KiCadInstallStatus.notInstalled.isReady == false)
        #expect(KiCadInstallStatus.wrongVersion(found: "9.0").isReady == false)
    }

    @Test("minimumSupported is 10.0.0")
    func minimumVersion() {
        #expect(KiCadInstallStatus.minimumSupported == Version(major: 10, minor: 0, patch: 0))
    }

    @Test("Equatable works")
    func equality() {
        #expect(KiCadInstallStatus.notInstalled == .notInstalled)
        #expect(KiCadInstallStatus.ready(path: "/x", version: "10.0") == .ready(path: "/x", version: "10.0"))
        #expect(KiCadInstallStatus.ready(path: "/x", version: "10.0") != .ready(path: "/y", version: "10.0"))
    }

    @Test("debugDescription is human-readable")
    func debugDescription() {
        #expect(KiCadInstallStatus.notInstalled.debugDescription.contains("not found"))
        #expect(KiCadInstallStatus.wrongVersion(found: "9.0").debugDescription.contains("9.0"))
        #expect(KiCadInstallStatus.ready(path: "/x", version: "10.0").debugDescription.contains("/x"))
    }
}

// MARK: - MockProcessRunner

/// Mock ProcessRunner for tests.
///
/// Uses an internal actor for thread-safe state — NSLock is unavailable
/// from async contexts in Swift 6.2. Setters are async so callers await
/// them, guaranteeing ordering between setup and `run()`.
final class MockProcessRunner: ProcessRunner, @unchecked Sendable {
    private let state = MockProcessRunnerState()

    func run(executable: String, arguments: [String]) async throws -> ProcessResult {
        // Intercept `which` calls — they have arguments ["kicad-cli"].
        if executable.contains("which") && arguments.contains("kicad-cli") {
            if let cached = await state.lookupResponse("__which__") {
                return cached
            }
            if await state.containsFailure("__which__") {
                throw KiCadDetectorError.spawnFailed(reason: "mock: which not found")
            }
        }

        // Direct executable lookup.
        if let cached = await state.lookupResponse(executable) {
            return cached
        }
        if await state.containsFailure(executable) {
            throw KiCadDetectorError.spawnFailed(reason: "mock: executable not found")
        }

        // Default: simulate executable missing.
        throw KiCadDetectorError.spawnFailed(reason: "mock: no response for \(executable)")
    }

    // Async builders — caller awaits each.

    @discardableResult
    func setWhich(path: String) async -> Self {
        await state.setResponse("__which__", ProcessResult(stdout: path + "\n", stderr: "", exitCode: 0))
        return self
    }

    @discardableResult
    func setWhichFailing() async -> Self {
        await state.addFailure("__which__")
        return self
    }

    @discardableResult
    func setVersion(executable: String, stdout: String, stderr: String = "") async -> Self {
        await state.setResponse(executable, ProcessResult(stdout: stdout, stderr: stderr, exitCode: 0))
        return self
    }
}

actor MockProcessRunnerState {
    var responses: [String: ProcessResult] = [:]
    var failures: Set<String> = []

    func setResponse(_ key: String, _ result: ProcessResult) {
        responses[key] = result
    }

    func addFailure(_ key: String) {
        failures.insert(key)
    }

    func lookupResponse(_ key: String) -> ProcessResult? {
        responses[key]
    }

    func containsFailure(_ key: String) -> Bool {
        failures.contains(key)
    }
}
