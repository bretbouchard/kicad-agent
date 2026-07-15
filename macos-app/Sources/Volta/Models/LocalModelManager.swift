//
//  LocalModelManager.swift
//  Volta
//
//  Phase 210 — Local Model Lifecycle Manager
//
//  Scans for downloaded MLX models on launch, registers them with the
//  ProviderRegistry, and provides the bridge between ModelDownloader
//  completion and provider registration.
//

import Foundation
import OSLog

/// Manages local MLX model discovery and registration.
///
/// On app launch, scans ~/Library/Application Support/VoltaPCB/models/
/// for valid model directories and registers MLXLocalProvider instances
/// with the ProviderRegistry.
@MainActor
@Observable
final class LocalModelManager {

    /// Lifecycle state of the local Volta v2 model + adapter.
    var status: LocalModelStatus = .notDownloaded

    /// Whether the download sheet should be shown.
    var showDownloadSheet: Bool {
        switch status {
        case .downloaded: return false
        case .downloading, .notDownloaded, .downloadFailed, .adapterNotPublished: return true
        }
    }

    private var registry: ProviderRegistry

    init(registry: ProviderRegistry) {
        self.registry = registry
        scanAndRegister()
    }

    /// Scan the models directory for downloaded models and register them.
    func scanAndRegister() {
        let baseDir = ModelDownloader.baseModelDirectory
        let adapterDir = ModelDownloader.adapterDirectory

        guard ModelDownloader.isBaseModelPresent else {
            status = .notDownloaded
            Logger.appShell.info("No local model found — showing download prompt")
            return
        }

        // Check if adapter is present (v2 standard: adapter_model.safetensors)
        let isAdapter = ModelDownloader.isAdapterPresent

        // Distinguish 404 (repo not found) from other failures
        if !isAdapter {
            // Could be adapter not published or other issue - check for 404
            // We'll treat missing adapter as "adapter not published" for now
            status = .adapterNotPublished
            Logger.appShell.info("Adapter not published or not found")
            return
        }

        // Register the MLX provider with optional adapter.
        // MLXLocalProvider is excluded from Xcode builds (C module resolution
        // issue) but available in SPM builds. The #if guards let the Xcode
        // build succeed while the SPM build has full inference support.
        #if canImport(MLXLLM)
        let provider = MLXLocalProvider(
            modelURL: baseDir,
            modelId: ModelDownloader().baseModelRepo,  // "mlx-community/..." full HF id
            adapterURL: isAdapter ? adapterDir : nil
        )
        registry.register(provider)
        status = .downloaded
        Logger.appShell.info("Local model registered: \(provider.displayName)")
        #else
        // MLX not available — show download sheet but note generation
        // won't work without MLX. The user can still use cloud providers.
        status = .notDownloaded
        Logger.appShell.info("MLX provider not available — LLM generation requires cloud or Apple Intelligence")
        #endif
    }

    /// Called when a download completes — register the newly downloaded model.
    func onDownloadComplete() {
        scanAndRegister()
    }
}
