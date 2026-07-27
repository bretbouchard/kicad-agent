//
//  OctopartProvider.swift
//  Volta
//
//  Phase 2 / Task 1 — Octopart/Nexar Provider
//
//  ComponentDataProvider backed by Nexar GraphQL API.
//  Aggregates data from Octopart's multi-distributor database.
//  Secondary source — used when Digi-Key misses (500 req/mo free tier).
//
//  SETUP: Register at portal.nexar.com → get Client ID + Secret.
//  Store in Keychain: nexar.client_id, nexar.client_secret
//  Or env vars: NEXAR_CLIENT_ID, NEXAR_CLIENT_SECRET
//

import Foundation
import OSLog
import VoltaPCBCore

/// Component data provider backed by Nexar/Octopart GraphQL API.
final class OctopartProvider: ComponentDataProvider, @unchecked Sendable {
    let name = "octopart"
    let displayName = "Octopart (Nexar)"
    let capabilities: Set<ProviderCapability> = [.pricing, .stock, .specifications]

    private let session: URLSession
    private let tokenURL = URL(string: "https://token.nexar.com/connect/token")!
    private let graphqlURL = URL(string: "https://api.nexar.com/graphql")!
    private var cachedToken: String?
    private var tokenExpiresAt: Date?
    private let tokenLock = NSLock()

    init() {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        self.session = URLSession(configuration: config)
    }

    var availability: ProviderAvailability {
        get async {
            let creds = credentials
            guard creds.clientId != "nexar-not-configured" else {
                return .requiresAuth(reason: "Nexar API credentials not set. Register at portal.nexar.com, then store in Keychain: nexar.client_id, nexar.client_secret")
            }
            return .available
        }
    }

    // MARK: - ComponentDataProvider

    func search(keyword: String) async throws -> [UnifiedComponent] {
        let token = try await ensureToken()

        let query = """
        query Search($keyword: String!) {
          supSearch(q: $keyword, start: 0, limit: 10) {
            hits
            results {
              part {
                mpn
                manufacturer { name }
                shortDescription
                datasheets { url }
                category { name }
                specs { attribute { name } displayValue }
                offers {
                  seller { name }
                  inventoryLevel
                  prices { quantity price currency }
                  clickUrl
                }
              }
            }
          }
        }
        """

        let payload: [String: Any] = [
            "query": query,
            "variables": ["keyword": keyword]
        ]

        let body = try JSONSerialization.data(withJSONObject: payload)
        var req = URLRequest(url: graphqlURL)
        req.httpMethod = "POST"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = body

        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else {
            throw OctopartError.invalidResponse
        }

        if http.statusCode == 429 {
            let retryAfter = http.value(forHTTPHeaderField: "Retry-After")
            let seconds = Double(retryAfter ?? "60") ?? 60
            throw OctopartError.rateLimited(retryAfter: seconds)
        }

        guard http.statusCode == 200 else {
            throw OctopartError.httpError(status: http.statusCode)
        }

        return try parseSearchResponse(data)
    }

    func getDetails(partNumber: String) async throws -> UnifiedComponent? {
        let results = try await search(keyword: partNumber)
        return results.first
    }

    // MARK: - Response Parsing

    private func parseSearchResponse(_ data: Data) throws -> [UnifiedComponent] {
        struct GraphqlResponse: Codable {
            let data: SearchData?
            let errors: [GraphqlError]?
        }
        struct GraphqlError: Codable {
            let message: String
        }
        struct SearchData: Codable {
            let supSearch: SupSearch?
        }
        struct SupSearch: Codable {
            let hits: Int?
            let results: [SearchResult]?
        }
        struct SearchResult: Codable {
            let part: Part?
        }
        struct Part: Codable {
            let mpn: String?
            let manufacturer: Manufacturer?
            let shortDescription: String?
            let datasheets: [Datasheet]?
            let category: CategoryRef?
            let specs: [Spec]?
            let offers: [Offer]?
        }
        struct Manufacturer: Codable {
            let name: String?
        }
        struct Datasheet: Codable {
            let url: String?
        }
        struct CategoryRef: Codable {
            let name: String?
        }
        struct Spec: Codable {
            let attribute: AttributeRef?
            let displayValue: String?
        }
        struct AttributeRef: Codable {
            let name: String?
        }
        struct Offer: Codable {
            let seller: Seller?
            let inventoryLevel: Int?
            let prices: [PriceEntry]?
            let clickUrl: String?
        }
        struct Seller: Codable {
            let name: String?
        }
        struct PriceEntry: Codable {
            let quantity: Int?
            let price: Double?
            let currency: String?
        }

        let decoded = try JSONDecoder().decode(GraphqlResponse.self, from: data)

        if let errors = decoded.errors, !errors.isEmpty {
            Logger.models.error("Octopart GraphQL errors: \(errors.map(\.message).joined(separator: ", "))")
            return []
        }

        guard let results = decoded.data?.supSearch?.results else { return [] }
        let now = Date()

        return results.compactMap { result in
            guard let part = result.part, let mpn = part.mpn else { return nil }

            // Map offers to pricing + stock
            var pricing: [PricingData]? = nil
            var stock: [StockData]? = nil

            if let offers = part.offers, !offers.isEmpty {
                pricing = offers.compactMap { offer in
                    guard let seller = offer.seller?.name,
                          let firstPrice = offer.prices?.first,
                          let unitPrice = firstPrice.price else { return nil }
                    return PricingData(
                        unitPrice: unitPrice,
                        minOrderQty: firstPrice.quantity ?? 1,
                        tieredPricing: offer.prices?.map { PricingTier(minQty: $0.quantity ?? 1, unitPrice: $0.price ?? 0) },
                        currency: firstPrice.currency ?? "USD",
                        distributor: seller,
                        lastUpdated: now
                    )
                }
                if pricing!.isEmpty { pricing = nil }

                stock = offers.compactMap { offer in
                    guard let seller = offer.seller?.name else { return nil }
                    return StockData(
                        quantityAvailable: offer.inventoryLevel ?? 0,
                        distributor: seller,
                        lastUpdated: now
                    )
                }
                if stock!.isEmpty { stock = nil }
            }

            // Map specs
            var specs: [String: String]? = nil
            if let partSpecs = part.specs, !partSpecs.isEmpty {
                var dict: [String: String] = [:]
                for spec in partSpecs {
                    if let name = spec.attribute?.name, let value = spec.displayValue {
                        dict[name] = value
                    }
                }
                if !dict.isEmpty { specs = dict }
            }

            // Datasheet
            var datasheetURL: URL? = nil
            if let ds = part.datasheets?.first?.url {
                datasheetURL = URL(string: ds)
            }

            return UnifiedComponent(
                partNumber: mpn,
                manufacturer: part.manufacturer?.name ?? "",
                description: part.shortDescription ?? "",
                sources: [ComponentSource(
                    provider: "octopart",
                    providerPartId: mpn,
                    lastUpdated: now,
                    confidence: 0.85
                )],
                pricing: pricing,
                stock: stock,
                specs: specs,
                datasheetURL: datasheetURL,
                category: part.category?.name
            )
        }
    }

    /// Get a valid OAuth2 token (for use by companion CAD provider).
    func ensureTokenPublic() async throws -> String {
        try await ensureToken()
    }

    // MARK: - OAuth2

    private var credentials: (clientId: String, clientSecret: String) {
        // Try Keychain first
        let keychain = KeychainManager()
        if let id = try? keychain.loadCredential(account: "nexar.client_id"),
           let secret = try? keychain.loadCredential(account: "nexar.client_secret") {
            return (id, secret)
        }
        // Fall back to env vars
        let id = ProcessInfo.processInfo.environment["NEXAR_CLIENT_ID"] ?? "nexar-not-configured"
        let secret = ProcessInfo.processInfo.environment["NEXAR_CLIENT_SECRET"] ?? ""
        return (id, secret)
    }

    private func ensureToken() async throws -> String {
        // Fast path: check cache under lock
        let needsRefresh: Bool = tokenLock.withLock {
            guard let token = cachedToken, let expiry = tokenExpiresAt else {
                return true
            }
            return Date().addingTimeInterval(60) >= expiry
        }

        if !needsRefresh {
            return tokenLock.withLock { cachedToken! }
        }

        let creds = credentials
        guard creds.clientId != "nexar-not-configured" else {
            throw OctopartError.notConfigured
        }

        var req = URLRequest(url: tokenURL)
        req.httpMethod = "POST"
        req.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")

        let body = "grant_type=client_credentials&client_id=\(creds.clientId)&client_secret=\(creds.clientSecret)"
        req.httpBody = body.data(using: .utf8)

        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw OctopartError.authFailed
        }

        struct TokenResponse: Codable {
            let access_token: String
            let expires_in: Int
        }

        let tokenResp = try JSONDecoder().decode(TokenResponse.self, from: data)

        tokenLock.withLock {
            cachedToken = tokenResp.access_token
            tokenExpiresAt = Date().addingTimeInterval(TimeInterval(tokenResp.expires_in))
        }

        return tokenResp.access_token
    }
}

private extension NSLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}

/// Octopart provider errors.
enum OctopartError: Error, LocalizedError, Sendable {
    case notConfigured
    case authFailed
    case invalidResponse
    case httpError(status: Int)
    case rateLimited(retryAfter: TimeInterval)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "Nexar API not configured. Register at portal.nexar.com."
        case .authFailed:
            return "Nexar OAuth2 authentication failed."
        case .invalidResponse:
            return "Invalid response from Nexar API."
        case .httpError(let status):
            return "Nexar API returned HTTP \(status)."
        case .rateLimited(let retry):
            return "Nexar rate limit exceeded. Retry in \(Int(retry))s."
        }
    }
}
