//
//  ComponentDataProvider.swift
//  VoltaPCBCore
//
//  Phase 1 / Task 0 — VoltaPCBCore Foundation
//
//  Protocol for providers that supply component data (pricing, stock,
//  specs, datasheets). Implementations translate their vendor-native
//  response shape into UnifiedComponent at the provider boundary so
//  nothing vendor-specific escapes the provider module.
//
//  Expected implementations (Phase 1+):
//    - DigiKeyProvider        (REST API, OAuth2)
//    - MouserProvider         (REST API, API key)
//    - OctopartProvider       (REST API, API key — aggregator)
//    - JlcpartsLocalProvider  (local SQLite cache, no network)
//
//  ponytail: two methods, not five. search + getDetails covers the entire
//  component-data surface; pricing/stock/specs ride along as fields on
//  UnifiedComponent rather than separate protocol methods. Keeps the
//  protocol narrow and lets new providers grow incrementally.
//

import Foundation

/// Protocol for providers that supply component data (pricing, stock, specs).
/// Implementations: DigiKeyProvider, MouserProvider, OctopartProvider, JlcpartsLocalProvider.
public protocol ComponentDataProvider: Sendable {
    /// Unique machine identifier (e.g., "digikey"). Stable across releases —
    /// used as the cache partition key and ComponentSource.provider value.
    var name: String { get }

    /// User-facing display name (e.g., "Digi-Key"). Shown in Settings and
    /// the provider-picker UI.
    var displayName: String { get }

    /// Capabilities this provider offers. Drives UI filtering ("show only
    /// providers with pricing") and merge-engine priority.
    var capabilities: Set<ProviderCapability> { get }

    /// Current availability state. Async — may probe network, credentials,
    /// or local cache before reporting. Polled by the registry on app launch
    /// and after Settings changes.
    var availability: ProviderAvailability { get async }

    /// Search for components by keyword (MPN, description, partial match).
    /// Returns unified components; the caller (merge engine) is responsible
    /// for cross-provider dedup by MPN.
    func search(keyword: String) async throws -> [UnifiedComponent]

    /// Get detailed information for a specific part number. Returns nil if
    /// the provider has no record of the part. The merge engine calls this
    /// against all available providers in parallel and merges results.
    func getDetails(partNumber: String) async throws -> UnifiedComponent?
}
