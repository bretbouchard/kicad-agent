//
//  StockData.swift
//  VoltaPCBCore
//
//  Phase 1 / Task 0 — VoltaPCBCore Foundation
//
//  Per-distributor stock availability. UnifiedComponent.stock is an array
//  of these — one entry per distributor — so the UI can highlight
//  out-of-stock parts and the BOM analyzer can flag single-source risk.
//
//  ponytail: leadTime is Optional<String> not Optional<Int>. Distributors
//  publish lead times as ranges ("2-3 weeks") or text ("contact sales"),
//  not deterministic integers. Forcing a parsed integer would lose info.
//

import Foundation

/// Per-distributor stock availability.
public struct StockData: Sendable, Codable, Hashable {
    /// Quantity on hand as reported by the distributor. Zero is a valid
    /// value (explicitly out of stock) — distinct from nil which would
    /// mean "not reported".
    public let quantityAvailable: Int

    /// Display name of the distributor (e.g., "Digi-Key", "Mouser").
    public let distributor: String

    /// Free-form lead time string as published (e.g., "2-3 weeks",
    /// "immediate", "contact sales"). nil if not reported.
    public let leadTime: String?

    /// When the provider last updated this stock figure. Drives cache TTL.
    public let lastUpdated: Date

    public init(
        quantityAvailable: Int,
        distributor: String,
        leadTime: String? = nil,
        lastUpdated: Date
    ) {
        self.quantityAvailable = quantityAvailable
        self.distributor = distributor
        self.leadTime = leadTime
        self.lastUpdated = lastUpdated
    }
}
