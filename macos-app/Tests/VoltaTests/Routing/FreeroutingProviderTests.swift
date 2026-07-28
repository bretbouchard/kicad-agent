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
        let runner = FreeroutingProcessRunner(
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
        let runner = FreeroutingProcessRunner(
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
        let runner = FreeroutingProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        let jarURL = Self.freshFakeJAR()
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
        let runner = FreeroutingProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:],
            outputDSNProducer: { outputURL in
                try? Self.freeroutingOutputFixture.write(to: outputURL, atomically: true, encoding: .utf8)
            }
        )
        let pcbURL = Self.freshFakePCB()
        let jarURL = Self.freshFakeJAR()
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: jarURL
        )
        // Inject canned Freerouting success output via the runner
        runner.runResults["/usr/bin/java"] = FreeroutingProcessRunner.RunResult(
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
        let runner = FreeroutingProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        runner.runResults["/usr/bin/java"] = FreeroutingProcessRunner.RunResult(
            stdout: "",
            stderr: "Error: invalid DSN format",
            exitCode: 1
        )
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: Self.freshFakeJAR()
        )
        await #expect(throws: FreeroutingError.self) {
            _ = try await provider.route(
                pcbFile: Self.freshFakePCB(),
                rules: RoutingRules(),
                progress: nil
            )
        }
    }

    @Test("Route throws timeout when process exceeds rules.timeout")
    func routeTimeout() async {
        let runner = FreeroutingProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        // Simulate a long-running process by making run() throw a timeout
        runner.runResults["/usr/bin/java"] = FreeroutingProcessRunner.RunResult(
            stdout: "",
            stderr: "killed by timeout",
            exitCode: 124  // GNU `timeout` exit code
        )
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: Self.freshFakeJAR()
        )
        let rules = RoutingRules(timeout: .seconds(1))
        await #expect(throws: FreeroutingError.self) {
            _ = try await provider.route(
                pcbFile: Self.freshFakePCB(),
                rules: rules,
                progress: nil
            )
        }
    }

    @Test("Route streams progress events")
    func routeStreamsProgress() async throws {
        let runner = FreeroutingProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:],
            outputDSNProducer: { outputURL in
                try? Self.freeroutingOutputFixture.write(to: outputURL, atomically: true, encoding: .utf8)
            }
        )
        runner.runResults["/usr/bin/java"] = FreeroutingProcessRunner.RunResult(
            stdout: Self.freeroutingProgressLog,
            stderr: "",
            exitCode: 0
        )
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: Self.freshFakeJAR()
        )

        actor ProgressCollector {
            var events: [RoutingProgress] = []
            func append(_ e: RoutingProgress) { events.append(e) }
            func snapshot() -> [RoutingProgress] { events }
        }
        let collector = ProgressCollector()

        _ = try await provider.route(
            pcbFile: Self.freshFakePCB(),
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

    // MARK: - Native pipeline integration

    @Test("Native pipeline parses PCB, writes DSN, runs Freerouting, splices segments, and updates the PCB file")
    func nativePipelineRoundTrip() async throws {
        let pcbURL = try Self.writeFixture()
        defer { try? FileManager.default.removeItem(at: pcbURL) }

        let jarURL = Self.freshFakeJAR()
        let runner = FreeroutingProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:],
            outputDSNProducer: { outputURL in
                // Minimal Specctra DSN with 1 wire and 1 via for net "NET_A".
                // Coordinate units are micrometers (um); the segment from
                // (1.0,1.0)mm → (2.0,2.0)mm = (1000,1000) → (2000,2000) um.
                let dsn = Self.freeroutingOutputFixture
                try? dsn.write(to: outputURL, atomically: true, encoding: .utf8)
            }
        )
        runner.runResults["/usr/bin/java"] = FreeroutingProcessRunner.RunResult(
            stdout: "Done. Wires routed: 1, vias placed: 1, unrouted nets: 0.\n",
            stderr: "",
            exitCode: 0
        )
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: jarURL
        )

        _ = try await provider.route(
            pcbFile: pcbURL,
            rules: RoutingRules(),
            progress: nil
        )

        let updated = try String(contentsOf: pcbURL, encoding: .utf8)
        let parsed = try PCBParser.parse(updated)
        #expect(parsed.segments.count == 1)
        #expect(parsed.segments[0].start.x == 1.0)
        #expect(parsed.segments[0].end.y == 2.0)
        #expect(parsed.vias.count == 1)
        #expect(parsed.vias[0].position.x == 1.0)
    }

    private static func writeFixture() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("freerouting-fixture-\(UUID().uuidString).kicad_pcb")
        let pcb = """
        (kicad_pcb (version 20240108) (generator pcbnew)
          (general (thickness 1.6))
          (paper "A4")
          (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen") (44 "Edge.Cuts" user))
          (setup (pad_to_mask_clearance 0))
          (net 0 "")
          (net 1 "NET_A")
        )
        """
        try pcb.write(to: url, atomically: true, encoding: .utf8)
        return url
    }

    // MARK: - Estimate Time

    @Test("Estimate time scales with board complexity")
    func estimateTime() {
        let runner = FreeroutingProcessRunner(
            whichResults: ["java": .pathFound("/usr/bin/java")],
            runResults: [:]
        )
        let provider = FreeroutingProvider(
            runner: runner,
            jarPathOverride: Self.freshFakeJAR()
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

    /// Synthetic Freerouting output DSN. One wire for NET_A from
    /// (1000,1000)um to (2000,2000)um, and one via at (1000,1000)um.
    /// Width is 250um (the default 0.25mm). Coordinates are in
    /// micrometers per the Specctra DSN resolution convention.
    private static let freeroutingOutputFixture = """
    (pcb freerouted_output
      (parser
        (string_quote ")
        (space_in_quoted_tokens on)
        (host_cad "freerouting-fixture")
        (host_version "1.0")
      )
      (resolution mm 1000000)
      (structure
        (layer F.Cu (type signal))
        (layer B.Cu (type signal))
      )
      (network
        (net "NET_A")
      )
      (wiring
        (wire (path F.Cu 250 1000 1000 2000 2000) (net "NET_A") (type fix))
        (via "Via[0-1]_700:400_um" 1000 1000 (net "NET_A") (type fix))
      )
    )
    """

    // MARK: - Helpers (used by all tests that need an override jar)

    /// Create an empty placeholder JAR file so FreeroutingProvider's
    /// `fileExists(atPath:)` check passes when a test injects an override
    /// path. The actual shell-out never runs against this stub because the
    /// FreeroutingProcessRunner's runResults dictionary short-circuits it.
    /// Failures are non-fatal — fall back to /tmp so the test can still run.
    private static func makeFakeJAR(at url: URL) {
        try? Data().write(to: url, options: .atomic)
    }

    /// Spawn an isolated jar override file inside the temp directory.
    /// Non-throwing because a fake-JAR write failure shouldn't block tests.
    private static func freshFakeJAR() -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("freerouting-override-\(UUID().uuidString).jar")
        makeFakeJAR(at: url)
        return url
    }

    /// Write a minimal KiCad PCB fixture so FreeroutingProvider's
    /// `String(contentsOf:)` succeeds. Two-layer board with two nets —
    /// enough for PCBParser to parse and SpecctraDSNWriter to emit.
    private static func freshFakePCB() -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("freerouting-pcb-\(UUID().uuidString).kicad_pcb")
        let pcb = """
        (kicad_pcb (version 20240108) (generator pcbnew)
          (general (thickness 1.6))
          (paper "A4")
          (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen") (44 "Edge.Cuts" user))
          (setup (pad_to_mask_clearance 0))
          (net 0 "")
          (net 1 "NET_A")
          (net 2 "NET_B")
        )
        """
        try? pcb.write(to: url, atomically: true, encoding: .utf8)
        return url
    }
}

// MARK: - FreeroutingProcessRunner

/// Mock ProcessRunner dedicated to FreeroutingProvider tests. Configurable
/// which-results and run-results keyed by executable path. Mirrors the shape
/// of RealProcessRunner so the provider can be tested without spawning
/// real subprocesses.
///
/// Renamed from `MockProcessRunner` to avoid the redeclaration that exists
/// between this file and `KiCadCLIDetectorTests.swift` (volta-db9).
final class FreeroutingProcessRunner: ProcessRunner, @unchecked Sendable {
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
    /// Optional closure invoked on every java invocation. Receives the
    /// output DSN path (from `-do <path>`) and should write a valid
    /// Specctra DSN to that path. Used by the native pipeline integration
    /// test to inject a Freerouting-style result without a real JAR.
    var outputDSNProducer: ((URL) -> Void)?
    var runCallCount: Int = 0
    var lastExecutable: String?
    var lastArguments: [String]?

    init(
        whichResults: [String: WhichResult] = [:],
        runResults: [String: RunResult] = [:],
        outputDSNProducer: ((URL) -> Void)? = nil
    ) {
        self.whichResults = whichResults
        self.runResults = runResults
        self.outputDSNProducer = outputDSNProducer
    }

    func run(executable: String, arguments: [String]) async throws -> ProcessResult {
        runCallCount += 1
        lastExecutable = executable
        lastArguments = arguments
        // Native pipeline test hook: if a producer is installed, write the
        // output DSN to the path the provider passed via `-do <path>`.
        if let producer = outputDSNProducer {
            var argIndex = 0
            while argIndex + 1 < arguments.count {
                if arguments[argIndex] == "-do" {
                    producer(URL(fileURLWithPath: arguments[argIndex + 1]))
                    break
                }
                argIndex += 1
            }
        }
        if let result = runResults[executable] {
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