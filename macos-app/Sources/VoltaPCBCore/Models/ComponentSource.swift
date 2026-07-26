//
//  ComponentSource.swift
//  VoltaPCBCore
//
//  Phase 1 / Task 0 — VoltaPCBCore Foundation
//
//  Source attribution — which provider contributed data for a component.
//  UnifiedComponent keeps an array of these so the merge engine can show
//  provenance ("pricing from Digi-Key, specs from Octopart") and so the
//  cache invalidation logic knows which provider to re-query when stale.
//
//  ponytail: value type with UUID identifier. Codable for cache persistence.
//

import Foundation

/// Source attribution — which provider contributed data for a component.
public struct ComponentSource: Sendable, Identifiable, Hashable, Codable {
    /// Stable unique ID for Identifiable conformance (SwiftUI lists, etc.).
    public let id: UUID

    /// Machine identifier of the provider (e.g., "digikey", "easyeda2kicad").
    public let provider: String

    /// Source-specific part ID (e.g., Digi-Key's "497-11924-ND").
    public let providerPartId: String

    /// When the provider last updated this record. Drives cache TTL.
    public let lastUpdated: Date

    /// Data quality score in [0.0, 1.0]. Merge engine uses this to pick the
    /// winning value when multiple providers disagree. First-party sources
    /// (manufacturer direct) typically score 0.95+; aggregators ~0.7.
    public let confidence: Double

    public init(
        id: UUID = UUID(),
        provider: String,
        providerPartId: String,
        lastUpdated: Date,
        confidence: Double
    ) {
        self.id = id
        self.provider = provider
        self.providerPartId = providerPartId
        self.lastUpdated = lastUpdated
        self.confidence = confidence
    }
}
