//
//  EasyEdaAPITests.swift
//  VoltaTests
//
//  Phase 4 / Task 6b — Sandbox Cleanup.
//
//  Tests for the direct EasyEDA web API client. Uses URLProtocol stubs
//  for offline HTTP mocking — no real network calls.
//

import XCTest
@testable import Volta
@testable import VoltaPCBCore

// MARK: - URLProtocol Stub

/// Records stubbed HTTP responses per URL path. Configure once per test,
/// then construct a URLSession with `EasyEdaStubURLProtocol`.
final class EasyEdaStubURLProtocol: URLProtocol {

    /// Path → response spec. Tests register stubs here.
    nonisolated(unsafe) static var stubs: [String: (status: Int, body: Data)] = [:]

    /// Counts how many times each path was hit (for ordering / de-dup tests).
    nonisolated(unsafe) static var hitCounts: [String: Int] = [:]

    /// Lock guarding all stub state — URLProtocol can be called from any thread.
    private static let lock = NSLock()

    static func register(path: String, status: Int = 200, body: Data) {
        lock.lock()
        defer { lock.unlock() }
        stubs[path] = (status, body)
    }

    static func reset() {
        lock.lock()
        defer { lock.unlock() }
        stubs.removeAll()
        hitCounts.removeAll()
    }

    override class func canInit(with request: URLRequest) -> Bool {
        guard let host = request.url?.host, host.contains("easyeda.com") else {
            return false
        }
        return true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL))
            return
        }
        let key = url.path

        Self.lock.lock()
        Self.hitCounts[key, default: 0] += 1
        let stub = Self.stubs[key]
        Self.lock.unlock()

        if let stub {
            let http = HTTPURLResponse(
                url: url,
                statusCode: stub.status,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            )!
            client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: stub.body)
            client?.urlProtocolDidFinishLoading(self)
        } else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
        }
    }

    override func stopLoading() {}
}

// MARK: - Test Helpers

private func makeSession() -> URLSession {
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [EasyEdaStubURLProtocol.self]
    return URLSession(configuration: config)
}

private func makeJSON(_ object: [String: Any]) -> Data {
    try! JSONSerialization.data(withJSONObject: object)
}

// MARK: - Tests

final class EasyEdaAPITests: XCTestCase {

    override func setUp() {
        super.setUp()
        EasyEdaStubURLProtocol.reset()
    }

    // MARK: - Successful product fetch

    func test_fetchProduct_succeeds_withResultEnvelope() async throws {
        let body = makeJSON([
            "success": true,
            "code": 200,
            "result": [
                "uuid": "P001",
                "lcsc": "C2040",
                "title": "RP2040",
                "description": "Raspberry Pi MCU",
                "manufacturer": "Raspberry Pi",
                "mpn": "RP2040",
                "datasheet": "https://example.com/ds.pdf",
                "symbol": "S001",
                "footprint": "F001"
            ]
        ])
        EasyEdaStubURLProtocol.register(path: "/api/products/C2040", body: body)

        let client = EasyEdaAPIClient(session: makeSession())
        let product = try await client.fetchProduct(lcscId: "C2040")

        XCTAssertEqual(product.uuid, "P001")
        XCTAssertEqual(product.lcscId, "C2040")
        XCTAssertEqual(product.title, "RP2040")
        XCTAssertEqual(product.mpn, "RP2040")
        XCTAssertEqual(product.symbolUuid, "S001")
        XCTAssertEqual(product.footprintUuid, "F001")
        XCTAssertEqual(EasyEdaStubURLProtocol.hitCounts["/api/products/C2040"], 1)
    }

    func test_fetchProduct_succeeds_withBarePayload() async throws {
        // Some endpoints return the payload without an envelope.
        let body = makeJSON([
            "uuid": "P002",
            "lcsc": "C9999",
            "title": "Bare",
            "symbol": "S002",
            "footprint": "F002"
        ])
        EasyEdaStubURLProtocol.register(path: "/api/products/C9999", body: body)

        let client = EasyEdaAPIClient(session: makeSession())
        let product = try await client.fetchProduct(lcscId: "C9999")

        XCTAssertEqual(product.uuid, "P002")
        XCTAssertEqual(product.lcscId, "C9999")
        XCTAssertEqual(product.symbolUuid, "S002")
    }

    // MARK: - Schema mismatch

    func test_fetchProduct_throwsResponseSchemaMismatch_onMalformedJSON() async {
        let body = Data("this is not json".utf8)
        EasyEdaStubURLProtocol.register(path: "/api/products/C1", body: body)

        let client = EasyEdaAPIClient(session: makeSession())

        do {
            _ = try await client.fetchProduct(lcscId: "C1")
            XCTFail("Expected schema mismatch error")
        } catch let error as EasyEdaError {
            guard case .responseSchemaMismatch(let raw) = error else {
                XCTFail("Expected .responseSchemaMismatch, got \(error)")
                return
            }
            XCTAssertTrue(raw.contains("not json"))
        } catch {
            XCTFail("Unexpected error type: \(error)")
        }
    }

    func test_fetchSymbol_throwsResponseSchemaMismatch_onTruncatedJSON() async {
        // Truncated JSON — strict Codable cannot parse.
        let body = Data(#"{"result":{"uuid":"#.utf8)
        EasyEdaStubURLProtocol.register(path: "/api/eda/product/symbol/S1", body: body)

        let client = EasyEdaAPIClient(session: makeSession())

        do {
            _ = try await client.fetchSymbol(uuid: "S1")
            XCTFail("Expected schema mismatch error")
        } catch let error as EasyEdaError {
            guard case .responseSchemaMismatch = error else {
                XCTFail("Expected .responseSchemaMismatch, got \(error)")
                return
            }
        } catch {
            XCTFail("Unexpected error type: \(error)")
        }
    }

    // MARK: - HTTP errors

    func test_fetchProduct_throwsHttpError_on404() async {
        let body = Data("{}".utf8)
        EasyEdaStubURLProtocol.register(
            path: "/api/products/C404",
            status: 404,
            body: body
        )

        let client = EasyEdaAPIClient(session: makeSession())

        do {
            _ = try await client.fetchProduct(lcscId: "C404")
            XCTFail("Expected HTTP error")
        } catch let error as EasyEdaError {
            guard case .httpError(let status) = error else {
                XCTFail("Expected .httpError, got \(error)")
                return
            }
            XCTAssertEqual(status, 404)
        } catch {
            XCTFail("Unexpected error type: \(error)")
        }
    }

    func test_fetchProduct_throwsHttpError_on500() async {
        let body = Data("{}".utf8)
        EasyEdaStubURLProtocol.register(
            path: "/api/products/C500",
            status: 500,
            body: body
        )

        let client = EasyEdaAPIClient(session: makeSession())

        do {
            _ = try await client.fetchProduct(lcscId: "C500")
            XCTFail("Expected HTTP error")
        } catch let error as EasyEdaError {
            guard case .httpError(let status) = error else {
                XCTFail("Expected .httpError, got \(error)")
                return
            }
            XCTAssertEqual(status, 500)
        } catch {
            XCTFail("Unexpected error type: \(error)")
        }
    }

    // MARK: - Symbol / Footprint success

    func test_fetchSymbol_succeeds() async throws {
        let body = makeJSON([
            "result": [
                "uuid": "S1",
                "title": "Symbol",
                "svg": "<svg/>"
            ]
        ])
        EasyEdaStubURLProtocol.register(path: "/api/eda/product/symbol/S1", body: body)

        let client = EasyEdaAPIClient(session: makeSession())
        let symbol = try await client.fetchSymbol(uuid: "S1")

        XCTAssertEqual(symbol.uuid, "S1")
        XCTAssertEqual(symbol.svg, "<svg/>")
    }

    func test_fetchFootprint_succeeds() async throws {
        let body = makeJSON([
            "result": [
                "uuid": "F1",
                "title": "Footprint",
                "data": "{\"shape\":[]}"
            ]
        ])
        EasyEdaStubURLProtocol.register(path: "/api/eda/product/footprint/F1", body: body)

        let client = EasyEdaAPIClient(session: makeSession())
        let footprint = try await client.fetchFootprint(uuid: "F1")

        XCTAssertEqual(footprint.uuid, "F1")
        XCTAssertEqual(footprint.data, "{\"shape\":[]}")
    }

    // MARK: - Input validation

    func test_fetchProduct_throwsOnEmptyLcscId() async {
        let client = EasyEdaAPIClient(session: makeSession())

        do {
            _ = try await client.fetchProduct(lcscId: "   ")
            XCTFail("Expected incompleteProduct error")
        } catch let error as EasyEdaError {
            guard case .incompleteProduct(let field) = error else {
                XCTFail("Expected .incompleteProduct, got \(error)")
                return
            }
            XCTAssertEqual(field, "lcscId")
        } catch {
            XCTFail("Unexpected error type: \(error)")
        }
    }

    func test_fetchSymbol_throwsOnEmptyUuid() async {
        let client = EasyEdaAPIClient(session: makeSession())

        do {
            _ = try await client.fetchSymbol(uuid: "")
            XCTFail("Expected incompleteProduct error")
        } catch let error as EasyEdaError {
            guard case .incompleteProduct(let field) = error else {
                XCTFail("Expected .incompleteProduct, got \(error)")
                return
            }
            XCTAssertEqual(field, "symbolUuid")
        } catch {
            XCTFail("Unexpected error type: \(error)")
        }
    }
}