//
//  CacheManager.swift
//  Volta
//
//  Phase 1 / Task 5 — Two-Tier Cache
//
//  GRDB-backed SQLite cache for component data + filesystem cache for
//  CAD model files. TTL-based freshness with stale-while-revalidate.
//
//  ARCH-P1-02: Cache lives in Volta target (not VoltaPCBCore).
//  VoltaPCBCore stays dependency-free.
//
//  ARCH-P2-04: Stale-while-revalidate pattern:
//  - On cache hit: show cached data immediately (instant UI)
//  - Background: check if data exceeds TTL → silent refresh
//  - If fresh response: update cache silently
//  - If network fails: keep showing cached data with stale indicator
//

import Foundation
import GRDB
import OSLog
import VoltaPCBCore

/// Two-tier cache: SQLite metadata + filesystem CAD files.
final class CacheManager: @unchecked Sendable {
    private let dbPool: DatabasePool
    private let cacheDir: URL

    /// Initialize with the default cache location (~/.volta/cache/).
    init() throws {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let cacheRoot = home.appendingPathComponent(".volta/cache", isDirectory: true)
        try FileManager.default.createDirectory(at: cacheRoot, withIntermediateDirectories: true)

        let dbURL = cacheRoot.appendingPathComponent("volta.db")
        self.cacheDir = cacheRoot
        self.dbPool = try DatabasePool(path: dbURL.path)

        try createSchemaIfNeeded()
    }

    /// Initialize with a custom database path (for tests).
    init(path: String) throws {
        let dir = (path as NSString).deletingLastPathComponent
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        self.cacheDir = URL(fileURLWithPath: dir, isDirectory: true)
        self.dbPool = try DatabasePool(path: path)
        try createSchemaIfNeeded()
    }

    // MARK: - Schema

    private func createSchemaIfNeeded() throws {
        try dbPool.write { db in
            try db.create(table: CacheEntry.databaseTableName, ifNotExists: true) { t in
                t.autoIncrementedPrimaryKey("id")
                t.column("part_number", .text).notNull().indexed()
                t.column("manufacturer", .text).notNull()
                t.column("data_json", .text).notNull()
                t.column("cached_at", .datetime).notNull()
                t.column("ttl_seconds", .double).notNull()
                t.column("etag", .text)
            }
            try db.execute(sql: "CREATE UNIQUE INDEX IF NOT EXISTS components_part_number ON \(CacheEntry.databaseTableName)(part_number)")
        }
        Logger.models.info("CacheManager: schema initialized")
    }

    // MARK: - Store

    /// Cache a component with the given TTL.
    func store(_ component: UnifiedComponent, ttl: TimeInterval, etag: String? = nil) throws {
        let normalized = MergeEngine.normalizeMPN(component.partNumber)
        let json = try JSONEncoder().encode(component)
        let jsonString = String(data: json, encoding: .utf8) ?? "{}"

        var entry = CacheEntry(
            id: nil,
            partNumber: normalized,
            manufacturer: component.manufacturer,
            dataJson: jsonString,
            cachedAt: Date(),
            ttlSeconds: ttl == .infinity ? TimeInterval.infinity : ttl,
            etag: etag
        )

        try dbPool.write { db in
            // Upsert: delete existing, insert new.
            try CacheEntry
                .filter(CacheEntry.Columns.partNumber == normalized)
                .deleteAll(db)
            try entry.insert(db)
        }
    }

    // MARK: - Load

    /// Load a cached component by part number. Returns nil if not cached.
    func load(partNumber: String) throws -> UnifiedComponent? {
        let normalized = MergeEngine.normalizeMPN(partNumber)
        return try dbPool.read { db in
            guard let entry = try CacheEntry
                .filter(CacheEntry.Columns.partNumber == normalized)
                .fetchOne(db) else {
                return nil
            }
            guard let data = entry.dataJson.data(using: .utf8) else {
                return nil
            }
            return try JSONDecoder().decode(UnifiedComponent.self, from: data)
        }
    }

    /// Load a cached entry with staleness info.
    func loadWithStaleness(partNumber: String) throws -> (component: UnifiedComponent, isStale: Bool)? {
        let normalized = MergeEngine.normalizeMPN(partNumber)
        return try dbPool.read { db in
            guard let entry = try CacheEntry
                .filter(CacheEntry.Columns.partNumber == normalized)
                .fetchOne(db) else {
                return nil
            }
            guard let data = entry.dataJson.data(using: .utf8) else {
                return nil
            }
            let component = try JSONDecoder().decode(UnifiedComponent.self, from: data)
            return (component, entry.isStale)
        }
    }

    // MARK: - Filesystem Cache (CAD models)

    /// Directory for cached CAD model files from a specific provider.
    func cadCacheDir(provider: String, lcscPartNumber: String) -> URL {
        cacheDir
            .appendingPathComponent("easyeda", isDirectory: true)
            .appendingPathComponent(lcscPartNumber, isDirectory: true)
    }

    // MARK: - Maintenance

    /// Delete all expired entries. Called periodically for cleanup.
    func purgeExpired() throws {
        try dbPool.write { db in
            try db.execute(sql: """
                DELETE FROM \(CacheEntry.databaseTableName) \
                WHERE cached_at + ttl_seconds < CURRENT_TIMESTAMP
                """)
        }
    }

    /// Total number of cached entries.
    var entryCount: Int {
        try! dbPool.read { db in
            try CacheEntry.fetchCount(db)
        }
    }
}
