//
//  JavaLocatorTests.swift
//  VoltaTests
//
//  Phase 253 Task 2 / Gate 2 P2 — JavaLocator unit tests.
//
//  Exercises JavaLocator's three response paths against stubbed
//  ProcessRunner output: success, empty stdout, non-zero exit.
//  Avoids any real subprocess invocation so tests are CI-safe.
//

import Testing
import Foundation
@testable import Volta

@Suite("JavaLocator")
struct JavaLocatorTests {

    // MARK: - Helpers

    /// Stub ProcessRunner that returns a single canned result for every
    /// run() invocation. Records the executable + arguments it was asked
    /// to invoke so tests can assert on what JavaLocator probed.
    final class StubRunner: ProcessRunner, @unchecked Sendable {
        struct Call: Equatable {
            let executable: String
            let arguments: [String]
        }

        let result: ProcessResult
        let throwingError: Error?
        private(set) var calls: [Call] = []

        init(result: ProcessResult, throwingError: Error? = nil) {
            self.result = result
            self.throwingError = throwingError
        }

        func run(executable: String, arguments: [String]) async throws -> ProcessResult {
            calls.append(Call(executable: executable, arguments: arguments))
            if let error = throwingError {
                throw error
            }
            return result
        }
    }

    /// Synthesise a fake $JAVA_HOME by creating a temp directory and a
    /// stub `bin/java` executable file. Returns (envValue, urlToCleanup).
    private static func makeFakeJavaHome() throws -> (envValue: String, cleanup: () -> Void) {
        let home = FileManager.default.temporaryDirectory
            .appendingPathComponent("java-locator-test-\(UUID().uuidString)")
        let bin = home.appendingPathComponent("bin")
        try FileManager.default.createDirectory(at: bin, withIntermediateDirectories: true)
        let java = bin.appendingPathComponent("java")
        try Data().write(to: java)
        // Ensure exists check passes via chmod. On macOS, executable bit
        // is set by FileManager when written — but chmod for safety.
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: java.path)
        return (home.path, {
            try? FileManager.default.removeItem(at: home)
        })
    }

    // MARK: - $JAVA_HOME path

    @Test("JAVA_HOME with executable bin/java returns that path")
    func javaHomeWins() async throws {
        let (home, cleanup) = try Self.makeFakeJavaHome()
        defer { cleanup() }
        setenv("JAVA_HOME", home, 1)
        defer { unsetenv("JAVA_HOME") }

        // Stub runner should never be called — JAVA_HOME is purely sync.
        let runner = StubRunner(result: ProcessResult(stdout: "", stderr: "", exitCode: 1))
        let locator = JavaLocator(runner: runner)

        let path = await locator.locate()
        #expect(path == "\(home)/bin/java")
        #expect(runner.calls.isEmpty, "JAVA_HOME path must not shell out")
    }

    @Test("JAVA_HOME pointing at non-executable bin/java falls through to /usr/libexec/java_home")
    func javaHomeNonExecutableFallsThrough() async throws {
        // Set JAVA_HOME to a path with no bin/java inside it.
        let bogus = "/tmp/nonexistent-jdk-\(UUID().uuidString)"
        setenv("JAVA_HOME", bogus, 1)
        defer { unsetenv("JAVA_HOME") }

        let runner = StubRunner(result: ProcessResult(
            stdout: "/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home\n",
            stderr: "",
            exitCode: 0
        ))
        let locator = JavaLocator(runner: runner)

        let path = await locator.locate()
        // The stub's stdout ends with the path. We can't actually exec that
        // path in CI (it may not exist), so just assert the runner was hit.
        #expect(runner.calls.count == 1)
        #expect(runner.calls[0].executable == "/usr/libexec/java_home")
        _ = path // path may be nil in CI if no JDK is installed; both outcomes acceptable
    }

    // MARK: - /usr/libexec/java_home path

    @Test("Empty stdout from /usr/libexec/java_home returns nil")
    func emptyStdoutReturnsNil() async {
        // Unset JAVA_HOME to ensure we probe /usr/libexec/java_home.
        unsetenv("JAVA_HOME")

        let runner = StubRunner(result: ProcessResult(stdout: "", stderr: "", exitCode: 0))
        let locator = JavaLocator(runner: runner)

        let path = await locator.locate()
        #expect(path == nil)
        #expect(runner.calls.count == 1)
        #expect(runner.calls[0].executable == "/usr/libexec/java_home")
    }

    @Test("Non-zero exit from /usr/libexec/java_home returns nil")
    func nonZeroExitReturnsNil() async {
        unsetenv("JAVA_HOME")

        let runner = StubRunner(result: ProcessResult(
            stdout: "",
            stderr: "Unable to find any JVMs",
            exitCode: 1
        ))
        let locator = JavaLocator(runner: runner)

        let path = await locator.locate()
        #expect(path == nil)
        #expect(runner.calls.count == 1)
    }

    @Test("Runner throwing an error returns nil without crashing")
    func runnerErrorReturnsNil() async {
        unsetenv("JAVA_HOME")

        struct FakeError: Error {}
        let runner = StubRunner(
            result: ProcessResult(stdout: "", stderr: "", exitCode: 0),
            throwingError: FakeError()
        )
        let locator = JavaLocator(runner: runner)

        let path = await locator.locate()
        #expect(path == nil)
    }

    @Test("Runner returns path but bin/java is missing — returns nil (sandbox-clean)")
    func stdoutPathMissingBinaryReturnsNil() async {
        unsetenv("JAVA_HOME")

        // Return a path that doesn't exist on disk.
        let fakeHome = "/this/path/does/not/exist/jdk-\(UUID().uuidString)"
        let runner = StubRunner(result: ProcessResult(
            stdout: "\(fakeHome)\n",
            stderr: "",
            exitCode: 0
        ))
        let locator = JavaLocator(runner: runner)

        let path = await locator.locate()
        #expect(path == nil, "Missing bin/java must not produce a fake path")
    }

    @Test("Trailing whitespace in stdout is trimmed")
    func stdoutWhitespaceTrimmed() async throws {
        unsetenv("JAVA_HOME")
        let (home, cleanup) = try Self.makeFakeJavaHome()
        defer { cleanup() }

        let runner = StubRunner(result: ProcessResult(
            stdout: "\n  \(home)  \n",
            stderr: "",
            exitCode: 0
        ))
        let locator = JavaLocator(runner: runner)

        let path = await locator.locate()
        #expect(path == "\(home)/bin/java")
    }
}
