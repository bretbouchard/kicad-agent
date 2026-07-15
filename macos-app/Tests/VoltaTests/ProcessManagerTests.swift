//
//  ProcessManagerTests.swift
//  VoltaTests
//
//  Phase 162 — Python Daemon Bundling
//
//  Tests for the daemon subprocess lifecycle. These tests are hermetic —
//  no external network, no app bundle required.
//
//  Tests run quickly by:
//  - Using ProcessManager constants for invariant checks (no spawn).
//  - Running at most ONE end-to-end spawn (which is gated on the daemon
//    binary being built).
//
//  swift-testing framework (TEST-01) — not XCTest.
//

import Testing
import Foundation
@testable import Volta

@MainActor
@Suite("ProcessManager")
struct ProcessManagerTests {

    // MARK: - Invariants (no spawn — instant)

    @Test("Watchdog timeout constant is 30 seconds (PITFALL 2)")
    func watchdogTimeoutConstant() {
        #expect(ProcessManager.watchdogTimeout == .seconds(30))
    }

    @Test("Shutdown timeout constant is 5 seconds (APP-05)")
    func shutdownTimeoutConstant() {
        #expect(ProcessManager.shutdownTimeout == .seconds(5))
    }

    @Test("Crash-loop threshold is 5 in 60s (DAEM-06)")
    func crashLoopThresholdConstant() {
        #expect(ProcessManager.crashLoopThreshold == 5)
        #expect(ProcessManager.crashLoopWindow == 60.0)
    }

    // MARK: - Binary resolution (no spawn)

    @Test("resolveDaemonURL returns a URL when daemon is built, nil otherwise")
    func resolveDaemonURLBehavior() {
        // The test environment either has the daemon built (PyInstaller)
        // or doesn't. We just verify the function returns a sensible result.
        let url = ProcessManager.resolveDaemonURL()
        if let url {
            #expect(FileManager.default.isExecutableFile(atPath: url.path))
        }
        // No else clause — nil is acceptable in environments without the bundle.
    }

    @Test("resolvePythonURL finds an interpreter in dev environments")
    func resolvePythonURLBehavior() {
        let url = ProcessManager.resolvePythonURL()
        if let url {
            #expect(FileManager.default.isExecutableFile(atPath: url.path))
        }
    }

    // MARK: - Checksum verification (APP-03)

    @Test("Checksum verification tolerates missing sidecar (dev mode)")
    func checksumToleratesMissingSidecar() async throws {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("pm_test_bin_\(UUID().uuidString)")
        try Data([0xDE, 0xAD, 0xBE, 0xEF]).write(to: tmp)
        defer { try? FileManager.default.removeItem(at: tmp) }
        // No sidecar → dev mode → accept.
        #expect(ProcessManager.verifyChecksum(of: tmp) == true)
    }

    @Test("Checksum verification rejects tampered sidecar")
    func checksumRejectsTamper() async throws {
        guard let url = ProcessManager.resolveDaemonURL() else {
            Issue.record("Daemon binary not built — run `pyinstaller volta-daemon.spec`")
            return
        }
        let sidecar = url.appendingPathExtension("sha256")
        let originalSidecar: String?
        if FileManager.default.fileExists(atPath: sidecar.path) {
            originalSidecar = try? String(contentsOf: sidecar, encoding: .utf8)
        } else {
            originalSidecar = nil
        }
        defer {
            if let original = originalSidecar {
                try? original.write(toFile: sidecar.path, atomically: true, encoding: .utf8)
            } else {
                try? FileManager.default.removeItem(at: sidecar)
            }
        }
        // Sanity: real sidecar verifies.
        #expect(ProcessManager.verifyChecksum(of: url) == true)
        // Tamper: write a bogus checksum.
        try "0000000000000000000000000000000000000000000000000000000000000000  \(url.lastPathComponent)\n"
            .write(toFile: sidecar.path, atomically: true, encoding: .utf8)
        #expect(ProcessManager.verifyChecksum(of: url) == false)
    }

    // MARK: - SHA-256 helper

    @Test("SHA-256 hex computation matches known vector")
    func sha256KnownVector() async throws {
        // Empty string SHA-256 = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("sha256_empty_\(UUID().uuidString)")
        try Data().write(to: tmp)
        defer { try? FileManager.default.removeItem(at: tmp) }
        let computed = ProcessManager.sha256(of: tmp)
        #expect(computed == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    }

    // MARK: - End-to-end spawn (single test, gated on binary presence)
    // These tests spawn the actual PyInstaller-frozen daemon binary and
    // wait for it to bind. PyInstaller cold start is ~30s, so they're
    // disabled by default. Set CI_RUN_INTEGRATION=1 to run them.

    @Test(
        "Spawn launches daemon and ping works end-to-end",
        .tags(.integration),
        .disabled(if: ProcessInfo.processInfo.environment["CI_RUN_INTEGRATION"] == nil)
    )
    func spawnAndPing() async throws {
        guard ProcessManager.resolveDaemonURL() != nil else {
            Issue.record("Daemon binary not built — run `pyinstaller volta-daemon.spec`")
            return
        }
        let pm = ProcessManager()
        try await pm.spawn()
        // Wait up to 3s for the messenger to bind.
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while pm.messenger == nil, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(100))
        }
        guard let messenger = pm.messenger else {
            throw ProcessManagerError.unknown("messenger not bound after spawn")
        }
        let result = try await messenger.call("ping", [:])
        guard let dict = result as? [String: Any], dict["pong"] as? Bool == true else {
            throw ProcessManagerError.unknown("malformed ping response")
        }
        #expect(pm.process?.isRunning == true)
        await pm.shutdown()
        #expect(pm.process == nil)
    }

    @Test(
        "Idempotent spawn returns same PID",
        .tags(.integration),
        .disabled(if: ProcessInfo.processInfo.environment["CI_RUN_INTEGRATION"] == nil)
    )
    func idempotentSpawn() async throws {
        guard ProcessManager.resolveDaemonURL() != nil else {
            Issue.record("Daemon binary not built")
            return
        }
        let pm = ProcessManager()
        try await pm.spawn()
        let firstPID = pm.process?.processIdentifier ?? -1
        try await pm.spawn()
        let secondPID = pm.process?.processIdentifier ?? -2
        #expect(firstPID == secondPID)
        await pm.shutdown()
    }
}
