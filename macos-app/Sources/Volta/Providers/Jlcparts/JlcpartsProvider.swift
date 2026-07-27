//
//  JlcpartsProvider.swift
//  Volta
//
//  Phase 2 / Task 2 — jlcparts Local Provider
//
//  Offline component data source backed by the jlcparts SQLite database.
//  11.2M components from JLCPCB/LCSC catalog. Data is a static snapshot —
//  stale by definition but excellent for offline fallback and broad coverage.
//
//  The database can be downloaded from https://github.com/yaqwsx/jlcparts
//  Default location: ~/.volta/cache/jlcparts.sqlite
//

import Foundation
import GRDB
import OSLog
import VoltaPCBCore

/// Offline component provider backed by jlcparts SQLite database.
///
/// All data is marked as offline/stale. Confidence score is lower than
/// live API providers (0.5 vs 0.95 for Digi-Key) reflecting the snapshot
/// nature of the data.
final class JlcpartsProvider: ComponentDataProvider, @unchecked Sendable {
    let name = "jlcparts"
    let displayName = "JLC Parts (Offline)"
    let capabilities: Set<ProviderCapability> = [.pricing, .stock, .specifications]

    /// Database pool. nil when DB is not available.
    private var dbPool: DatabasePool?
    private let dbPath: String

    init(dbPath: String? = nil) {
        let home = FileManager.default.homeDirectoryForCurrentUser
        self.dbPath = dbPath ?? home
            .appendingPathComponent(".volta/cache/jlcparts.sqlite").path

        if FileManager.default.fileExists(atPath: self.dbPath) {
            do {
                var config = Configuration()
                config.readonly = true
                self.dbPool = try DatabasePool(path: self.dbPath, configuration: config)
                Logger.models.info("JlcpartsProvider: loaded database at \(self.dbPath)")
            } catch {
                Logger.models.error("JlcpartsProvider: failed to open database: \(error)")
            }
        } else {
            Logger.models.info("JlcpartsProvider: database not found at \(self.dbPath)")
        }
    }

    var availability: ProviderAvailability {
        get async {
            guard dbPool != nil else {
                return .requiresAuth(reason: "jlcparts database not found. Download from https://github.com/yaqwsx/jlcparts")
            }
            return .available
        }
    }

    // MARK: - ComponentDataProvider

    func search(keyword: String) async throws -> [UnifiedComponent] {
        guard let pool = dbPool else { return [] }
        let escaped = keyword.replacingOccurrences(of: "'", with: "''")

        return try await pool.read { db in
            // Try FTS5 full-text search first, fall back to LIKE
            let ftsSql = """
                SELECT lcsc, mfr, mpn, description, package, category,
                       stock, price_low, attributes
                FROM parts
                WHERE parts MATCH '\(escaped)'
                ORDER BY rank
                LIMIT 25
                """
            do {
                let rows = try Row.fetchAll(db, sql: ftsSql)
                return rows.map { Self.mapRow($0) }
            } catch {
                Logger.models.warning("JlcpartsProvider: FTS unavailable, using LIKE")
                let likeSql = """
                    SELECT lcsc, mfr, mpn, description, package, category,
                           stock, price_low, attributes
                    FROM parts
                    WHERE mpn LIKE '%\(escaped)%' OR description LIKE '%\(escaped)%'
                    LIMIT 25
                    """
                let rows = try Row.fetchAll(db, sql: likeSql)
                return rows.map { Self.mapRow($0) }
            }
        }
    }

    func getDetails(partNumber: String) async throws -> UnifiedComponent? {
        guard let pool = dbPool else { return nil }
        let escaped = partNumber.replacingOccurrences(of: "'", with: "''")

        return try await pool.read { db in
            guard let row = try Row.fetchOne(db, sql: """
                SELECT lcsc, mfr, mpn, description, package, category,
                       stock, price_low, attributes
                FROM parts
                WHERE mpn = '\(escaped)' OR lcsc = '\(escaped)'
                LIMIT 1
                """) else {
                return nil
            }
            return Self.mapRow(row)
        }
    }

    // MARK: - Row Mapping

    private static func mapRow(_ row: Row) -> UnifiedComponent {
        let lcsc: String = row["lcsc"] ?? ""
        let mfr: String = row["mfr"] ?? ""
        let mpn: String = row["mpn"] ?? ""
        let description: String = row["description"] ?? ""
        let package: String = row["package"] ?? ""
        let category: String = row["category"] ?? ""
        let stock: Int = row["stock"] ?? 0
        let priceLow: Double? = row["price_low"]
        let attributesJson: String = row["attributes"] ?? ""

        // Parse attributes JSON into specs dict
        var specs: [String: String] = [:]
        if let data = attributesJson.data(using: .utf8),
           let attrs = try? JSONSerialization.jsonObject(with: data) as? [[String: String]] {
            for attr in attrs {
                if let name = attr["name"], let value = attr["value"], value != "-" {
                    specs[name] = value
                }
            }
        }
        if !package.isEmpty { specs["Package"] = package }

        // Pricing
        var pricing: [PricingData]? = nil
        if let price = priceLow {
            pricing = [PricingData(
                unitPrice: price,
                minOrderQty: 1,
                currency: "USD",
                distributor: "JLCPCB",
                lastUpdated: Date(timeIntervalSince1970: 0)
            )]
        }

        // Stock
        let stockData = [StockData(
            quantityAvailable: stock,
            distributor: "JLCPCB",
            leadTime: nil,
            lastUpdated: Date(timeIntervalSince1970: 0)
        )]

        let partNum = mpn.isEmpty ? lcsc : mpn

        return UnifiedComponent(
            partNumber: partNum,
            manufacturer: mfr,
            description: description,
            sources: [ComponentSource(
                provider: "jlcparts",
                providerPartId: lcsc,
                lastUpdated: Date(timeIntervalSince1970: 0),
                confidence: 0.5
            )],
            pricing: pricing,
            stock: stockData,
            specs: specs.isEmpty ? nil : specs,
            datasheetURL: nil,
            lcscPartNumber: lcsc.isEmpty ? nil : lcsc,
            category: category.isEmpty ? nil : category
        )
    }
}
