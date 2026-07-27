//
//  OctopartCADProvider.swift
//  Volta
//
//  Phase 2 / Task 1 — Octopart/Nexar CAD Provider
//
//  CADModelProvider backed by Nexar GraphQL API.
//  Octopart aggregates 850K+ KiCad models (SnapEDA-sourced).
//  Secondary CAD source — used when easyeda2kicad misses.
//

import Foundation
import OSLog
import VoltaPCBCore

/// CAD model provider backed by Nexar/Octopart GraphQL API.
/// Queries SnapEDA-sourced footprints, symbols, and 3D models.
final class OctopartCADProvider: CADModelProvider, @unchecked Sendable {
    let name = "octopart-cad"
    let displayName = "Octopart CAD (SnapEDA)"
    let capabilities: Set<ProviderCapability> = [.footprints, .symbols, .models3D]

    private let session: URLSession
    private let graphqlURL = URL(string: "https://api.nexar.com/graphql")!
    private let authProvider: OctopartProvider

    init(authProvider: OctopartProvider) {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 30
        self.session = URLSession(configuration: config)
        self.authProvider = authProvider
    }

    var availability: ProviderAvailability {
        get async { await authProvider.availability }
    }

    // MARK: - CADModelProvider

    func searchCADModels(keyword: String) async throws -> [UnifiedComponent] {
        // CAD search via keyword isn't supported — Octopart CAD is MPN/LCSC based.
        // The MergeEngine will call getCADModels(lcscPartNumber:) for specific parts.
        return []
    }

    func getCADModels(lcscPartNumber: String) async throws -> [CADModelRef] {
        let token = try await authProvider.ensureTokenPublic()

        // Query SnapEDA for CAD models by MPN
        let query = """
        query CadModels($mpn: String!) {
          supSearch(q: $mpn, limit: 1) {
            results {
              part {
                mpn
                cad {
                  kicadFootprint { url name }
                  kicadSymbol { url name }
                  step { url }
                }
              }
            }
          }
        }
        """

        let payload: [String: Any] = [
            "query": query,
            "variables": ["mpn": lcscPartNumber]
        ]

        let body = try JSONSerialization.data(withJSONObject: payload)
        var req = URLRequest(url: graphqlURL)
        req.httpMethod = "POST"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = body

        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            Logger.models.error("Octopart CAD: HTTP error for \(lcscPartNumber)")
            return []
        }

        return try parseCADResponse(data)
    }

    // MARK: - Parsing

    private func parseCADResponse(_ data: Data) throws -> [CADModelRef] {
        struct GraphqlResponse: Codable {
            let data: SearchData?
        }
        struct SearchData: Codable {
            let supSearch: SupSearch?
        }
        struct SupSearch: Codable {
            let results: [SearchResult]?
        }
        struct SearchResult: Codable {
            let part: Part?
        }
        struct Part: Codable {
            let cad: CAD?
        }
        struct CAD: Codable {
            let kicadFootprint: CADFile?
            let kicadSymbol: CADFile?
            let step: StepFile?
        }
        struct CADFile: Codable {
            let url: String?
            let name: String?
        }
        struct StepFile: Codable {
            let url: String?
        }

        let decoded = try JSONDecoder().decode(GraphqlResponse.self, from: data)
        guard let part = decoded.data?.supSearch?.results?.first?.part?.cad else { return [] }
        let now = Date()
        var refs: [CADModelRef] = []

        if let fp = part.kicadFootprint, let url = fp.url {
            refs.append(CADModelRef(filePath: url, format: .kicadMod, source: name, cachedDate: now))
        }
        if let sym = part.kicadSymbol, let url = sym.url {
            refs.append(CADModelRef(filePath: url, format: .kicadSym, source: name, cachedDate: now))
        }
        if let step = part.step, let url = step.url {
            refs.append(CADModelRef(filePath: url, format: .step, source: name, cachedDate: now))
        }

        return refs
    }
}
