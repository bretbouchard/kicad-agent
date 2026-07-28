//
//  CADModelRef.swift
//  VoltaPCBCore
//
//  Phase 1 / Task 0 — VoltaPCBCore Foundation
//
//  Reference to a cached CAD model file on disk. CADModelProvider
//  implementations download footprints, symbols, and 3D models into
//  a local cache directory and return refs pointing at the files.
//  UnifiedComponent.cadModels is an array of these — one component may
//  have a KiCad footprint + symbol + WRL 3D model + STEP 3D model.
//
//  ponytail: path is String not URL. File paths cross Codable boundaries
//  more cleanly than URL (which has tricky percent-encoding behavior on
//  Codable). Convert to URL at the use site with fileURLWithPath.
//

import Foundation

/// Reference to a cached CAD model file on disk.
public struct CADModelRef: Sendable, Codable, Hashable {
    /// Absolute filesystem path to the cached CAD model file.
    public let filePath: String

    /// File format / KiCad library role.
    public let format: CADModelFormat

    /// Machine identifier of the provider that supplied this model
    /// (e.g., "easyeda", "kicad-http-libs").
    public let source: String

    /// When the file was cached. Used for cache eviction + freshness checks.
    public let cachedDate: Date

    public init(
        filePath: String,
        format: CADModelFormat,
        source: String,
        cachedDate: Date
    ) {
        self.filePath = filePath
        self.format = format
        self.source = source
        self.cachedDate = cachedDate
    }
}

/// Supported CAD model file formats. Values mirror the file extension
/// (without the leading dot) so rawValue can be used directly when
/// constructing paths.
public enum CADModelFormat: String, Sendable, Codable, CaseIterable {
    /// `.kicad_mod` — KiCad footprint (single footprint per file).
    case kicadMod

    /// `.kicad_sym` — KiCad symbol library (multiple symbols per file).
    case kicadSym

    /// `.wrl` — VRML 3D model (KiCad's preferred 3D format).
    case wrl

    /// `.step` — STEP AP214 3D model (mechanical CAD interchange).
    case step
}
