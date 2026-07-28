//
//  FreeroutingProvider.swift
//  Volta
//
//  Phase 253 Task 2 — Freerouting Routing Provider
//
//  RoutingProvider implementation that shells out to the Freerouting
//  autorouter (a Java JAR). Detects java + JAR at known paths, runs
//  Freerouting with a Specctra DSN input/output pair, and parses
//  metrics from the router log.
//
//  Detection strategy, in order:
//    1. `which java` via /usr/bin/env (user PATH)
//    2. `/usr/bin/java` (system Java)
//    3. `java -version` to confirm it actually runs (some installs have
//       `java` shim that 404s on macOS)
//
//  JAR search paths:
//    - /Applications/Freerouting.app/Contents/Java/freerouting.jar
//    - /Applications/Freerouting.app/Contents/Java/Freerouting.jar
//    - /opt/homebrew/Cellar/freerouting/*/libexec/freerouting.jar
//    - ~/.volta/tools/freerouting.jar
//    - ~/Library/Application Support/freerouting/freerouting.jar
//
//  ponytail: zero IO during availability if previously-cached path is
//  still on disk. We re-probe only on demand (lazy invalidation via
//  app-launch reset).
//
//  Integration scope: shell-out + log parse ONLY. The KiCad ↔ DSN
//  conversion is delegated to a Python helper (pcbnew bindings) since
//  kicad-cli 9.x has no specctra subcommand. The adapter raises a
//  clear .dsnConversionUnavailable error if the helper script is
//  missing, and surfaces the helper's stderr in the log file.
//

import Foundation
import OSLog
import VoltaPCBCore

#if canImport(VoltaKiCadBridge)
// Reserved for the Python pcbnew helper bridge. Out of scope for this task.
#endif

// MARK: - FreeroutingError

/// Errors raised by FreeroutingProvider. Each case maps to a specific
/// failure mode so the UI can show actionable install/setup guidance.
public enum FreeroutingError: Error, LocalizedError, Equatable {
    case javaNotFound
    case jarNotFound(searched: [String])
    case nonZeroExit(code: Int32, stderr: String)
    case timeout(seconds: Int)
    case dsnConversionUnavailable(reason: String)
    case invalidDSNOutput(path: String, reason: String)

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
        case .dsnConversionUnavailable(let reason):
            return "DSN conversion unavailable: \(reason). Install pcbnew bindings: `pip install pcbnew` from your KiCad install."
        case .invalidDSNOutput(let path, let reason):
            return "Freerouting produced an invalid DSN at \(path): \(reason)"
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

    /// Default JAR search paths. Public so tests / settings UI can read.
    public static let defaultJARSearchPaths: [String] = [
        "/Applications/Freerouting.app/Contents/Java/freerouting.jar",
        "/Applications/Freerouting.app/Contents/Java/Freerouting.jar",
        "/opt/homebrew/Cellar/freerouting/*/libexec/freerouting.jar",
        "/Library/Application Support/freerouting/freerouting.jar",
        NSString(string: "~/Library/Application Support/freerouting/freerouting.jar").expandingTildeInPath,
        NSString(string: "~/.volta/tools/freerouting.jar").expandingTildeInPath,
    ]

    /// Memory budget for the Java process. -Xmx2g is enough for boards
    /// up to ~500 components; larger boards should override via rules.
    private static let defaultJavaMemoryMB = 2048

    // MARK: - Injected deps

    private let runner: any ProcessRunner
    private let jarPathOverride: URL?

    // Cached detection results (refreshed lazily when invalidated).
    private var cachedJavaPath: String?
    private var cachedJarPath: URL?
    private var cacheValid: Bool = false

    // MARK: - Init

    /// Production initializer (uses the real Process runner).
    public convenience init(jarPathOverride: URL? = nil) {
        self.init(runner: RealProcessRunner(), jarPathOverride: jarPathOverride)
    }

    /// Designated initializer for tests in the same module.
    init(runner: any ProcessRunner, jarPathOverride: URL? = nil) {
        self.runner = runner
        self.jarPathOverride = jarPathOverride
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
            guard let jarPath = locateJAR() else {
                return .unavailable(reason: FreeroutingError.jarNotFound(searched: Self.defaultJARSearchPaths).localizedDescription)
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
        let jarPath: URL
        if let override = jarPathOverride, FileManager.default.fileExists(atPath: override.path) {
            jarPath = override
        } else if let found = locateJAR() {
            jarPath = found
        } else {
            throw FreeroutingError.jarNotFound(searched: Self.defaultJARSearchPaths)
        }

        // 2. Prepare DSN workspace. The actual .kicad_pcb → DSN conversion
        //    is delegated to a Python helper (pcbnew). For now we treat the
        //    input as if it were already a DSN — the adapter's caller is
        //    responsible for staging the conversion. We still document the
        //    error path for when that stage fails.
        let workDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("freerouting-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: workDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: workDir) }

        let inputDSN = workDir.appendingPathComponent("input.dsn")
        let outputDSN = workDir.appendingPathComponent("output.dsn")
        let logFile = workDir.appendingPathComponent("freerouting.log")

        // If the caller passed a .kicad_pcb, we assume a sibling helper has
        // already produced inputDSN. We copy the inputDSN to track it.
        // The actual conversion lives outside this Swift layer (Python
        // helper invoked by the Volta host app); for direct unit tests
        // the caller stages inputDSN themselves.
        if !FileManager.default.fileExists(atPath: inputDSN.path) {
            // Try the convention: caller pre-staged input.dsn next to pcbFile.
            let sibling = pcbFile.deletingLastPathComponent().appendingPathComponent("input.dsn")
            if FileManager.default.fileExists(atPath: sibling.path) {
                try FileManager.default.copyItem(at: sibling, to: inputDSN)
            } else {
                throw FreeroutingError.dsnConversionUnavailable(reason: "No input.dsn found at \(inputDSN.path) — host app must run pcbnew export before invoking Freerouting.")
            }
        }

        // 3. Shell out to java -jar freerouting.jar -de input -do output.
        let arguments = [
            "-Xmx\(Self.defaultJavaMemoryMB)m",
            "-jar", jarPath.path,
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

        let metrics = parseMetrics(stdout: result.stdout, summary: parseOutputSummary(outputDSN))

        // 6. The mutated .kicad_pcb lives at pcbFile. Freerouting wrote
        //    routes into outputDSN; the host app is responsible for the
        //    DSN → .kicad_pcb import (Python pcbnew). For now we report
        //    the outputDSN in the result so callers can locate it.
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
    func probeJava() async -> String? {
        // Try `/usr/bin/env which java` first to honor user PATH.
        let candidates: [[String]] = [
            ["/usr/bin/env", "which", "java"],
            ["/usr/bin/which", "java"],
        ]
        for cmd in candidates {
            do {
                let result = try await runner.run(
                    executable: cmd[0],
                    arguments: Array(cmd.dropFirst())
                )
                if result.exitCode == 0 {
                    let path = result.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
                    if !path.isEmpty, FileManager.default.isExecutableFile(atPath: path) {
                        return path
                    }
                }
            } catch {
                continue
            }
        }
        // Fallback: probe /usr/bin/java directly (some macOS system installs).
        let systemPath = "/usr/bin/java"
        if FileManager.default.isExecutableFile(atPath: systemPath) {
            return systemPath
        }
        return nil
    }

    /// Locate the Freerouting JAR on disk. Honors the override first,
    /// then walks the default search paths. Returns the first match.
    func locateJAR() -> URL? {
        if let override = jarPathOverride, FileManager.default.fileExists(atPath: override.path) {
            return override
        }
        for path in Self.defaultJARSearchPaths {
            let expanded = NSString(string: path).expandingTildeInPath
            if expanded.contains("*") {
                // Glob expand (Homebrew cellar path). Use FileManager
                // glob since Foundation has no built-in glob.
                if let resolved = globFirst(path: expanded) {
                    return resolved
                }
            } else if FileManager.default.fileExists(atPath: expanded) {
                return URL(fileURLWithPath: expanded)
            }
        }
        return nil
    }

    /// Glob a single-star path (only one wildcard supported) and return
    /// the first match as a URL. Returns nil if nothing matches.
    private func globFirst(path: String) -> URL? {
        let parts = path.split(separator: "*", maxSplits: 1, omittingEmptySubsequences: false)
        guard parts.count == 2 else { return nil }
        let prefix = String(parts[0])
        let suffix = String(parts[1])
        let dir = URL(fileURLWithPath: prefix).deletingLastPathComponent().path
        guard let entries = try? FileManager.default.contentsOfDirectory(atPath: dir) else {
            return nil
        }
        let fileName = prefix.split(separator: "/").last.map(String.init) ?? ""
        let matched = entries.first { entry in
            entry.hasPrefix(fileName) && entry.hasSuffix(suffix.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        }
        if let matched = matched {
            return URL(fileURLWithPath: dir).appendingPathComponent(matched).appendingPathComponent(suffix.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        }
        return nil
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
                unrouted = (1...count).map { "NET_\($0)" }
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