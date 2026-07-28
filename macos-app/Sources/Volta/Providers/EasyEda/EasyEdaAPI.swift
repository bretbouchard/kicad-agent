//
//  EasyEdaAPI.swift
//  Volta
//
//  Phase 4 / Task 6b — Sandbox Cleanup: direct EasyEDA web API client.
//
//  Replaces the prior Python CLI subprocess shell-out
//  (sandbox-rule violation). Hits the EasyEDA web API directly via
//  URLSession with strict Codable decoding. NO shell-out, NO fallback,
//  NO feature flag — the web API is the only path.
//
//  Endpoints used (LCSC-ID lookup only — that is all EasyEdaProvider does):
//    - GET https://easyeda.com/api/products/{lcscId}
//    - GET https://easyeda.com/api/eda/product/symbol/{...}
//    - GET https://easyeda.com/api/eda/product/footprint/{...}
//
//  ponytail: one file, one job. The API client fetches and decodes; the
//  provider orchestrates caching and file validation. Strict Codable —
//  schema mismatch throws (with the raw response body for debugging)
//  instead of silently producing `Any` decoded junk.
//

import Foundation
import OSLog
import VoltaPCBCore

/// Errors thrown by the EasyEDA web API client.
enum EasyEdaError: Error, LocalizedError, Sendable {
    /// HTTP transport failure (connection refused, DNS, timeout, etc.).
    case networkError(underlying: String)

    /// API returned a non-2xx status code.
    case httpError(status: Int)

    /// Response body could not be decoded against the strict Codable schema.
    /// Carries the raw body for debugging — never throw away evidence.
    case responseSchemaMismatch(rawResponse: String)

    /// API returned a successful response, but the data was empty/invalid
    /// in a way the schema accepted but the domain rejects (e.g. missing
    /// symbol or footprint UUID after product lookup).
    case incompleteProduct(missingField: String)

    var errorDescription: String? {
        switch self {
        case .networkError(let underlying):
            return "EasyEDA network error: \(underlying)"
        case .httpError(let status):
            return "EasyEDA API returned HTTP \(status)."
        case .responseSchemaMismatch(let raw):
            return "EasyEDA response schema mismatch. Raw body: \(raw.prefix(200))"
        case .incompleteProduct(let field):
            return "EasyEDA product incomplete: missing \(field)."
        }
    }
}

/// EasyEDA product metadata returned by `/api/products/{lcscId}`.
struct EasyEdaProduct: Codable, Sendable, Equatable {
    let uuid: String?
    let lcscId: String?
    let title: String?
    let description: String?
    let manufacturer: String?
    let mpn: String?
    let datasheet: String?
    let symbolUuid: String?
    let footprintUuid: String?

    enum CodingKeys: String, CodingKey {
        case uuid = "uuid"
        case lcscId = "lcsc"
        case title = "title"
        case description = "description"
        case manufacturer = "manufacturer"
        case mpn = "mpn"
        case datasheet = "datasheet"
        case symbolUuid = "symbol"
        case footprintUuid = "footprint"
    }
}

/// EasyEDA symbol SVG payload returned by `/api/eda/product/symbol/{uuid}`.
struct EasyEdaSymbol: Codable, Sendable, Equatable {
    let uuid: String?
    let svg: String?
    let title: String?
}

/// EasyEDA footprint JSON payload returned by `/api/eda/product/footprint/{uuid}`.
struct EasyEdaFootprint: Codable, Sendable, Equatable {
    let uuid: String?
    let data: String?     // JSON-stringified footprint geometry
    let title: String?
}

/// Top-level envelope returned by EasyEDA endpoints.
/// All fields optional — schema is permissive at the wrapper, strict at the inner payload.
private struct EasyEdaEnvelope<T: Codable & Sendable>: Codable {
    let success: Bool?
    let code: Int?
    let message: String?
    let result: T?
    let data: T?
}

/// HTTP client for the EasyEDA public web API.
///
/// Strict Codable decoding — on schema mismatch, throws
/// `EasyEdaError.responseSchemaMismatch(rawResponse:)` with the raw body.
/// No silent `Any` decoding, no fallback paths, no subprocess.
final class EasyEdaAPIClient: Sendable {
    private let session: URLSession
    private let baseURL: URL

    /// Designated initializer. `session` is injectable for testing
    /// (use `URLProtocol` stubs to intercept requests without hitting
    /// the network).
    init(session: URLSession, baseURL: URL = URL(string: "https://easyeda.com")!) {
        self.session = session
        self.baseURL = baseURL
    }

    /// Convenience initializer with production defaults.
    convenience init() {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 30
        self.init(session: URLSession(configuration: config))
    }

    // MARK: - Endpoints

    /// Fetch product metadata for an LCSC part number (e.g. "C2040").
    func fetchProduct(lcscId: String) async throws -> EasyEdaProduct {
        let trimmed = lcscId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw EasyEdaError.incompleteProduct(missingField: "lcscId")
        }
        let url = baseURL.appendingPathComponent("api/products/\(trimmed)")
        let data = try await fetch(url: url)
        return try decode(EasyEdaProduct.self, from: data)
    }

    /// Fetch schematic symbol SVG payload by EasyEDA product UUID.
    func fetchSymbol(uuid: String) async throws -> EasyEdaSymbol {
        guard !uuid.isEmpty else {
            throw EasyEdaError.incompleteProduct(missingField: "symbolUuid")
        }
        let url = baseURL.appendingPathComponent("api/eda/product/symbol/\(uuid)")
        let data = try await fetch(url: url)
        return try decode(EasyEdaSymbol.self, from: data)
    }

    /// Fetch PCB footprint JSON payload by EasyEDA product UUID.
    func fetchFootprint(uuid: String) async throws -> EasyEdaFootprint {
        guard !uuid.isEmpty else {
            throw EasyEdaError.incompleteProduct(missingField: "footprintUuid")
        }
        let url = baseURL.appendingPathComponent("api/eda/product/footprint/\(uuid)")
        let data = try await fetch(url: url)
        return try decode(EasyEdaFootprint.self, from: data)
    }

    // MARK: - Transport

    private func fetch(url: URL) async throws -> Data {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw EasyEdaError.networkError(underlying: String(describing: error))
        }

        guard let http = response as? HTTPURLResponse else {
            throw EasyEdaError.networkError(underlying: "non-HTTP response")
        }
        guard (200..<300).contains(http.statusCode) else {
            throw EasyEdaError.httpError(status: http.statusCode)
        }
        return data
    }

    // MARK: - Decoding

    /// Strict decode: try the envelope wrapper first; fall back to
    /// decoding the payload directly. On schema mismatch, throw
    /// `EasyEdaError.responseSchemaMismatch` with the raw body.
    private func decode<T: Codable & Sendable>(_ type: T.Type, from data: Data) throws -> T {
        // Try envelope first (typical API shape: { "result": {...} })
        do {
            let envelope = try JSONDecoder().decode(EasyEdaEnvelope<T>.self, from: data)
            if let inner = envelope.result ?? envelope.data {
                return inner
            }
        } catch {
            // Envelope decode failed — fall through to direct decode.
        }

        // Direct decode (no envelope).
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            let raw = String(data: data, encoding: .utf8) ?? "<non-UTF8 bytes>"
            Logger.models.error("EasyEDA schema mismatch: \(raw.prefix(200))")
            throw EasyEdaError.responseSchemaMismatch(rawResponse: raw)
        }
    }
}