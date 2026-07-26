//
//  PricingData.swift
//  VoltaPCBCore
//
//  Phase 1 / Task 0 — VoltaPCBCore Foundation
//
//  Per-distributor pricing data. UnifiedComponent.pricing is an array of
//  these — one entry per distributor (Digi-Key, Mouser, LCSC, etc.) — so
//  the UI can show side-by-side price comparison and the BOM cost rollup
//  can pick the cheapest source per line item.
//
//  ponytail: tieredPricing is Optional<[PricingTier]> not empty array.
//  Distinction matters: nil = "no tier data published", [] = "verified
//  no tiers, flat pricing only". Merge engine treats these differently.
//

import Foundation

/// Per-distributor pricing data for a component.
public struct PricingData: Sendable, Codable, Hashable {
    /// Price at `minOrderQty`. Always populated — providers without unit
    /// price are useless to the BOM rollup.
    public let unitPrice: Double

    /// Minimum order quantity in the same units the distributor quotes
    /// (typically pieces, but could be reels/trays for some distributors).
    public let minOrderQty: Int

    /// Volume pricing tiers, sorted ascending by `minQty`. nil means the
    /// provider did not publish tier data; empty means provider confirmed
    /// flat pricing. The merge engine treats these differently.
    public let tieredPricing: [PricingTier]?

    /// ISO 4217 currency code (e.g., "USD", "CNY", "EUR").
    public let currency: String

    /// Display name of the distributor (e.g., "Digi-Key", "LCSC").
    public let distributor: String

    /// When the provider last updated this price. Drives cache TTL.
    public let lastUpdated: Date

    public init(
        unitPrice: Double,
        minOrderQty: Int,
        tieredPricing: [PricingTier]? = nil,
        currency: String,
        distributor: String,
        lastUpdated: Date
    ) {
        self.unitPrice = unitPrice
        self.minOrderQty = minOrderQty
        self.tieredPricing = tieredPricing
        self.currency = currency
        self.distributor = distributor
        self.lastUpdated = lastUpdated
    }
}

/// Volume pricing tier (e.g., "1-9: $2.50, 10-99: $2.00, 100+: $1.75").
/// Tiers are sorted ascending by `minQty`; the upper bound is implicit
/// (next tier's minQty - 1, or unbounded for the last tier).
public struct PricingTier: Sendable, Codable, Hashable {
    /// Quantity at which this price takes effect (inclusive).
    public let minQty: Int

    /// Per-unit price at this tier.
    public let unitPrice: Double

    public init(minQty: Int, unitPrice: Double) {
        self.minQty = minQty
        self.unitPrice = unitPrice
    }
}
