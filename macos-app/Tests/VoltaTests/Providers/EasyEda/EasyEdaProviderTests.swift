//
//  EasyEdaProviderTests.swift
//  VoltaTests
//
//  Phase 4 / Task 6b — Sandbox Cleanup.
//
//  Tests for EasyEdaProvider using the new direct web API client.
//  No subprocess / ProcessRunner mocking — the EasyEdaAPIClient is
//  injected with a stubbed URLSession (see EasyEdaAPITests.swift for
//  the URLProtocol stub pattern).
//

import XCTest
@testable import Volta
@testable import VoltaPCBCore

/// Reuses the URLProtocol stub from EasyEdaAPITests — same registry,
/// same session factory. Co-located in one test target.
final class EasyEdaProviderTests: XCTestCase {

    /// Per-test temp cache directory. Keeps tests off the user's real
    /// `~/.volta/cache/easyeda/` so prior runs don't short-circuit fetches.
    private var tempCacheRoot: URL!

    override func setUp() {
        super.setUp()
        EasyEdaStubURLProtocol.reset()
        tempCacheRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("EasyEdaProviderTests-\(UUID().uuidString)", isDirectory: true)
        try? FileManager.default.createDirectory(at: tempCacheRoot, withIntermediateDirectories: true)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: tempCacheRoot)
        super.tearDown()
    }

    private func makeProvider(apiSession: URLSession? = nil) -> EasyEdaProvider {
        let session = apiSession ?? makeProviderSession()
        return EasyEdaProvider(
            api: EasyEdaAPIClient(session: session),
            cacheRoot: tempCacheRoot
        )
    }

    /// Availability is always `.available` for the web-API provider —
    /// no install check, no subprocess probe. Failures surface per-call.
    func test_availability_isAvailable() async {
        let provider = makeProvider()
        let avail = await provider.availability
        guard case .available = avail else {
            XCTFail("Expected .available, got \(avail)")
            return
        }
    }

    /// getCADModels returns empty when product has no downstream UUIDs.
    func test_getModels_productMissingUUIDs_returnsEmpty() async throws {
        let body = jsonBody([
            "result": [
                "uuid": "P1",
                "lcsc": "C1234",
                "title": "No UUIDs part"
            ]
        ])
        EasyEdaStubURLProtocol.register(path: "/api/products/C1234", body: body)

        let provider = makeProvider()
        let refs = try await provider.getCADModels(lcscPartNumber: "C1234")
        XCTAssertTrue(refs.isEmpty)
    }

    /// getCADModels caches and reuses results — second call should not hit network.
    func test_getModels_cachesResults() async throws {
        let productBody = jsonBody([
            "result": [
                "uuid": "P1",
                "lcsc": "C9999",
                "title": "Cache Test",
                "symbol": "S9",
                "footprint": "F9"
            ]
        ])
        let symbolBody = jsonBody([
            "result": [
                "uuid": "S9",
                "title": "Sym",
                "svg": "<svg/>"
            ]
        ])
        let footprintBody = jsonBody([
            "result": [
                "uuid": "F9",
                "title": "FP",
                "data": "{}"
            ]
        ])
        EasyEdaStubURLProtocol.register(path: "/api/products/C9999", body: productBody)
        EasyEdaStubURLProtocol.register(path: "/api/eda/product/symbol/S9", body: symbolBody)
        EasyEdaStubURLProtocol.register(path: "/api/eda/product/footprint/F9", body: footprintBody)

        let provider = makeProvider()

        // First call — populates cache.
        let first = try await provider.getCADModels(lcscPartNumber: "C9999")
        XCTAssertFalse(first.isEmpty)
        let productHitsAfterFirst = EasyEdaStubURLProtocol.hitCounts["/api/products/C9999"] ?? 0
        XCTAssertEqual(productHitsAfterFirst, 1)

        // Second call — should hit cache, no network.
        let second = try await provider.getCADModels(lcscPartNumber: "C9999")
        XCTAssertEqual(second.count, first.count)
        let productHitsAfterSecond = EasyEdaStubURLProtocol.hitCounts["/api/products/C9999"] ?? 0
        XCTAssertEqual(productHitsAfterSecond, 1, "Cache should prevent a second product fetch")
    }

    /// searchCADModels always returns empty (API does not support keyword search).
    func test_searchCADModels_returnsEmpty() async throws {
        let provider = makeProvider()
        let results = try await provider.searchCADModels(keyword: "STM32F411")
        XCTAssertTrue(results.isEmpty)
    }

    // MARK: - Helpers

    private func makeProviderSession() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [EasyEdaStubURLProtocol.self]
        return URLSession(configuration: config)
    }

    private func jsonBody(_ object: [String: Any]) -> Data {
        try! JSONSerialization.data(withJSONObject: object)
    }
}