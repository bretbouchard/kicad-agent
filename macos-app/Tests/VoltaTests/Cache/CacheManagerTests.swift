//
//  CacheManagerTests.swift
//  VoltaTests
//
//  Phase 1 / Task 5 — Two-Tier Cache
//
//  Tests GRDB-backed cache: store/load, TTL staleness, filesystem paths.
//

import XCTest
@testable import Volta
@testable import VoltaPCBCore

final class CacheManagerTests: XCTestCase {

    /// Create a CacheManager with a temp database for isolation.
    private func makeCache() throws -> CacheManager {
        let tmpDir = NSTemporaryDirectory() + "volta-cache-test-\(UUID().uuidString)/"
        return try CacheManager(path: tmpDir + "test.db")
    }

    func test_storeAndLoad() throws {
        let cache = try makeCache()
        let component = UnifiedComponent(
            partNumber: "STM32F411RET6",
            manufacturer: "STMicroelectronics",
            description: "MCU 32BIT 512KB FLASH",
            sources: [ComponentSource(provider: "digikey", providerPartId: "STM32F411RET6", lastUpdated: Date(), confidence: 1.0)]
        )

        try cache.store(component, ttl: CacheTTL.pricing)

        let loaded = try cache.load(partNumber: "STM32F411RET6")
        XCTAssertNotNil(loaded)
        XCTAssertEqual(loaded?.partNumber, "STM32F411RET6")
        XCTAssertEqual(loaded?.manufacturer, "STMicroelectronics")
    }

    func test_loadNonExistentReturnsNil() throws {
        let cache = try makeCache()
        let loaded = try cache.load(partNumber: "DOESNOTEXIST")
        XCTAssertNil(loaded)
    }

    func test_stalenessFresh() throws {
        let cache = try makeCache()
        let component = UnifiedComponent(
            partNumber: "RC0805FR-0710KL",
            manufacturer: "Yageo",
            description: "RES SMD 10K OHM 1%",
            sources: [ComponentSource(provider: "digikey", providerPartId: "RC0805FR-0710KL", lastUpdated: Date(), confidence: 1.0)]
        )

        // 24h TTL — should be fresh immediately.
        try cache.store(component, ttl: CacheTTL.pricing)

        let result = try cache.loadWithStaleness(partNumber: "RC0805FR-0710KL")
        XCTAssertNotNil(result)
        XCTAssertFalse(result!.isStale, "Entry should be fresh")
    }

    func test_stalenessExpired() throws {
        let cache = try makeCache()
        let component = UnifiedComponent(
            partNumber: "CAP-001",
            manufacturer: "Murata",
            description: "CAP CER 0.1UF",
            sources: [ComponentSource(provider: "digikey", providerPartId: "CAP-001", lastUpdated: Date(), confidence: 1.0)]
        )

        // 0-second TTL — immediately stale.
        try cache.store(component, ttl: 0)

        let result = try cache.loadWithStaleness(partNumber: "CAP-001")
        XCTAssertNotNil(result)
        XCTAssertTrue(result!.isStale, "Entry should be stale with 0s TTL")
    }

    func test_upsertReplacesExisting() throws {
        let cache = try makeCache()
        let original = UnifiedComponent(
            partNumber: "STM32F103C8T6",
            manufacturer: "ST",
            description: "Original description",
            sources: [ComponentSource(provider: "digikey", providerPartId: "STM32F103C8T6", lastUpdated: Date(), confidence: 1.0)]
        )
        let updated = UnifiedComponent(
            partNumber: "STM32F103C8T6",
            manufacturer: "ST",
            description: "Updated description",
            sources: [ComponentSource(provider: "digikey", providerPartId: "STM32F103C8T6", lastUpdated: Date(), confidence: 1.0)]
        )

        try cache.store(original, ttl: CacheTTL.pricing)
        try cache.store(updated, ttl: CacheTTL.pricing)

        let loaded = try cache.load(partNumber: "STM32F103C8T6")
        XCTAssertEqual(loaded?.description, "Updated description")
        XCTAssertEqual(cache.entryCount, 1, "Upsert should replace, not duplicate")
    }

    func test_cadCacheDirPath() throws {
        let cache = try makeCache()
        let dir = cache.cadCacheDir(provider: "easyeda", lcscPartNumber: "C2040")
        XCTAssertTrue(dir.path.contains("C2040"))
    }
}
