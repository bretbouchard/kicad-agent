//
//  DigiKeyProvider.swift
//  Volta
//
//  Phase 1 / Task 2 — Digi-Key V4 Provider
//
//  First real ComponentDataProvider adapter. Queries Digi-Key V4 keyword
//  search endpoint and maps results to UnifiedComponent.
//
//  ARCH-P1-01: Locale headers required on ALL V4 calls (US/en/USD default).
//  Rate limit handling: respects X-BurstLimit-* and Retry-After on 429.
//

import Foundation
import OSLog
import VoltaPCBCore

/// Digi-Key V4 API adapter for component data (pricing, stock, specs).
final class DigiKeyProvider: ComponentDataProvider, @unchecked Sendable {
    let name = "digikey"
    let displayName = "Digi-Key"
    let capabilities: Set<ProviderCapability> = [.pricing, .stock, .specifications, .datasheets]

    private let auth: DigiKeyAuth
    private let session: URLSession
    private let baseURL: String

    /// Locale headers (ARCH-P1-01) — configurable, defaults to US/en/USD.
    private let localeSite: String
    private let localeLanguage: String
    private let localeCurrency: String

    init(credentials: DigiKeyCredentials, sandbox: Bool = false) {
        self.auth = DigiKeyAuth(credentials: credentials, sandbox: sandbox)
        self.baseURL = sandbox ? "https://api-sandbox.digikey.com" : "https://api.digikey.com"
        self.localeSite = "US"
        self.localeLanguage = "en"
        self.localeCurrency = "USD"

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 15
        config.waitsForConnectivity = true
        self.session = URLSession(configuration: config)
    }

    var availability: ProviderAvailability {
        get async {
            do {
                _ = try await auth.getAccessToken()
                return .available
            } catch {
                return .requiresAuth(reason: error.localizedDescription)
            }
        }
    }

    func search(keyword: String) async throws -> [UnifiedComponent] {
        let token = try await auth.getAccessToken()
        let (data, response) = try await performKeywordSearch(keyword: keyword, token: token)

        guard let http = response as? HTTPURLResponse else {
            throw DigiKeyError.invalidResponse
        }

        // Rate limit handling
        if http.statusCode == 429 {
            let retryAfter = http.value(forHTTPHeaderField: "Retry-After").flatMap(TimeInterval.init)
            throw DigiKeyError.rateLimited(retryAfter: retryAfter)
        }

        guard http.statusCode == 200 else {
            let msg = String(data: data, encoding: .utf8)
            throw DigiKeyError.apiError(statusCode: http.statusCode, message: msg)
        }

        let response_decoded = try JSONDecoder().decode(DigiKeySearchResponse.self, from: data)
        return response_decoded.products.map { mapToUnifiedComponent($0) }
    }

    func getDetails(partNumber: String) async throws -> UnifiedComponent? {
        // V4 keyword search with exact MPN returns the part.
        let results = try await search(keyword: partNumber)
        // Prefer exact MPN match
        let normalized = partNumber.uppercased()
        return results.first { $0.partNumber.uppercased() == normalized } ?? results.first
    }

    // MARK: - API Call

    private func performKeywordSearch(keyword: String, token: String) async throws -> (Data, URLResponse) {
        let url = URL(string: "\(baseURL)/products/v4/search/keyword")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(auth.clientID, forHTTPHeaderField: "X-DIGIKEY-Client-Id")

        // ARCH-P1-01: Required locale headers — V4 returns 400 without them.
        request.setValue(localeSite, forHTTPHeaderField: "X-DIGIKEY-Locale-Site")
        request.setValue(localeLanguage, forHTTPHeaderField: "X-DIGIKEY-Locale-Language")
        request.setValue(localeCurrency, forHTTPHeaderField: "X-DIGIKEY-Locale-Currency")

        let body: [String: Any] = [
            "Keywords": keyword,
            "RecordCount": 25,
            "RecordStartPosition": 0
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        return try await session.data(for: request)
    }

    // MARK: - Mapping

    private func mapToUnifiedComponent(_ product: DigiKeyProduct) -> UnifiedComponent {
        var specs: [String: String]? = nil
        if let params = product.parameters, !params.isEmpty {
            specs = Dictionary(uniqueKeysWithValues: params.map { ($0.parameterText, $0.valueText) })
        }

        // Build pricing tiers from first variation
        var pricingTiers: [PricingTier]? = nil
        if let variation = product.productVariations?.first,
           let stdPricing = variation.standardPricing, !stdPricing.isEmpty {
            pricingTiers = stdPricing.map { PricingTier(minQty: $0.breakQuantity, unitPrice: $0.unitPrice) }
        }

        let pricing = PricingData(
            unitPrice: product.unitPrice,
            minOrderQty: product.productVariations?.first?.minimumOrderQuantity ?? 1,
            tieredPricing: pricingTiers,
            currency: localeCurrency,
            distributor: "Digi-Key",
            lastUpdated: Date()
        )

        let stock = StockData(
            quantityAvailable: product.quantityAvailable,
            distributor: "Digi-Key",
            lastUpdated: Date()
        )

        let source = ComponentSource(
            provider: name,
            providerPartId: product.manufacturerProductNumber,
            lastUpdated: Date(),
            confidence: 1.0
        )

        return UnifiedComponent(
            partNumber: product.manufacturerProductNumber,
            manufacturer: product.manufacturer.name,
            description: product.description.productDescription,
            sources: [source],
            pricing: [pricing],
            stock: [stock],
            specs: specs,
            datasheetURL: product.datasheetUrl.flatMap(URL.init(string:)),
            category: product.category?.name
        )
    }
}
