//
//  FreeroutingProvider.swift
//  Volta
//
//  Phase 253 Task 2 — Freerouting Routing Provider
//
//  RoutingProvider implementation that shells out to the Freerouting
//  autorouter (a Java JAR). Detects java + JAR via sandbox-clean
//  lookups (Bundle.main for JAR, /usr/libexec/java_home + JAVA_HOME
//  for Java), runs Freerouting with a Specctra DSN input/output pair,
//  and splices the resulting routes back into the original .kicad_pcb
//  via the pure-Swift SpecctraDSNReader + SegmentSplicer pipeline.
//
//  Detection strategy, in order:
//    1. $JAVA_HOME/bin/java (user-set env var = explicit user intent)
//    2. /usr/libexec/java_home (macOS system framework — not PATH)
//
//  JAR lookup:
//    1. Bundle.main.url(forResource: "freerouting", withExtension: "jar")
//    2. $FREEROUTING_JAR_PATH env var (dev-only escape hatch)
//
//  ponytail: zero IO during availability if previously-cached path is
//  still on disk. Re-probe only on demand (lazy invalidation via
//  app-launch reset).
//
//  Native Swift pipeline (no Python pcbnew at runtime):
//    .kicad_pcb → PCBParser → SpecctraDSNWriter.write → Freerouting JAR
//    Freerouting JAR → SpecctraDSNReader.read → SegmentSplicer.splice
//    → updated .kicad_pcb on disk.
//

import Foundation
import OSLog
import VoltaPCBCore

// MARK: - FreeroutingError

/// Errors raised by FreeroutingProvider. Each case maps to a specific
/// failure mode so the UI can show actionable install/setup guidance.
public enum FreeroutingError: Error, LocalizedError, Equatable {
    case javaNotFound
    case jarNotFound(searched: [String])
    case nonZeroExit(code: Int32, stderr: String)
    case timeout(seconds: Int)
    case invalidDSNOutput(path: String, reason: String)
    case splicingFailed(reason: String)

    public var errorDescription: String? {
        switch self {
        case .javaNotFound:
            return "Java runtime not found. Install OpenJDK: `brew install openjdk` and ensure `java` is on PATH."
        case .jarNotFound(let searched):
            let list = searched.joined(separator: "\n  • ")
            return "Freerouting JAR not found. Searched:\n  • \(list)\nDownload from freerouting.app or `brew install freerouting`."
        case .nonZeroExit(let code, let stderr):
            return "Freerouting exited with code \(code). stderr: \(stderr.prefix(500))"
        case .timeout(let seconds):
            return "Freerouting timed out after \(seconds) seconds. Increase rules.timeout or simplify the board."
        case .invalidDSNOutput(let path, let reason):
            return "Freerouting produced an invalid DSN at \(path): \(reason)"
        case .splicingFailed(let reason):
            return "Splicing Freerouting output into the .kicad_pcb failed: \(reason)"
        }
    }
}

// MARK: - FreeroutingProvider

/// RoutingProvider backed by Freerouting (Java autorouter).
/// Implements AD-1..AD-5 from PLAN.md: domain isolation, vendor-neutral
/// contract, long-running operation semantics, offline-first.
public final class FreeroutingProvider: RoutingProvider, @unchecked Sendable {

    // MARK: - RoutingProvider

    public let name = "freerouting"
    public let displayName = "Freerouting"
    public let capabilities: Set<RoutingCapability> = [.autoroute, .offline, .powerAware]

    // MARK: - Configuration

    /// Memory budget for the Java process. -Xmx2g is enough for boards
    /// up to ~500 components; larger boards should override via rules.
    private static let defaultJavaMemoryMB = 2048

    // MARK: - Injected deps

    private let runner: any ProcessRunner
    private let jarPathOverride: URL?
    private let dsnWriter: SpecctraDSNWriter
    private let dsnReader: SpecctraDSNReader
    private let splicer: SegmentSplicer

    // Cached detection results (refreshed lazily when invalidated).
    private var cachedJavaPath: String?
    private var cachedJarPath: URL?
    private var cacheValid: Bool = false

    // MARK: - Init

    /// Production initializer (uses the real Process runner).
    public convenience init(jarPathOverride: URL? = nil) {
        self.init(
            runner: RealProcessRunner(),
            jarPathOverride: jarPathOverride,
            dsnWriter: SpecctraDSNWriter(),
            dsnReader: SpecctraDSNReader(),
            splicer: SegmentSplicer()
        )
    }

    /// Designated initializer for tests in the same module.
    init(
        runner: any ProcessRunner,
        jarPathOverride: URL? = nil,
        dsnWriter: SpecctraDSNWriter = SpecctraDSNWriter(),
        dsnReader: SpecctraDSNReader = SpecctraDSNReader(),
        splicer: SegmentSplicer = SegmentSplicer()
    ) {
        self.runner = runner
        self.jarPathOverride = jarPathOverride
        self.dsnWriter = dsnWriter
        self.dsnReader = dsnReader
        self.splicer = splicer
    }

    // MARK: - Availability

    public var availability: ProviderAvailability {
        get async {
            // Honor the override for tests / settings-driven paths.
            if let override = jarPathOverride, FileManager.default.fileExists(atPath: override.path) {
                if (await probeJava()) != nil {
                    return .available
                } else {
                    return .unavailable(reason: FreeroutingError.javaNotFound.localizedDescription)
                }
            }

            // Production path: probe both java and JAR.
            guard let javaPath = await probeJava() else {
                return .unavailable(reason: FreeroutingError.javaNotFound.localizedDescription)
            }
            guard let jarPath = jarPath() else {
                return .unavailable(reason: FreeroutingError.jarNotFound(searched: [jarSearchSummary()]).localizedDescription)
            }
            cachedJavaPath = javaPath
            cachedJarPath = jarPath
            cacheValid = true
            return .available
        }
    }

    // MARK: - Route

    public func route(
        pcbFile: URL,
        rules: RoutingRules,
        progress: (@Sendable (RoutingProgress) -> Void)?
    ) async throws -> RoutingResult {
        progress?(.started)

        // 1. Ensure Java + JAR available.
        guard let javaPath = await probeJava() else {
            throw FreeroutingError.javaNotFound
        }
        let resolvedJarPath: URL
        if let override = jarPathOverride, FileManager.default.fileExists(atPath: override.path) {
            resolvedJarPath = override
        } else if let found = jarPath() {
            resolvedJarPath = found
        } else {
            throw FreeroutingError.jarNotFound(searched: [jarSearchSummary()])
        }

        // 2. Native Swift: parse the .kicad_pcb, generate DSN, stage workspace.
        let pcbText = try String(contentsOf: pcbFile, encoding: .utf8)
        let board = try PCBParser.parse(pcbText)
        let dsnText = dsnWriter.write(board)

        let workDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("freerouting-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: workDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: workDir) }

        let inputDSN = workDir.appendingPathComponent("input.dsn")
        let outputDSN = workDir.appendingPathComponent("output.dsn")
        let logFile = workDir.appendingPathComponent("freerouting.log")
        try dsnText.write(to: inputDSN, atomically: true, encoding: .utf8)

        // 3. Shell out to java -jar freerouting.jar -de input -do output.
        let arguments = [
            "-Xmx\(Self.defaultJavaMemoryMB)m",
            "-jar", resolvedJarPath.path,
            "-de", inputDSN.path,
            "-do", outputDSN.path,
            "-mt", "1",
            "--log-stdout"
        ]
        let started = Date()

        // Honor rules.timeout: we can't cancel the Process mid-run from
        // Swift safely, so we use a Task with timeout. The provider reports
        // a timeout if java doesn't exit within the budget.
        let timeoutSeconds = Int(rules.timeout.components.seconds)
        let result: ProcessResult
        do {
            result = try await withThrowingTaskGroup(of: ProcessResult?.self) { group in
                group.addTask { [runner, javaPath, arguments] in
                    try? await runner.run(executable: javaPath, arguments: arguments)
                }
                group.addTask {
                    try? await Task.sleep(for: rules.timeout)
                    return nil
                }
                // First non-nil result wins; nil from the timeout task means
                // we hit the budget without java finishing.
                for try await value in group {
                    if let value = value {
                        group.cancelAll()
                        return value
                    }
                }
                throw FreeroutingError.timeout(seconds: timeoutSeconds)
            }
        } catch let err as FreeroutingError {
            throw err
        } catch {
            throw FreeroutingError.nonZeroExit(code: -1, stderr: error.localizedDescription)
        }

        // 4. Verify exit code + output DSN exists.
        guard result.exitCode == 0 else {
            // GNU `timeout` exit code 124 ⇒ timed out
            if result.exitCode == 124 {
                throw FreeroutingError.timeout(seconds: timeoutSeconds)
            }
            throw FreeroutingError.nonZeroExit(code: result.exitCode, stderr: result.stderr)
        }
        guard FileManager.default.fileExists(atPath: outputDSN.path) else {
            throw FreeroutingError.invalidDSNOutput(path: outputDSN.path, reason: "Output DSN file was not created")
        }

        // 5. Persist log + parse metrics from output DSN.
        try (result.stdout + "\n" + result.stderr).write(to: logFile, atomically: true, encoding: .utf8)

        let outputText = try String(contentsOf: outputDSN, encoding: .utf8)
        let routedBoard: SpecctraBoard
        do {
            routedBoard = try dsnReader.read(outputText)
        } catch {
            throw FreeroutingError.invalidDSNOutput(path: outputDSN.path, reason: error.localizedDescription)
        }

        // 6. Splice Freerouting's output back into the original .kicad_pcb.
        let spliced: SplicedResult
        do {
            spliced = try splicer.splice(specctraBoard: routedBoard, into: pcbText)
        } catch {
            throw FreeroutingError.splicingFailed(reason: error.localizedDescription)
        }
        try spliced.pcbContent.write(to: pcbFile, atomically: true, encoding: .utf8)

        let metrics = parseMetrics(stdout: result.stdout, summary: parseOutputSummary(outputDSN))
        progress?(.completed)
        return RoutingResult(
            pcbFile: pcbFile,
            log: logFile,
            metrics: metrics,
            providerName: name,
            duration: Date().timeIntervalSince(started)
        )
    }

    public func estimateTime(board: PCBSummary) -> TimeInterval? {
        // Simple linear heuristic: components dominate, nets contribute too.
        // Returns seconds. Capped at 30 minutes (1800s).
        let baseSeconds = Double(board.componentCount) * 0.5 + Double(board.netCount) * 0.1
        let layerMultiplier = 1.0 + Double(max(0, board.layerCount - 2)) * 0.3
        let raw = baseSeconds * layerMultiplier
        return min(raw, 1800)
    }

    // MARK: - Detection helpers

    /// Probe for a working Java install. Returns the absolute path or nil.
    /// Sandbox-clean: only $JAVA_HOME + /usr/libexec/java_home (no PATH/which).
    func probeJava() async -> String? {
        // 1. $JAVA_HOME first (user-set env var = explicit user intent).
        if let home = ProcessInfo.processInfo.environment["JAVA_HOME"] {
            let url = URL(fileURLWithPath: "\(home)/bin/java")
            if FileManager.default.isExecutableFile(atPath: url.path) {
                return url.path
            }
        }
        // 2. /usr/libexec/java_home (macOS system framework — not PATH, not which).
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/libexec/java_home")
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
            guard process.terminationStatus == 0 else { return nil }
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            guard let home = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines), !home.isEmpty else { return nil }
            let javaURL = URL(fileURLWithPath: "\(home)/bin/java")
            return FileManager.default.isExecutableFile(atPath: javaURL.path) ? javaURL.path : nil
        } catch {
            return nil
        }
    }

    /// Resolve the Freerouting JAR URL via sandbox-clean lookups.
    /// 1. `Bundle.main.url(forResource: "freerouting", withExtension: "jar")`
    /// 2. `ProcessInfo.processInfo.environment["FREEROUTING_JAR_PATH"]` (dev escape hatch)
    func jarPath() -> URL? {
        if let bundled = Bundle.main.url(forResource: "freerouting", withExtension: "jar"),
           FileManager.default.fileExists(atPath: bundled.path) {
            return bundled
        }
        if let envPath = ProcessInfo.processInfo.environment["FREEROUTING_JAR_PATH"],
           FileManager.default.fileExists(atPath: envPath) {
            return URL(fileURLWithPath: envPath)
        }
        return nil
    }

    /// Human-readable description of where we looked for the JAR, for
    /// surfacing actionable install/setup guidance to the user.
    private func jarSearchSummary() -> String {
        let env = ProcessInfo.processInfo.environment["FREEROUTING_JAR_PATH"] ?? "(unset)"
        return "Bundle.main (freerouting.jar) and $FREEROUTING_JAR_PATH=\(env)"
    }

    // MARK: - Metric parsing

    /// Parse RoutingMetrics from Freerouting stdout. Format is loosely
    /// "Done. Wires routed: 42, vias placed: 8, unrouted nets: 2." — we
    /// also fall back to parsing the output DSN for accuracy.
    func parseMetrics(stdout: String, summary: DSNSummary?) -> RoutingMetrics {
        var wires = summary?.wireCount ?? 0
        var vias = summary?.viaCount ?? 0
        var unrouted = summary?.unroutedNets ?? []
        let layers = summary?.layers.count ?? 0

        // Regex-free scan: look for "Wires routed: N" / "vias placed: N" / "unrouted nets: N"
        if let range = stdout.range(of: "Wires routed:") {
            wires = parseTrailingNumber(after: "Wires routed:", in: stdout[range.upperBound...]) ?? wires
        }
        if let range = stdout.range(of: "vias placed:") {
            vias = parseTrailingNumber(after: "vias placed:", in: stdout[range.upperBound...]) ?? vias
        }
        if let range = stdout.range(of: "unrouted nets:") {
            // unrouted nets may be a single number; if summary has a list, prefer that.
            if summary?.unroutedNets.isEmpty ?? true {
                let count = parseTrailingNumber(after: "unrouted nets:", in: stdout[range.upperBound...]) ?? 0
                // `1...count` would trap if count == 0; clamp + skip when zero.
                let safeCount = max(0, count)
                if safeCount > 0 {
                    unrouted = (1...safeCount).map { "NET_\($0)" }
                }
            }
        }

        return RoutingMetrics(
            wiresRouted: wires,
            viasPlaced: vias,
            unroutedNets: unrouted,
            layers: layers
        )
    }

    /// Parse the integer after a marker substring. Returns nil if no int found.
    private func parseTrailingNumber(after marker: String, in text: Substring) -> Int? {
        var digits = ""
        for char in text {
            if char.isWhitespace { continue }
            if char.isNumber { digits.append(char) }
            else if !digits.isEmpty { break }
        }
        return digits.isEmpty ? nil : Int(digits)
    }

    /// Parse the output DSN if it exists, returning a DSNSummary for
    /// metric cross-checking. Returns nil if the file is missing.
    private func parseOutputSummary(_ url: URL) -> DSNSummary? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try? DSNConverter.parseSummary(at: url)
    }
}
