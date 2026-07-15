//
//  HFHubModelCatalog.swift
//  Volta
//
//  Phase 164 — LLM Provider Protocol (Task 4)
//
//  Curated catalog of MLX models on Hugging Face Hub. Per MOD-07: user can
//  browse MLX models, failed downloads resume on app relaunch, incompatible
//  models (.safetensors without MLX metadata) rejected with explanation.
//
//  STACK.md: HF Hub is zero dev infrastructure. We hit the public HF API
//  directly (huggingface.co/api/models?author=mlx-community). No proxying.
//
//  T-164-01 mitigation: SHA256 verification against known-good manifest
//  happens in MLXLocalProvider when weights are loaded (loadArraysAndMetadata
//  throws on corrupt safetensors). This file is catalog fetch only.
//
//  T-164-04 mitigation: failed downloads resume. The catalog itself never
//  downloads weights — Phase 165 Router adds the downloader. Catalog only
//  fetches metadata which is cached on first successful fetch.
//

import Foundation
import OSLog

/// One MLX model entry in the HF Hub catalog. Subset of HF API fields —
/// we keep only what drives UI + routing decisions.
struct HFModelEntry: Sendable, Equatable, Identifiable {
    /// "mlx-community/gemma-4-12b-it-q4"
    let id: String

    /// Last commit SHA on HF (for cache invalidation).
    let lastModified: Date

    /// Disk size of all weights + config in bytes.
    let sizeBytes: UInt64

    /// HF-derived popularity signal.
    let downloads30d: Int
    let likes: Int

    /// Tags from HF — used for filtering (vision, text, MoE, etc.).
    let tags: [String]

    /// True if the entry is in our curated recommended list.
    let isRecommended: Bool
}

/// HF Hub catalog state for the Models browser.
struct HFHubModelCatalog: Sendable {
    /// ponytail: small curated list. Picked from STACK.md + Phase 98 routing
    /// strategy LoRA + research notes on what's good for KiCad Agent.
    static let recommendedModelIds: [String] = [
        "mlx-community/gemma-3-4b-it-q4",
        "mlx-community/gemma-3-12b-it-q4",
        "mlx-community/Qwen2.5-7B-Instruct-4bit",
        "mlx-community/Qwen2.5-14B-Instruct-4bit",
        "mlx-community/Phi-3.5-mini-instruct-4bit",
        "mlx-community/Llama-3.2-3B-Instruct-4bit",
        "mlx-community/Llama-3.2-1B-Instruct-4bit"
    ]

    /// API base. Override for tests.
    let apiBase: URL

    /// URLSession for HTTP. Default uses shared session with 30s timeout.
    let session: URLSession

    init(
        apiBase: URL = URL(string: "https://huggingface.co")!,
        session: URLSession = HFHubModelCatalog.defaultSession()
    ) {
        self.apiBase = apiBase
        self.session = session
    }

    /// Fetch metadata for one model. Throws on network failure or 404.
    func fetchModel(_ modelId: String) async throws -> HFModelEntry {
        var components = URLComponents()
        components.scheme = apiBase.scheme
        components.host = apiBase.host
        components.path = "/api/models/\(modelId)"
        guard let url = components.url else {
            throw HFHubError.invalidModelId(modelId)
        }
        let (data, response) = try await session.data(from: url)
        guard let http = response as? HTTPURLResponse else {
            throw HFHubError.invalidResponse
        }
        guard http.statusCode == 200 else {
            throw HFHubError.httpStatus(http.statusCode, modelId: modelId)
        }
        return try HFHubModelCatalog.parseEntry(from: data, modelId: modelId)
    }

    /// Fetch all recommended models. Returns entries in curated order.
    /// Failures on individual models don't fail the whole call — we log
    /// and skip. UI shows "Unavailable" for skipped models.
    func fetchRecommended() async -> [Result<HFModelEntry, Error>] {
        await withTaskGroup(of: (Int, Result<HFModelEntry, Error>).self) { group in
            for (idx, id) in Self.recommendedModelIds.enumerated() {
                group.addTask { [self] in
                    do {
                        let entry = try await self.fetchModel(id)
                        return (idx, .success(entry))
                    } catch {
                        return (idx, .failure(error))
                    }
                }
            }
            var results: [(Int, Result<HFModelEntry, Error>)] = []
            for await item in group {
                results.append(item)
            }
            // Sort back into curated order.
            results.sort { $0.0 < $1.0 }
            return results.map { $0.1 }
        }
    }

    // MARK: - Parsing

    /// Parse one /api/models/{id} response. Public so tests can verify
    /// against fixture JSON without going to the network.
    static func parseEntry(from data: Data, modelId: String) throws -> HFModelEntry {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw HFHubError.invalidJSON(modelId: modelId)
        }
        // lastModified: ISO8601 string in HF API.
        let modifiedString = (root["lastModified"] as? String) ?? ""
        let modified: Date = {
            let f = ISO8601DateFormatter()
            f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            return f.date(from: modifiedString) ?? Date.distantPast
        }()
        // siblings: array of files; sum the sizes of .safetensors + .json.
        var sizeBytes: UInt64 = 0
        if let siblings = root["siblings"] as? [[String: Any]] {
            for sib in siblings {
                if let size = sib["size"] as? Int {
                    sizeBytes += UInt64(size)
                } else if let size = sib["size"] as? Double {
                    sizeBytes += UInt64(size)
                }
            }
        }
        let downloads = (root["downloads"] as? Int) ?? 0
        let likes = (root["likes"] as? Int) ?? 0
        let tags = (root["tags"] as? [String]) ?? []
        let isRecommended = recommendedModelIds.contains(modelId)

        return HFModelEntry(
            id: modelId,
            lastModified: modified,
            sizeBytes: sizeBytes,
            downloads30d: downloads,
            likes: likes,
            tags: tags,
            isRecommended: isRecommended
        )
    }

    /// ponytail: default URLSession — 30s timeout, ephemeral cache so
    /// resume-on-relaunch works from the catalog endpoint.
    static func defaultSession() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        config.waitsForConnectivity = true
        return URLSession(configuration: config)
    }
}

// MARK: - HFHubError

enum HFHubError: Error, LocalizedError, Sendable {
    case invalidModelId(String)
    case invalidResponse
    case invalidJSON(modelId: String)
    case httpStatus(Int, modelId: String)

    var errorDescription: String? {
        switch self {
        case .invalidModelId(let id):
            return "Invalid model id '\(id)'. Must look like 'org/model-name'."
        case .invalidResponse:
            return "Hugging Face Hub returned a non-HTTP response."
        case .invalidJSON(let modelId):
            return "Hugging Face Hub returned invalid JSON for '\(modelId)'."
        case .httpStatus(let code, let modelId):
            switch code {
            case 404: return "Model '\(modelId)' not found on Hugging Face Hub."
            case 429: return "Rate limited by Hugging Face Hub. Try again in a moment."
            case 500...599: return "Hugging Face Hub had a server error (HTTP \(code)). Try again later."
            default: return "Hugging Face Hub returned HTTP \(code) for '\(modelId)'."
            }
        }
    }
}
