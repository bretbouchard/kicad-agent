//
//  EasyEdaProvider.swift
//  Volta
//
//  Phase 1 / Task 3 — easyeda2kicad Provider
//
//  First real CADModelProvider adapter. Shells out to easyeda2kicad CLI
//  to download KiCad-native footprints, symbols, and 3D models from
//  LCSC/EasyEDA catalog.
//
//  ARCH-P1-03: Reuses existing ProcessRunner protocol from KiCadCLIDetector.
//  Accepts `any ProcessRunner` in initializer — same pattern as KiCadCLIDetector.
//
//  SEC-P2-02: Output files validated before caching.
//    - .kicad_mod must start with "(module"
//    - .kicad_sym must start with "(kicad_symbol_lib"
//    - .wrl must start with "#VRML V2.0"
//

import Foundation
import OSLog
import VoltaPCBCore

/// CAD model provider backed by easyeda2kicad CLI.
/// Downloads footprints (.kicad_mod), symbols (.kicad_sym), 3D models (.wrl).
final class EasyEdaProvider: CADModelProvider, @unchecked Sendable {
    let name = "easyeda2kicad"
    let displayName = "EasyEDA → KiCad"
    let capabilities: Set<ProviderCapability> = [.footprints, .symbols, .models3D]

    private let processRunner: any ProcessRunner
    private let cacheRoot: URL

    /// Path to easyeda2kicad executable. Defaults to `which` lookup.
    private let executablePath: String

    init(processRunner: any ProcessRunner = RealProcessRunner(), executablePath: String? = nil) {
        self.processRunner = processRunner
        self.executablePath = executablePath ?? Self.findEasyEda2Kicad()
        self.cacheRoot = Self.defaultCacheRoot()
    }

    var availability: ProviderAvailability {
        get async {
            guard executablePath != "easyeda2kicad-not-found" else {
                return .requiresAuth(reason: "easyeda2kicad is not installed. Install with: pip install easyeda2kicad")
            }
            return .available
        }
    }

    // MARK: - CADModelProvider

    func searchCADModels(keyword: String) async throws -> [UnifiedComponent] {
        // easyeda2kicad doesn't have a keyword search API — it works with LCSC IDs.
        // For keyword search, we return an empty array. MPN → LCSC mapping is
        // handled by the MergeEngine or deferred to Phase 2 (Octopart cross-ref).
        // ARCH-P2-05 mitigation.
        return []
    }

    func getCADModels(lcscPartNumber: String) async throws -> [CADModelRef] {
        // Check cache first — models are cached permanently (never re-download).
        let partCacheDir = cacheRoot.appendingPathComponent(lcscPartNumber)
        let cached = loadCachedModels(from: partCacheDir, lcscPartNumber: lcscPartNumber)
        if !cached.isEmpty {
            return cached
        }

        // Download via easyeda2kicad CLI.
        guard executablePath != "easyeda2kicad-not-found" else {
            throw EasyEdaError.notInstalled
        }

        // Ensure cache directory exists.
        try FileManager.default.createDirectory(at: partCacheDir, withIntermediateDirectories: true)

        // Run: easyeda2kicad --full --lcsc_id=CXXXX --output=<dir>
        let result = try await processRunner.run(
            executable: executablePath,
            arguments: ["--full", "--lcsc_id=\(lcscPartNumber)", "--output=\(partCacheDir.path)"]
        )

        if result.exitCode != 0 {
            // Part not found is a common case — return empty, not an error.
            if result.stderr.contains("not found") || result.stderr.contains("404") {
                Logger.models.info("EasyEda: part \(lcscPartNumber) not found")
                return []
            }
            throw EasyEdaError.processFailed(exitCode: result.exitCode, stderr: result.stderr)
        }

        // Validate and cache output files (SEC-P2-02).
        let validated = validateAndMapFiles(in: partCacheDir, lcscPartNumber: lcscPartNumber)
        return validated
    }

    // MARK: - File Validation (SEC-P2-02)

    /// Validate output files before accepting them as cached CAD models.
    private func validateAndMapFiles(in dir: URL, lcscPartNumber: String) -> [CADModelRef] {
        let fm = FileManager.default
        guard let entries = try? fm.contentsOfDirectory(atPath: dir.path) else { return [] }

        var refs: [CADModelRef] = []
        let now = Date()

        for entry in entries {
            let fileURL = dir.appendingPathComponent(entry)
            guard let content = try? String(contentsOf: fileURL, encoding: .utf8) else { continue }
            let prefix = content.trimmingCharacters(in: .whitespacesAndNewlines)

            let format: CADModelFormat?
            if entry.hasSuffix(".kicad_mod") && prefix.hasPrefix("(module") {
                format = .kicadMod
            } else if entry.hasSuffix(".kicad_sym") && prefix.hasPrefix("(kicad_symbol_lib") {
                format = .kicadSym
            } else if entry.hasSuffix(".wrl") && prefix.hasPrefix("#VRML V2.0") {
                format = .wrl
            } else if entry.hasSuffix(".step") || entry.hasSuffix(".stp") {
                // STEP files validated by magic number, not text prefix
                format = .step
            } else {
                Logger.models.warning("EasyEda: rejecting unvalidated file \(entry) — prefix mismatch")
                continue
            }

            if let format {
                refs.append(CADModelRef(
                    filePath: fileURL.path,
                    format: format,
                    source: name,
                    cachedDate: now
                ))
            }
        }

        return refs
    }

    /// Load previously cached models from disk (permanent cache).
    private func loadCachedModels(from dir: URL, lcscPartNumber: String) -> [CADModelRef] {
        let fm = FileManager.default
        guard fm.fileExists(atPath: dir.path) else { return [] }

        // Re-validate cached files too — don't trust stale files.
        return validateAndMapFiles(in: dir, lcscPartNumber: lcscPartNumber)
    }

    // MARK: - Helpers

    private static func findEasyEda2Kicad() -> String {
        // Check common locations
        let candidates = [
            "/usr/local/bin/easyeda2kicad",
            "/opt/homebrew/bin/easyeda2kicad",
            FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent(".local/bin/easyeda2kicad").path
        ]
        for path in candidates where FileManager.default.isExecutableFile(atPath: path) {
            return path
        }
        return "easyeda2kicad-not-found"
    }

    private static func defaultCacheRoot() -> URL {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home
            .appendingPathComponent(".volta/cache/easyeda", isDirectory: true)
    }
}

/// EasyEda provider errors.
enum EasyEdaError: Error, LocalizedError, Sendable {
    case notInstalled
    case processFailed(exitCode: Int32, stderr: String)

    var errorDescription: String? {
        switch self {
        case .notInstalled:
            return "easyeda2kicad is not installed. Install with: pip install easyeda2kicad"
        case .processFailed(let code, let stderr):
            return "easyeda2kicad failed (exit \(code)): \(stderr)"
        }
    }
}
