//
//  MouserProvider.swift
//  Volta
//
//  Phase 3 / Task 2 — Mouser Search API Provider
//
//  ComponentDataProvider backed by Mouser's free REST Search API.
//  Backup source — used when Digi-Key is rate-limited or misses a part.
//
//  SETUP: Register at mouser.com/api (free, self-serve) → get API key.
//  Store in Keychain: mouser.api_key
//  Or env var: MOUSER_API_KEY
//
//  API docs: https://www.mouser.com/api/docs/API-usage-guidelines
//  Endpoints:
//    /api/v1/search/partnumber   — exact MPN lookup
//    /api/v1/search/partkeyword  — keyword search
//  Rate limits: daily call limits by subscription tier (free = 500/day)
//

import Foundation
import OSLog
import VoltaPCBCore

/// Component data provider backed by Mouser Search API.
final class MouserProvider: ComponentDataProvider, @unchecked Sendable {
    let name = "mouser"
    let displayName = "Mouser"
    let capabilities: Set<ProviderCapability> = [.pricing, .stock, .specifications, .datasheets]

    private let session: URLSession
    private let baseURL: String

    init() {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 30
        self.session = URLSession(configuration: config)
        self.baseURL = "https://api.mouser.com/api/v1"
    }

    var availability: ProviderAvailability {
        get async {
            guard apiKey != nil else {
                return .requiresAuth(reason: "Mouser API key not set. Register at mouser.com/api, then store in Keychain: mouser.api_key")
            }
            return .available
        }
    }

    // MARK: - ComponentDataProvider

    func search(keyword: String) async throws -> [UnifiedComponent] {
        guard let key = apiKey else {
            throw MouserError.notConfigured
        }

        let url = URL(string: "\(baseURL)/search/partkeyword?apiKey=\(key)&keyword=\(urlEncode(keyword))&limit=25")!
        let (data, response) = try await session.data(from: url)

        guard let http = response as? HTTPURLResponse else {
            throw MouserError.invalidResponse
        }

        if http.statusCode == 429 {
            throw MouserError.rateLimited(retryAfter: 60)
        }

        guard http.statusCode == 200 else {
            throw MouserError.httpError(status: http.statusCode)
        }

        return try parseSearchResponse(data)
    }

    func getDetails(partNumber: String) async throws -> UnifiedComponent? {
        guard let key = apiKey else {
            throw MouserError.notConfigured
        }

        let url = URL(string: "\(baseURL)/search/partnumber?apiKey=\(key)&partNumber=\(urlEncode(partNumber))")!
        let (data, response) = try await session.data(from: url)

        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            // Fallback to keyword search if partnumber endpoint fails
            let results = try await search(keyword: partNumber)
            let normalized = partNumber.uppercased()
            return results.first { $0.partNumber.uppercased() == normalized } ?? results.first
        }

        let components = try parseSearchResponse(data)
        let normalized = partNumber.uppercased()
        return components.first { $0.partNumber.uppercased() == normalized } ?? components.first
    }

    // MARK: - Response Parsing

    private func parseSearchResponse(_ data: Data) throws -> [UnifiedComponent] {
        struct MouserSearchResponse: Codable {
            let SearchResults: SearchResults?
            let Errors: [MouserErrorDetail]?
        }
        struct SearchResults: Codable {
            let Parts: [MouserPart]?
            let NumberOfResult: Int?
        }
        struct MouserPart: Codable {
            let ManufacturerPartNumber: String?
            let Manufacturer: String?
            let Description: String?
            let Category: String?
            let Min: String?
            let MultipackQuantity: String?
            let PriceBreaks: [PriceBreak]?
            let Availability: String?
            let AvailabilityInStock: Int?
            let ProductDetailUrl: String?
            let DataSheetUrl: String?
            let ProductAttributes: [ProductAttribute]?
        }
        struct PriceBreak: Codable {
            let Quantity: Int?
            let Price: String?
        }
        struct ProductAttribute: Codable {
            let AttributeName: String?
            let AttributeValue: String?
        }
        struct MouserErrorDetail: Codable {
            let Code: Int?
            let Message: String?
            let PropertyName: String?
        }

        let decoded = try JSONDecoder().decode(MouserSearchResponse.self, from: data)

        if let errors = decoded.Errors, !errors.isEmpty {
            let msgs = errors.compactMap { $0.Message }.joined(separator: ", ")
            Logger.models.error("Mouser API errors: \(msgs)")
        }

        guard let parts = decoded.SearchResults?.Parts else { return [] }
        let now = Date()

        return parts.compactMap { part in
            guard let mpn = part.ManufacturerPartNumber, !mpn.isEmpty else { return nil }

            // Pricing
            var pricing: [PricingData]? = nil
            if let breaks = part.PriceBreaks, !breaks.isEmpty {
                let tiers = breaks.compactMap { pb -> PricingTier? in
                    guard let qty = pb.Quantity else { return nil }
                    let priceStr = pb.Price ?? "0"
                    let cleaned = priceStr.replacingOccurrences(of: "$", with: "")
                        .replacingOccurrences(of: ",", with: "")
                    let price = Double(cleaned) ?? 0
                    return PricingTier(minQty: qty, unitPrice: price)
                }
                if let first = breaks.first {
                    let priceStr = first.Price ?? "0"
                    let cleaned = priceStr.replacingOccurrences(of: "$", with: "")
                        .replacingOccurrences(of: ",", with: "")
                    let unitPrice = Double(cleaned) ?? 0
                    let minQty = Int(part.Min ?? "1") ?? 1
                    pricing = [PricingData(
                        unitPrice: unitPrice,
                        minOrderQty: minQty,
                        tieredPricing: tiers.isEmpty ? nil : tiers,
                        currency: "USD",
                        distributor: "Mouser",
                        lastUpdated: now
                    )]
                }
            }

            // Stock
            let stockQty = part.AvailabilityInStock ?? 0
            let stock = [StockData(
                quantityAvailable: stockQty,
                distributor: "Mouser",
                leadTime: part.Availability,
                lastUpdated: now
            )]

            // Specs
            var specs: [String: String]? = nil
            if let attrs = part.ProductAttributes, !attrs.isEmpty {
                var dict: [String: String] = [:]
                for attr in attrs {
                    if let name = attr.AttributeName, let value = attr.AttributeValue, !value.isEmpty {
                        dict[name] = value
                    }
                }
                if !dict.isEmpty { specs = dict }
            }

            return UnifiedComponent(
                partNumber: mpn,
                manufacturer: part.Manufacturer ?? "",
                description: part.Description ?? "",
                sources: [ComponentSource(
                    provider: "mouser",
                    providerPartId: mpn,
                    lastUpdated: now,
                    confidence: 0.90
                )],
                pricing: pricing,
                stock: stock,
                specs: specs,
                datasheetURL: part.DataSheetUrl.flatMap(URL.init(string:)),
                category: part.Category
            )
        }
    }

    // MARK: - Credentials

    private var apiKey: String? {
        let keychain = KeychainManager()
        if let key = try? keychain.loadCredential(account: "mouser.api_key"), !key.isEmpty {
            return key
        }
        let env = ProcessInfo.processInfo.environment["MOUSER_API_KEY"]
        if let key = env, !key.isEmpty {
            return key
        }
        return nil
    }

    private func urlEncode(_ s: String) -> String {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&")
        return s.addingPercentEncoding(withAllowedCharacters: allowed) ?? s
    }
}

/// Mouser provider errors.
enum MouserError: Error, LocalizedError, Sendable {
    case notConfigured
    case invalidResponse
    case httpError(status: Int)
    case rateLimited(retryAfter: TimeInterval)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "Mouser API not configured. Register at mouser.com/api."
        case .invalidResponse:
            return "Invalid response from Mouser API."
        case .httpError(let status):
            return "Mouser API returned HTTP \(status)."
        case .rateLimited(let retry):
            return "Mouser rate limit exceeded. Retry in \(Int(retry))s."
        }
    }
}
