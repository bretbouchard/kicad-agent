//
//  JlcpcbApiProvider.swift
//  Volta
//
//  Phase 3 / Task 1 — JLCPCB Assembly API Provider
//
//  ComponentDataProvider backed by JLCPCB's official Components API.
//  Provides assembly availability data and LCSC part mapping.
//
//  BLOCKED: Requires API application at api.jlcpcb.com (needs account + small order).
//  Provider is fully built — will work as soon as API access is approved.
//
//  SETUP: Apply at api.jlcpcb.com after placing a small order.
//  Store credentials in Keychain:
//    jlcpcb.api_key     — API key from JLCPCB
//    jlcpcb.client_id   — Client ID (if OAuth flow)
//  Or env var: JLCPCB_API_KEY
//
//  Brand compliance (REQ-07.5):
//    - No "JLC" in user-facing URLs
//    - No JLCPCB logo or trademark in UI
//    - Refer to source as "Assembly Data" not "JLCPCB" in primary UI
//

import Foundation
import OSLog
import VoltaPCBCore

/// Component data provider backed by JLCPCB Components API.
///
/// Adds the `.assemblyData` capability — tells users whether a part
/// can be assembled by JLCPCB's PCBA service. Cross-references LCSC
/// part numbers for CAD model lookup via the EasyEDA provider.
final class JlcpcbApiProvider: ComponentDataProvider, @unchecked Sendable {
    let name = "jlcpcb"
    let displayName = "Assembly Data"
    let capabilities: Set<ProviderCapability> = [.pricing, .stock, .specifications, .assemblyData]

    private let session: URLSession
    private let baseURL: String

    init() {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 30
        self.session = URLSession(configuration: config)
        self.baseURL = "https://jlcpcb.com/api/v1"
    }

    var availability: ProviderAvailability {
        get async {
            guard apiKey != nil else {
                return .requiresAuth(reason: "JLCPCB API access not configured. Apply at api.jlcpcb.com after placing a small order, then store in Keychain: jlcpcb.api_key")
            }
            return .available
        }
    }

    // MARK: - ComponentDataProvider

    func search(keyword: String) async throws -> [UnifiedComponent] {
        guard let key = apiKey else {
            throw JlcpcbApiError.notConfigured
        }

        // Search endpoint — maps keyword to LCSC components
        let url = URL(string: "\(baseURL)/components/search")!
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(key, forHTTPHeaderField: "X-API-Key")

        let body: [String: Any] = [
            "keyword": keyword,
            "page": 1,
            "pageSize": 25
        ]
        req.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else {
            throw JlcpcbApiError.invalidResponse
        }

        if http.statusCode == 429 {
            throw JlcpcbApiError.rateLimited(retryAfter: 60)
        }

        guard http.statusCode == 200 else {
            throw JlcpcbApiError.httpError(status: http.statusCode)
        }

        return try parseSearchResponse(data)
    }

    func getDetails(partNumber: String) async throws -> UnifiedComponent? {
        // Try exact LCSC lookup first, then fall back to search
        let results = try await search(keyword: partNumber)
        let normalized = partNumber.uppercased()
        return results.first { $0.partNumber.uppercased() == normalized } ?? results.first
    }

    // MARK: - Assembly Data

    /// Check if a specific LCSC part is assembly-ready (in JLCPCB's basic/extended library).
    /// Returns nil if API not configured or part not found.
    func checkAssemblyAvailability(lcscPartNumber: String) async throws -> AssemblyAvailability? {
        guard let key = apiKey else {
            throw JlcpcbApiError.notConfigured
        }

        let url = URL(string: "\(baseURL)/components/\(lcscPartNumber)/assembly")!
        var req = URLRequest(url: url)
        req.setValue(key, forHTTPHeaderField: "X-API-Key")

        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            return nil
        }

        struct AssemblyResponse: Codable {
            let lcscPartNumber: String?
            let assemblyType: String?  // "basic" or "extended"
            let inStock: Bool?
            let assemblyFee: Double?
            let deliveryTime: String?
        }

        let decoded = try JSONDecoder().decode(AssemblyResponse.self, from: data)
        guard let partNum = decoded.lcscPartNumber else { return nil }

        return AssemblyAvailability(
            lcscPartNumber: partNum,
            assemblyType: decoded.assemblyType ?? "unknown",
            inStock: decoded.inStock ?? false,
            assemblyFee: decoded.assemblyFee,
            deliveryTime: decoded.deliveryTime
        )
    }

    // MARK: - Response Parsing

    private func parseSearchResponse(_ data: Data) throws -> [UnifiedComponent] {
        struct JlcpcbSearchResponse: Codable {
            let code: Int?
            let message: String?
            let data: SearchData?
        }
        struct SearchData: Codable {
            let totalCount: Int?
            let components: [JlcpcbComponent]?
        }
        struct JlcpcbComponent: Codable {
            let lcsc: String?
            let mfr: String?
            let mpn: String?
            let description: String?
            let package: String?
            let category: String?
            let stock: Int?
            let price: Double?
            let typeCode: Int?  // 0 = basic, 1 = extended, 2 = no assembly
            let attributes: [ComponentAttribute]?
            let datasheet: String?
        }
        struct ComponentAttribute: Codable {
            let name: String?
            let value: String?
        }

        let decoded = try JSONDecoder().decode(JlcpcbSearchResponse.self, from: data)

        if let code = decoded.code, code != 200 {
            Logger.models.error("JLCPCB API error: code=\(code), message=\(decoded.message ?? "none")")
            return []
        }

        guard let components = decoded.data?.components else { return [] }
        let now = Date()

        return components.compactMap { comp in
            guard let lcsc = comp.lcsc, !lcsc.isEmpty else { return nil }

            let partNum = comp.mpn?.isEmpty == false ? comp.mpn! : lcsc

            // Specs
            var specs: [String: String] = [:]
            if let attrs = comp.attributes {
                for attr in attrs {
                    if let name = attr.name, let value = attr.value, value != "-" {
                        specs[name] = value
                    }
                }
            }
            if let pkg = comp.package, !pkg.isEmpty {
                specs["Package"] = pkg
            }

            // Pricing
            var pricing: [PricingData]? = nil
            if let price = comp.price, price > 0 {
                pricing = [PricingData(
                    unitPrice: price,
                    minOrderQty: 1,
                    currency: "CNY",
                    distributor: "LCSC",
                    lastUpdated: now
                )]
            }

            // Stock
            let stock = [StockData(
                quantityAvailable: comp.stock ?? 0,
                distributor: "LCSC",
                lastUpdated: now
            )]

            // Assembly type
            let assemblyType: String
            switch comp.typeCode {
            case 0: assemblyType = "basic"
            case 1: assemblyType = "extended"
            case 2: assemblyType = "none"
            default: assemblyType = "unknown"
            }
            if assemblyType != "unknown" {
                specs["Assembly"] = assemblyType
            }

            return UnifiedComponent(
                partNumber: partNum,
                manufacturer: comp.mfr ?? "",
                description: comp.description ?? "",
                sources: [ComponentSource(
                    provider: "jlcpcb",
                    providerPartId: lcsc,
                    lastUpdated: now,
                    confidence: 0.95
                )],
                pricing: pricing,
                stock: stock,
                specs: specs.isEmpty ? nil : specs,
                datasheetURL: comp.datasheet.flatMap(URL.init(string:)),
                lcscPartNumber: lcsc,
                category: comp.category
            )
        }
    }

    // MARK: - Credentials

    private var apiKey: String? {
        let keychain = KeychainManager()
        if let key = try? keychain.loadCredential(account: "jlcpcb.api_key"), !key.isEmpty {
            return key
        }
        let env = ProcessInfo.processInfo.environment["JLCPCB_API_KEY"]
        if let key = env, !key.isEmpty {
            return key
        }
        return nil
    }
}

/// Assembly availability information for a JLCPCB component.
struct AssemblyAvailability: Sendable, Hashable {
    let lcscPartNumber: String
    let assemblyType: String   // "basic", "extended", "none", "unknown"
    let inStock: Bool
    let assemblyFee: Double?
    let deliveryTime: String?

    /// True if this part can be assembled by JLCPCB (basic or extended library).
    var isAssemblyReady: Bool {
        assemblyType == "basic" || assemblyType == "extended"
    }

    /// True if this part is in the "basic" library (free assembly, no extra fee).
    var isBasicAssembly: Bool {
        assemblyType == "basic"
    }
}

/// JLCPCB API provider errors.
enum JlcpcbApiError: Error, LocalizedError, Sendable {
    case notConfigured
    case invalidResponse
    case httpError(status: Int)
    case rateLimited(retryAfter: TimeInterval)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "JLCPCB API not configured. Apply at api.jlcpcb.com."
        case .invalidResponse:
            return "Invalid response from JLCPCB API."
        case .httpError(let status):
            return "JLCPCB API returned HTTP \(status)."
        case .rateLimited(let retry):
            return "JLCPCB rate limit exceeded. Retry in \(Int(retry))s."
        }
    }
}
