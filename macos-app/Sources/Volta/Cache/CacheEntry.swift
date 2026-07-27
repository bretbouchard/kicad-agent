//
//  CacheEntry.swift
//  Volta
//
//  Phase 1 / Task 5 — Two-Tier Cache
//
//  GRDB record for cached component data. TTL tiers control freshness:
//  pricing expires fastest (1h), CAD models never expire (permanent).
//

import Foundation
import GRDB

/// TTL tiers for different data types.
enum CacheTTL {
    /// CAD model data — permanent (never expires).
    static let cadModels: TimeInterval = .infinity
    /// Specs/description — 30 days.
    static let specs: TimeInterval = 2_592_000
    /// Pricing — 24 hours.
    static let pricing: TimeInterval = 86_400
    /// Stock — 1 hour.
    static let stock: TimeInterval = 3_600
    /// Product status — 7 days.
    static let productStatus: TimeInterval = 604_800
}

/// GRDB record for cached component data.
struct CacheEntry: Codable, FetchableRecord, MutablePersistableRecord {
    static let databaseTableName = "components"

    /// Primary key — auto-incremented.
    var id: Int64?

    /// Normalized part number (uppercase, no spaces/dashes).
    var partNumber: String

    /// Manufacturer name.
    var manufacturer: String

    /// JSON-encoded UnifiedComponent.
    var dataJson: String

    /// When this entry was cached.
    var cachedAt: Date

    /// TTL in seconds from cachedAt. Data older than cachedAt + ttl is stale.
    var ttlSeconds: TimeInterval

    /// ETag from the provider, if supported (for conditional refresh).
    var etag: String?

    enum Columns: String, ColumnExpression {
        case id, partNumber = "part_number", manufacturer
        case dataJson = "data_json", cachedAt = "cached_at"
        case ttlSeconds = "ttl_seconds", etag
    }

    enum CodingKeys: String, CodingKey {
        case id, partNumber = "part_number", manufacturer
        case dataJson = "data_json", cachedAt = "cached_at"
        case ttlSeconds = "ttl_seconds", etag
    }

    mutating func didInsert(_ inserted: InsertionSuccess) {
        id = inserted.rowID
    }

    /// Whether this entry has expired based on its TTL.
    var isStale: Bool {
        Date().timeIntervalSince(cachedAt) > ttlSeconds
    }
}
