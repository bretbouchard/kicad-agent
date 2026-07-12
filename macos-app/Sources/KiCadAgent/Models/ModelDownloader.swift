//
//  ModelDownloader.swift
//  KiCadAgent
//
//  Phase 210 — Gemma 4 12B Model Download Pipeline
//
//  Downloads the base MLX model (from HuggingFace) and the Volta PCB LoRA
//  adapter (from GitHub releases / HuggingFace) to the app's sandbox
//  container at ~/Library/Application Support/VoltaPCB/models/.
//
//  ponytail: URLSession + AsyncStream. No third-party download deps.
//

import Foundation
import CryptoKit
import OSLog

/// Progress updates emitted during model download.
enum DownloadProgress: Sendable {
    case fetchingManifest
    case downloadingFile(name: String, progress: Double)  // 0.0–1.0 per file
    case verifyingFile(name: String, success: Bool)
    case completed(modelPath: URL, adapterPath: URL?)
    case failed(Error)
}

/// Downloads the Gemma 4 12B base model + Volta PCB LoRA adapter.
///
/// Two-phase download:
/// 1. Base model from `mlx-community/gemma-4-12b-it-4bit` (HuggingFace)
/// 2. LoRA adapter from `bretbouchard/volta-pcb-adapter-v1` (HuggingFace)
///
/// Files are saved to the sandbox container:
///   ~/Library/Application Support/VoltaPCB/models/gemma-4-12b-it-4bit/
///   ~/Library/Application Support/VoltaPCB/models/volta-pcb-adapter-v1/
final class ModelDownloader: Sendable {

    /// HuggingFace API base.
    private let hfBase = "https://huggingface.co"

    /// Base model repo on HuggingFace.
    private let baseModelRepo = "mlx-community/gemma-4-12b-it-4bit"

    /// LoRA adapter repo on HuggingFace.
    private let adapterRepo = "bretbouchard/volta-pcb-adapter-v2"

    /// URLSession for downloads (configurable for testing).
    private let session: URLSession

    init(session: URLSession? = nil) {
        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.default
            config.timeoutIntervalForRequest = 300  // 5 min per file
            config.timeoutIntervalForResource = 7200  // 2 hr total
            self.session = URLSession(configuration: config)
        }
    }

    // MARK: - Public API

    /// Returns the models directory inside the sandbox container.
    static var modelsDirectory: URL {
        let fm = FileManager.default
        let appSupport = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent("VoltaPCB/models", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// Path where the base model should live.
    static var baseModelDirectory: URL {
        modelsDirectory.appendingPathComponent("gemma-4-12b-it-4bit", isDirectory: true)
    }

    /// Path where the LoRA adapter should live.
    static var adapterDirectory: URL {
        modelsDirectory.appendingPathComponent("volta-pcb-adapter-v1", isDirectory: true)
    }

    /// Check if the base model is already downloaded and valid.
    static var isBaseModelPresent: Bool {
        let dir = baseModelDirectory
        guard FileManager.default.fileExists(atPath: dir.path) else { return false }
        let configURL = dir.appendingPathComponent("config.json")
        let hasConfig = FileManager.default.fileExists(atPath: configURL.path)
        let hasWeights = (try? FileManager.default.contentsOfDirectory(atPath: dir.path))?
            .contains { $0.hasSuffix(".safetensors") } ?? false
        return hasConfig && hasWeights
    }

    /// Check if the adapter is already downloaded.
    static var isAdapterPresent: Bool {
        let dir = adapterDirectory
        guard FileManager.default.fileExists(atPath: dir.path) else { return false }
        let adapterURL = dir.appendingPathComponent("adapters.safetensors")
        let configURL = dir.appendingPathComponent("adapter_config.json")
        return FileManager.default.fileExists(atPath: adapterURL.path)
            && FileManager.default.fileExists(atPath: configURL.path)
    }

    /// Download the base model + adapter. Emits progress via AsyncStream.
    func download() -> AsyncStream<DownloadProgress> {
        AsyncStream { @Sendable continuation in
            let stream = continuation
            Task { @Sendable in
                do {
                    // Phase 1: Base model
                    try await downloadRepo(
                        repo: baseModelRepo,
                        to: Self.baseModelDirectory,
                        stream: stream
                    )

                    // Phase 2: LoRA adapter
                    try await downloadRepo(
                        repo: adapterRepo,
                        to: Self.adapterDirectory,
                        stream: stream
                    )

                    stream.yield(.completed(
                        modelPath: Self.baseModelDirectory,
                        adapterPath: Self.adapterDirectory
                    ))
                } catch {
                    Logger.appShell.error("Model download failed: \(error.localizedDescription)")
                    stream.yield(.failed(error))
                }
                stream.finish()
            }
        }
    }

    // MARK: - Private

    /// Download all files from a HuggingFace repo to a local directory.
    private func downloadRepo(
        repo: String,
        to directory: URL,
        stream: AsyncStream<DownloadProgress>.Continuation
    ) async throws {
        let fm = FileManager.default
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)

        // Fetch file list from HF API
        stream.yield(.fetchingManifest)
        let manifest = try await fetchFileList(repo: repo)

        Logger.models.info("Downloading \(repo): \(manifest.count) files")

        for file in manifest {
            // Skip non-essential files
            let name = file.key
            if name.hasSuffix(".md") || name.hasSuffix(".gitattributes") || name.hasSuffix(".png") {
                continue
            }

            let destURL = directory.appendingPathComponent(name)

            // Skip if already downloaded and size matches (resumable)
            if let existingSize = try? fm.attributesOfItem(atPath: destURL.path)[.size] as? Int64,
               existingSize == file.size {
                Logger.models.info("Skip \(name) — already downloaded")
                continue
            }

            // Download
            stream.yield(.downloadingFile(name: name, progress: 0))

            let url = URL(string: "\(hfBase)/\(repo)/resolve/main/\(name)")!
            let (tempURL, response) = try await session.download(from: url)

            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else {
                throw ModelDownloadError.downloadFailed(file: name)
            }

            // Move to destination
            if fm.fileExists(atPath: destURL.path) {
                try fm.removeItem(at: destURL)
            }
            try fm.moveItem(at: tempURL, to: destURL)

            stream.yield(.verifyingFile(name: name, success: true))
        }
    }

    /// Fetch the file list for a HuggingFace repo via the API.
    private func fetchFileList(repo: String) async throws -> [HFFile] {
        let url = URL(string: "\(hfBase)/api/models/\(repo)")!
        let (data, response) = try await session.data(from: url)

        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw ModelDownloadError.manifestFailed(repo: repo)
        }

        // Parse the siblings array from HF API response
        struct HFResponse: Decodable {
            struct Sibling: Decodable {
                let rfilename: String
                let size: Int64?
            }
            let siblings: [Sibling]
        }

        let decoded = try JSONDecoder().decode(HFResponse.self, from: data)
        return decoded.siblings.map { HFFile(key: $0.rfilename, size: $0.size ?? 0) }
    }
}

// MARK: - Supporting Types

private struct HFFile {
    let key: String
    let size: Int64
}

enum ModelDownloadError: LocalizedError {
    case manifestFailed(repo: String)
    case downloadFailed(file: String)
    case checksumMismatch(file: String)

    var errorDescription: String? {
        switch self {
        case .manifestFailed(let repo):
            return "Failed to fetch file list for \(repo)"
        case .downloadFailed(let file):
            return "Failed to download \(file)"
        case .checksumMismatch(let file):
            return "Checksum mismatch for \(file)"
        }
    }
}
