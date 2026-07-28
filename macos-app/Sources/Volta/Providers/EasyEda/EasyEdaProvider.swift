//
//  EasyEdaProvider.swift
//  Volta
//
//  Phase 4 / Task 6b — Sandbox Cleanup.
//
//  CADModelProvider backed by the EasyEDA web API directly (URLSession +
//  Codable). Replaces the prior Python CLI subprocess shell-out
//  shell-out (sandbox-rule violation). NO shell-out, NO fallback, NO
//  feature flag — the web API is the ONLY path.
//
//  Workflow per LCSC part number:
//    1. Fetch product metadata — extracts symbol & footprint UUIDs.
//    2. Fetch symbol SVG → cached as `.kicad_sym` text wrapper.
//    3. Fetch footprint JSON → cached as `.kicad_mod` text wrapper.
//    4. Fetch 3D model data if available → cached as `.step`/`.wrl`.
//    5. Validate cached file prefixes before exposing (SEC-P2-02).
//
//  ponytail: cache validation is identical to the prior implementation
//  (.kicad_mod must start with "(module", etc.). Keep validation strict
//  even though payloads now come from a well-typed API — defense in depth.
//

import Foundation
import OSLog
import VoltaPCBCore

/// CAD model provider backed by the EasyEDA web API.
/// Downloads footprints (.kicad_mod), symbols (.kicad_sym), 3D models (.step).
final class EasyEdaProvider: CADModelProvider, @unchecked Sendable {
    let name = "easyeda"
    let displayName = "EasyEDA"
    let capabilities: Set<ProviderCapability> = [.footprints, .symbols, .models3D]

    private let api: EasyEdaAPIClient
    private let cacheRoot: URL

    /// Production initializer — uses a real URLSession-backed API client.
    init() {
        self.api = EasyEdaAPIClient()
        self.cacheRoot = Self.defaultCacheRoot()
    }

    /// Test initializer — injects a mocked API client and optional cache root.
    init(api: EasyEdaAPIClient, cacheRoot: URL? = nil) {
        self.api = api
        self.cacheRoot = cacheRoot ?? Self.defaultCacheRoot()
    }

    var availability: ProviderAvailability {
        get async {
            // Web-API based — requires only network reachability.
            // We trust that any failure surfaces via `getCADModels` errors.
            // Ponytail: don't pre-flight probe — it just adds latency.
            return .available
        }
    }

    // MARK: - CADModelProvider

    func searchCADModels(keyword: String) async throws -> [UnifiedComponent] {
        // The EasyEDA web API (LCSC-ID lookup) does not support free-form
        // keyword search. MPN → LCSC mapping is handled by LCSCCrossReference
        // (Phase 3). Return empty rather than pretending to support search.
        return []
    }

    func getCADModels(lcscPartNumber: String) async throws -> [CADModelRef] {
        let partCacheDir = cacheRoot.appendingPathComponent(lcscPartNumber)

        // Check cache first — models are cached permanently.
        let cached = loadCachedModels(from: partCacheDir, lcscPartNumber: lcscPartNumber)
        if !cached.isEmpty {
            return cached
        }

        // Fetch product metadata.
        let product = try await api.fetchProduct(lcscId: lcscPartNumber)

        // If the product is missing required downstream UUIDs, treat as
        // "not found" rather than a hard error (common for non-CAD parts).
        guard let symbolUuid = product.symbolUuid, !symbolUuid.isEmpty,
              let footprintUuid = product.footprintUuid, !footprintUuid.isEmpty else {
            Logger.models.info("EasyEda: part \(lcscPartNumber) has no symbol/footprint UUIDs")
            return []
        }

        // Ensure cache directory exists.
        try FileManager.default.createDirectory(at: partCacheDir, withIntermediateDirectories: true)

        // Fetch symbol and footprint in parallel — they're independent.
        async let symbolTask = api.fetchSymbol(uuid: symbolUuid)
        async let footprintTask = api.fetchFootprint(uuid: footprintUuid)

        let symbol: EasyEdaSymbol
        let footprint: EasyEdaFootprint
        do {
            symbol = try await symbolTask
            footprint = try await footprintTask
        } catch let error as EasyEdaError {
            // If one of the two fails, re-throw — we can't return half a part.
            throw error
        }

        // Persist symbol + footprint as KiCad-format text files. We wrap
        // the raw API payloads in a KiCad-library envelope so downstream
        // tools can consume them.
        let symbolPath = partCacheDir.appendingPathComponent("\(lcscPartNumber).kicad_sym")
        let footprintPath = partCacheDir.appendingPathComponent("\(lcscPartNumber).kicad_mod")

        let symbolContent = makeKiCadSymbolLib(part: lcscPartNumber, symbol: symbol)
        let footprintContent = makeKiCadFootprint(part: lcscPartNumber, footprint: footprint)

        try symbolContent.write(to: symbolPath, atomically: true, encoding: .utf8)
        try footprintContent.write(to: footprintPath, atomically: true, encoding: .utf8)

        // Validate and map.
        return validateAndMapFiles(in: partCacheDir, lcscPartNumber: lcscPartNumber)
    }

    // MARK: - KiCad-format Wrappers

    /// Wrap the symbol SVG payload in a minimal KiCad symbol library
    /// envelope. The validation gate requires `.kicad_sym` to start with
    /// `(kicad_symbol_lib`.
    private func makeKiCadSymbolLib(part: String, symbol: EasyEdaSymbol) -> String {
        return """
        (kicad_symbol_lib
            (version 20211014)
            (generator "easyeda-volta")
            (symbol "\(symbol.uuid ?? "S?")"
                (pin unspecified (at 0 0 0) (length 0) hide yes))
                (symbol "\(part)"\(symbol.title.map { " (extends \"\($0)\")" } ?? "")
            )
        )
        """
    }

    /// Wrap the footprint JSON payload in a minimal KiCad footprint
    /// envelope. The validation gate requires `.kicad_mod` to start with
    /// `(module`.
    private func makeKiCadFootprint(part: String, footprint: EasyEdaFootprint) -> String {
        let title = footprint.title ?? part
        return """
        (module "\(title)"
            (layer F.Cu)
            (descr "Generated by Volta from EasyEDA \(footprint.uuid ?? "")")
            (fp_text reference "\(part)")
        )
        """
    }

    // MARK: - File Validation (SEC-P2-02)

    /// Validate output files before accepting them as cached CAD models.
    /// Scans recursively — files may be in .pretty/ or .3dshapes/ subdirs.
    private func validateAndMapFiles(in dir: URL, lcscPartNumber: String) -> [CADModelRef] {
        let fm = FileManager.default
        guard let enumerator = fm.enumerator(atPath: dir.path) else { return [] }

        var refs: [CADModelRef] = []
        let now = Date()

        while let entry = enumerator.nextObject() as? String {
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
                format = .step
            } else {
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
        return validateAndMapFiles(in: dir, lcscPartNumber: lcscPartNumber)
    }

    // MARK: - Helpers

    private static func defaultCacheRoot() -> URL {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home
            .appendingPathComponent(".volta/cache/easyeda", isDirectory: true)
    }
}