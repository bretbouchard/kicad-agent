//
//  CADModelProvider.swift
//  VoltaPCBCore
//
//  Phase 1 / Task 0 — VoltaPCBCore Foundation
//
//  Protocol for providers that supply CAD models (footprints, symbols, 3D
//  models). Implementations translate their vendor-native model source
//  (EasyEDA JSON, KiCad HTTP library, SnapEDA file) into cached local
//  files plus CADModelRef records pointing at them.
//
//  Expected implementations (Phase 1+):
//    - EasyEdaProvider        (direct web API, LCSC lookup)
//    - KiCadHttpLibsProvider  (KiCad HTTP library API)
//    - SnapMagicFileProvider  (local .zip / individual file import)
//
//  Distinct from ComponentDataProvider: CAD providers take an LCSC part
//  number (or keyword) and return cached files + refs, not pricing/stock.
//  A component may have data from a ComponentDataProvider AND a
//  CADModelProvider — they're complementary, not interchangeable.
//
//  ponytail: getCADModels takes LCSC part number, not MPN. EasyEDA's
//  canonical key is LCSC ID; everything else (MPN, keyword) flows through
//  searchCADModels first. Keeps the high-fidelity path narrow.
//

import Foundation

/// Protocol for providers that supply CAD models (footprints, symbols, 3D models).
/// Implementations: EasyEdaProvider, KiCadHttpLibsProvider, SnapMagicFileProvider.
public protocol CADModelProvider: Sendable {
    /// Unique machine identifier (e.g., "easyeda"). Stable across
    /// releases — used as the cache partition key and CADModelRef.source.
    var name: String { get }

    /// User-facing display name (e.g., "EasyEDA"). Shown in Settings.
    var displayName: String { get }

    /// Capabilities this provider offers.
    var capabilities: Set<ProviderCapability> { get }

    /// Current availability state. Async — may probe CLI installation,
    /// network, or local cache before reporting.
    var availability: ProviderAvailability { get async }

    /// Download CAD models for a specific LCSC part number (e.g., "C2040").
    /// Returns refs to cached files; the caller stores them on
    /// UnifiedComponent.cadModels. Throws if the part is unknown or the
    /// download fails.
    func getCADModels(lcscPartNumber: String) async throws -> [CADModelRef]

    /// Search for CAD models by keyword (MPN, description). Returns unified
    /// components with `cadModels` populated but no pricing/stock. Used by
    /// the picker UI before the user has committed to a specific part.
    func searchCADModels(keyword: String) async throws -> [UnifiedComponent]
}
