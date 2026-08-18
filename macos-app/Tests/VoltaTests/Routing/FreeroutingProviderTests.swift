//
//  FreeroutingProviderTests.swift
//  VoltaTests
//
//  Phase 253 Task 2 — Freerouting Provider TDD Tests
//
//  Verifies FreeroutingProvider detection, shell-out mechanics, error
//  mapping, and metric parsing. Uses MockProcessRunner to avoid real
//  java/jar dependencies in CI. Integration round-trip (real board →
//  DSN → Freerouting → DSN → board) is documented as a manual step
//  since it requires pcbnew bindings + a Freerouting JAR.
//

import Testing
import Foundation
@testable import Volta
import VoltaPCBCore

@Suite("Freerouting Provider")
struct FreeroutingProviderTests {
    private static func makeTempJarURL() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("freerouting-test-\(UUID().uuidString).jar")
        FileManager.default.createFile(atPath: url.path, contents: Data())
        return url
    }

    private static func makeRouteWorkspace() throws -> (pcbURL: URL, cleanupURL: URL) {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("freerouting-workspace-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let pcbURL = dir.appendingPathComponent("test-board.kicad_pcb")
        let dsnURL = dir.appendingPathComponent("input.dsn")
        FileManager.default.createFile(atPath: pcbURL.path, contents: Data())
        let dsn = """
        (pcb
          (layer F.Cu)
          (component U1)
        )
        """
        try dsn.write(to: dsnURL, atomically: true, encoding: .utf8)
        return (pcbURL, dir)
    }

    // MARK: - Identity

    @Test("Provider identity")
    func identity() {
        let provider = FreeroutingProvider()
        #expect(provider.name == "freerouting")
        #expect(provider.displayName == "Freerouting")
        #expect(provider.capabilities.contains(.autoroute))
        #expect(provider.capabilities.contains(.offline))
        #expect(provider.capabilities.contains(.powerAware))
        #expect(!provider.capabilities.contains(.cloud))
    }

    // MARK: - Availability

    @Test("Availability is .unavailable when java not on PATH")
    func availabilityNoJava() async {
        let runner = FreeroutingMockProcessRunner(
            whichResults: ["java": .whichFailed(exitCode: 1)],
            runResults: [:]
        )
        let provider = FreeroutingProvider(runner: runner)
        let avail = await provider.availability
        guard case .unavailable(let reason) = avail else {
            Issue.record("Expected .unavailable, got \(avail)")
            return
        }
        #expect(reason.contains("Java"))
    }

    @Test("Availability is .unavailable when java found but JAR missing")
    func availabilityNoJar() async {
        let runner = FreeroutingMockProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        let provider = FreeroutingProvider(runner: runner)
        let avail = await provider.availability
        guard case .unavailable(let reason) = avail else {
            Issue.record("Expected .unavailable, got \(avail)")
            return
        }
        #expect(reason.contains("Freerouting") || reason.contains("JAR") || reason.contains("jar"))
    }

    @Test("Availability is .available when java + JAR both found")
    func availabilityReady() async {
        let runner = FreeroutingMockProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        let jarURL = try! Self.makeTempJarURL()
        defer { try? FileManager.default.removeItem(at: jarURL) }
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: jarURL
        )
        let avail = await provider.availability
        #expect(avail == .available)
    }

    // MARK: - Route

    @Test("Route returns RoutingResult on success")
    func routeSuccess() async throws {
        let runner = FreeroutingMockProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        let workspace = try Self.makeRouteWorkspace()
        let pcbURL = workspace.pcbURL
        defer { try? FileManager.default.removeItem(at: workspace.cleanupURL) }
        let jarURL = try Self.makeTempJarURL()
        defer { try? FileManager.default.removeItem(at: jarURL) }
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: jarURL
        )
        // Inject canned Freerouting success output via the runner
        runner.runResults["/usr/bin/java"] = FreeroutingMockProcessRunner.RunResult(
            stdout: Self.freeroutingSuccessLog,
            stderr: "",
            exitCode: 0
        )

        let result = try await provider.route(
            pcbFile: pcbURL,
            rules: RoutingRules(),
            progress: nil
        )
        #expect(result.providerName == "freerouting")
        #expect(result.metrics.wiresRouted >= 0)
        #expect(result.metrics.viasPlaced >= 0)
        #expect(result.duration >= 0)
    }

    @Test("Route throws nonZeroExit on java failure")
    func routeNonZeroExit() async {
        let runner = FreeroutingMockProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        runner.runResults["/usr/bin/java"] = FreeroutingMockProcessRunner.RunResult(
            stdout: "",
            stderr: "Error: invalid DSN format",
            exitCode: 1
        )
        let workspace = try! Self.makeRouteWorkspace()
        defer { try? FileManager.default.removeItem(at: workspace.cleanupURL) }
        let jarURL = try! Self.makeTempJarURL()
        defer { try? FileManager.default.removeItem(at: jarURL) }
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: jarURL
        )
        await #expect(throws: FreeroutingError.self) {
            _ = try await provider.route(
                pcbFile: workspace.pcbURL,
                rules: RoutingRules(),
                progress: nil
            )
        }
    }

    @Test("Route throws timeout when process exceeds rules.timeout")
    func routeTimeout() async {
        let runner = FreeroutingMockProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        // Simulate a long-running process by making run() throw a timeout
        runner.runResults["/usr/bin/java"] = FreeroutingMockProcessRunner.RunResult(
            stdout: "",
            stderr: "killed by timeout",
            exitCode: 124  // GNU `timeout` exit code
        )
        let workspace = try! Self.makeRouteWorkspace()
        defer { try? FileManager.default.removeItem(at: workspace.cleanupURL) }
        let jarURL = try! Self.makeTempJarURL()
        defer { try? FileManager.default.removeItem(at: jarURL) }
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: jarURL
        )
        let rules = RoutingRules(timeout: .seconds(1))
        await #expect(throws: FreeroutingError.self) {
            _ = try await provider.route(
                pcbFile: workspace.pcbURL,
                rules: rules,
                progress: nil
            )
        }
    }

    @Test("Route streams progress events")
    func routeStreamsProgress() async throws {
        let runner = FreeroutingMockProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        runner.runResults["/usr/bin/java"] = FreeroutingMockProcessRunner.RunResult(
            stdout: Self.freeroutingProgressLog,
            stderr: "",
            exitCode: 0
        )
        let workspace = try Self.makeRouteWorkspace()
        defer { try? FileManager.default.removeItem(at: workspace.cleanupURL) }
        let jarURL = try Self.makeTempJarURL()
        defer { try? FileManager.default.removeItem(at: jarURL) }
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: jarURL
        )

        actor ProgressCollector {
            var events: [RoutingProgress] = []
            func append(_ e: RoutingProgress) { events.append(e) }
            func snapshot() -> [RoutingProgress] { events }
        }
        let collector = ProgressCollector()

        _ = try await provider.route(
            pcbFile: workspace.pcbURL,
            rules: RoutingRules(),
            progress: { event in
                Task { await collector.append(event) }
            }
        )

        // Give the actor a moment to drain pending appends.
        try await Task.sleep(for: .milliseconds(50))
        let events = await collector.snapshot()
        #expect(events.contains(.started))
        #expect(events.contains(.completed))
    }

    // MARK: - Estimate Time

    @Test("Estimate time scales with board complexity")
    func estimateTime() {
        let runner = FreeroutingMockProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        let jarURL = try! Self.makeTempJarURL()
        defer { try? FileManager.default.removeItem(at: jarURL) }
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: jarURL
        )
        let smallBoard = PCBSummary(
            componentCount: 10,
            netCount: 20,
            layerCount: 2,
            boardSize: Size2D(width: 50, height: 30)
        )
        let largeBoard = PCBSummary(
            componentCount: 200,
            netCount: 400,
            layerCount: 4,
            boardSize: Size2D(width: 200, height: 150)
        )

        let smallEstimate = provider.estimateTime(board: smallBoard) ?? 0
        let largeEstimate = provider.estimateTime(board: largeBoard) ?? 0

        #expect(smallEstimate > 0)
        #expect(largeEstimate > smallEstimate)
    }

    // MARK: - Error descriptions

    @Test("Error descriptions are human-readable")
    func errorDescriptions() {
        let javaMissing = FreeroutingError.javaNotFound
        #expect(javaMissing.localizedDescription.lowercased().contains("java"))

        let jarMissing = FreeroutingError.jarNotFound(searched: ["/tmp/missing.jar"])
        #expect(jarMissing.localizedDescription.contains("/tmp/missing.jar"))

        let timeout = FreeroutingError.timeout(seconds: 600)
        #expect(timeout.localizedDescription.contains("600"))
    }

    // MARK: - Fixtures

    /// Synthetic Freerouting stdout representing a successful 2-layer routing pass.
    private static let freeroutingSuccessLog = """
    Freerouting 2.1.0
    Loading DSN...
    Starting autorouter pass 1 of 5
    Optimizing route...
    Done. Wires routed: 42, vias placed: 8, unrouted nets: 2.
    """

    /// Synthetic Freerouting stdout with progress lines.
    private static let freeroutingProgressLog = """
    Freerouting 2.1.0
    Pass 1: 25% complete
    Pass 1: 50% complete
    Pass 1: 75% complete
    Done. Wires routed: 10, vias placed: 2, unrouted nets: 0.
    """
}

// MARK: - MockProcessRunner

/// Mock ProcessRunner for FreeroutingProvider tests. Configurable
/// which-results and run-results keyed by executable path. Mirrors
/// the shape of RealProcessRunner so the provider can be tested
/// without spawning real subprocesses.
final class FreeroutingMockProcessRunner: ProcessRunner, @unchecked Sendable {
    /// What `which <executable>` should return per binary name.
    enum WhichResult: Equatable, Sendable {
        case pathFound(String)
        case whichFailed(exitCode: Int32)
    }

    /// Per-run result keyed by executable path.
    struct RunResult: Equatable, Sendable {
        let stdout: String
        let stderr: String
        let exitCode: Int32
    }

    var whichResults: [String: WhichResult]
    var runResults: [String: RunResult]
    var runCallCount: Int = 0
    var lastExecutable: String?
    var lastArguments: [String]?

    init(whichResults: [String: WhichResult] = [:], runResults: [String: RunResult] = [:]) {
        self.whichResults = whichResults
        self.runResults = runResults
    }

    func run(executable: String, arguments: [String]) async throws -> ProcessResult {
        runCallCount += 1
        lastExecutable = executable
        lastArguments = arguments
        if let result = runResults[executable] {
            if result.exitCode == 0,
               let outputIndex = arguments.firstIndex(of: "-do"),
               arguments.indices.contains(outputIndex + 1) {
                let outputPath = arguments[outputIndex + 1]
                if !FileManager.default.fileExists(atPath: outputPath) {
                    let output = """
                    (pcb
                      (layer F.Cu)
                      (wire (path a b))
                      (via x y)
                    )
                    """
                    try output.write(toFile: outputPath, atomically: true, encoding: .utf8)
                }
            }
            return ProcessResult(
                stdout: result.stdout,
                stderr: result.stderr,
                exitCode: result.exitCode
            )
        }
        // Default: success with empty output.
        return ProcessResult(stdout: "", stderr: "", exitCode: 0)
    }

    /// Simulate `which <binary>` invocation. Looks up the whichResults
    /// dict, then runs `/usr/bin/which <binary>` or `/usr/bin/env which <binary>`
    /// to satisfy the real provider's probe sequence.
    func which(_ binary: String) async throws -> ProcessResult {
        guard let result = whichResults[binary] else {
            return ProcessResult(stdout: "", stderr: "", exitCode: 1)
        }
        switch result {
        case .pathFound(let path):
            return ProcessResult(stdout: path, stderr: "", exitCode: 0)
        case .whichFailed(let code):
            return ProcessResult(stdout: "", stderr: "", exitCode: code)
        }
    }
}
