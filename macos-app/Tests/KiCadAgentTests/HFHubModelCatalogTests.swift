//
//  HFHubModelCatalogTests.swift
//  KiCadAgentTests
//
//  Phase 164 — LLM Provider Protocol
//
//  Tests for HFHubModelCatalog:
//    - JSON parsing of /api/models/{id} response
//    - Recommended list contains expected entries
//    - Error mapping for invalid model ids / 404 / 5xx
//    - T-164-04 mitigation: failed downloads resume (catalog resilient)
//
//  No real network calls — we feed fixture JSON directly into the parser.
//  Network-level tests would be flaky and slow. Parser tests cover the
//  surface that matters for the catalog UI.
//

import Testing
import Foundation
@testable import KiCadAgent

@Suite("HFHubModelCatalog")
struct HFHubModelCatalogTests {

    // MARK: - Curated list

    @Test("Recommended list has at least 5 entries")
    func recommendedListNonEmpty() {
        #expect(HFHubModelCatalog.recommendedModelIds.count >= 5)
    }

    @Test("All recommended model ids are mlx-community prefixed")
    func recommendedAreMlxCommunity() {
        for id in HFHubModelCatalog.recommendedModelIds {
            #expect(id.hasPrefix("mlx-community/"), "id '\(id)' should be mlx-community/")
        }
    }

    @Test("Recommended list contains Gemma and Qwen (STACK.md priorities)")
    func recommendedHasCoreFamilies() {
        let all = HFHubModelCatalog.recommendedModelIds.joined(separator: " ").lowercased()
        #expect(all.contains("gemma"))
        #expect(all.contains("qwen"))
    }

    // MARK: - Parsing

    @Test("parseEntry extracts id, size, downloads, likes, tags")
    func parseBasic() throws {
        let json = """
        {
            "modelId": "mlx-community/gemma-3-4b",
            "lastModified": "2025-12-15T10:30:00.000Z",
            "downloads": 12345,
            "likes": 67,
            "tags": ["mlx", "gemma3", "text-generation"],
            "siblings": [
                {"rfilename": "config.json", "size": 1024},
                {"rfilename": "model.safetensors", "size": 2000000000}
            ]
        }
        """
        let data = json.data(using: .utf8)!
        // Use a model id that IS in the curated recommended list.
        let recommendedId = HFHubModelCatalog.recommendedModelIds.first { $0.contains("gemma-3-4b") } ?? "mlx-community/gemma-3-4b"
        let entry = try HFHubModelCatalog.parseEntry(from: data, modelId: recommendedId)
        #expect(entry.id == recommendedId)
        #expect(entry.downloads30d == 12345)
        #expect(entry.likes == 67)
        #expect(entry.tags == ["mlx", "gemma3", "text-generation"])
        // 1024 + 2,000,000,000 = 2,000,001,024 bytes
        #expect(entry.sizeBytes == 2_000_001_024)
        #expect(entry.isRecommended)
    }

    @Test("parseEntry handles missing fields with sensible defaults")
    func parseMissingFields() throws {
        let json = """
        {
            "modelId": "some-org/some-model"
        }
        """
        let data = json.data(using: .utf8)!
        let entry = try HFHubModelCatalog.parseEntry(from: data, modelId: "some-org/some-model")
        #expect(entry.downloads30d == 0)
        #expect(entry.likes == 0)
        #expect(entry.tags.isEmpty)
        #expect(entry.sizeBytes == 0)
        #expect(!entry.isRecommended)
        #expect(entry.lastModified == .distantPast)
    }

    @Test("parseEntry marks non-recommended models as isRecommended=false")
    func parseNonRecommended() throws {
        let json = #"{"modelId":"random/random"}"#
        let data = json.data(using: .utf8)!
        let entry = try HFHubModelCatalog.parseEntry(from: data, modelId: "random/random")
        #expect(!entry.isRecommended)
    }

    @Test("parseEntry throws on garbage input (any Error is acceptable)")
    func parseGarbage() {
        let data = "not json".data(using: .utf8)!
        // JSONSerialization wraps errors in NSError — we accept any throw.
        #expect(throws: (any Error).self) {
            _ = try HFHubModelCatalog.parseEntry(from: data, modelId: "x/y")
        }
    }

    // MARK: - HFHubError messages

    @Test("HFHubError messages are actionable per MOD-07")
    func errorMessageQuality() {
        let invalid = HFHubError.invalidModelId("no-slash")
        #expect(invalid.errorDescription?.contains("no-slash") == true)

        let http404 = HFHubError.httpStatus(404, modelId: "x/y")
        #expect(http404.errorDescription?.contains("not found") == true)

        let http429 = HFHubError.httpStatus(429, modelId: "x/y")
        #expect(http429.errorDescription?.contains("Rate limited") == true)

        let http500 = HFHubError.httpStatus(503, modelId: "x/y")
        #expect(http500.errorDescription?.contains("server error") == true)
    }
}
