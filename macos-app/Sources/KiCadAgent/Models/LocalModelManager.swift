//
//  LocalModelManager.swift
//  KiCadAgent
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

    /// Whether a local model is currently registered and available.
    var hasLocalModel: Bool = false

    /// Whether the download sheet should be shown.
    var showDownloadSheet: Bool = false

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
            hasLocalModel = false
            showDownloadSheet = true
            Logger.appShell.info("No local model found — showing download prompt")
            return
        }

        // Register the MLX provider with optional adapter
        let provider = MLXLocalProvider(
            modelURL: baseDir,
            modelId: "gemma-4-12b-it-4bit",
            adapterURL: ModelDownloader.isAdapterPresent ? adapterDir : nil
        )
        registry.register(provider)
        hasLocalModel = true
        showDownloadSheet = false
        Logger.appShell.info("Local model registered: \(provider.displayName)")
    }

    /// Called when a download completes — register the newly downloaded model.
    func onDownloadComplete() {
        scanAndRegister()
    }
}
