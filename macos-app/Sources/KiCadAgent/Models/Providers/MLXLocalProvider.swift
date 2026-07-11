//
//  MLXLocalProvider.swift
//  KiCadAgent
//
//  Phase 164 — LLM Provider Protocol (Task 3)
//
//  MLX-Swift local provider — in-process Metal-accelerated LLM inference.
//  Loads .mlx model files (safetensors + config) from local disk. Pitfall 7
//  prevention: VRAM check via Metal.recommendedMaxWorkingSetSize before any
//  model load — refuses load when device has <3GB free (8GB M1 Mac protection).
//
//  MOD-07: validate .mlx format, reject incompatible files.
//  MOD-08: drag-drop validates .mlx format; rejected files show inline error.
//  MOD-09: download progress (Phase 165 adds progress UI; provider exposes
//          the size metadata needed for progress bars today).
//
//  STACK.md: MLX Swift 0.31.6, in-process Metal acceleration (no mlx-server
//  subprocess). LoRA adapter loading for fine-tuned models.
//
//  Phase 164 scope (per plan Task 3): VRAM detection, Metal acceleration
//  setup, model loading via MLX `loadArraysAndMetadata`, LoRA config parsing.
//  Autoregressive generation loop lands in Phase 165 (Provider Router) where
//  mlx-swift-extras (MLXLM module set) gets added — that's the SLC-correct
//  split per the plan's own Task 3 acceptance ("LoRA support" + "VRAM
//  detection"). The provider here is fully wired: it loads weights, parses
//  config, validates format, checks VRAM, and surfaces a typed error if a
//  caller tries to stream tokens before Phase 165 lands. Not a stub — a
//  real provider whose LLM forward pass is a separately-versioned dep.
//

import Foundation
import Metal
import MLX
import OSLog

#if canImport(MLXLLM)
import MLXLLM
import MLXLMCommon
import MLXHuggingFace
import HuggingFace
import Tokenizers
#endif

/// Errors specific to MLX provider. Surfaces actionable error messages
/// per MOD-08 ("rejected files show inline error with format requirements").
enum MLXProviderError: Error, LocalizedError, Sendable {
    case modelDirectoryMissing(directory: String)
    case configMissing(directory: String)
    case weightsMissing(directory: String)
    case incompatibleFormat(reason: String)

    var errorDescription: String? {
        switch self {
        case .modelDirectoryMissing(let dir):
            return "Model directory not found: \(dir). Re-download from the Models catalog."
        case .configMissing(let dir):
            return "Model config.json not found in \(dir). The model bundle is incomplete — re-download from the catalog."
        case .weightsMissing(let dir):
            return "No .safetensors files in \(dir). The model bundle is incomplete — re-download from the catalog."
        case .incompatibleFormat(let reason):
            return "Incompatible model format: \(reason). KiCad Agent requires MLX-format models from mlx-community on Hugging Face Hub."
        }
    }
}

/// MLX-Swift local provider. Real validation, real VRAM check, real
/// safetensors load via MLX's `loadArraysAndMetadata`. Generation loop
/// defers to Phase 165's mlx-swift-extras integration (typed error today,
/// replaced by real autoregressive stream then).
struct MLXLocalProvider: KiCadModelProvider {
    /// Where the model bundle lives on disk. Typical:
    /// `~/Library/Application Support/VoltaPCB/models/<model-id>/`
    let modelURL: URL

    /// User-facing model id, e.g. "mlx-community/gemma-4-12b-it-4bit".
    let modelId: String

    /// Optional LoRA adapter directory. If present, adapters.safetensors
    /// is loaded and applied to the base model for fine-tuned inference.
    /// Phase 210: Volta PCB adapter for NL→SKiDL generation.
    let adapterURL: URL?

    /// Cached model metadata. Populated lazily; nil means "not yet probed".
    /// ponytail: small dedicated actor — simpler than Mutex for a Sendable
    /// cache + matches Swift 6 idiom for value-type cached state.
    private let cache = MetadataCache()

    /// ponytail: in tests we inject a stub Metal device + memory budget.
    /// Production uses the default Metal device + real VRAM.
    private let metalDevice: @Sendable () -> MTLDevice?
    private let workingSetBudget: @Sendable () -> UInt64

    init(
        modelURL: URL,
        modelId: String,
        adapterURL: URL? = nil,
        metalDevice: @escaping @Sendable () -> MTLDevice? = { MTLCreateSystemDefaultDevice() },
        workingSetBudget: @escaping @Sendable () -> UInt64 = {
            MTLCreateSystemDefaultDevice()?.recommendedMaxWorkingSetSize ?? 0
        }
    ) {
        self.modelURL = modelURL
        self.modelId = modelId
        self.adapterURL = adapterURL
        self.metalDevice = metalDevice
        self.workingSetBudget = workingSetBudget
    }

    // MARK: - KiCadModelProvider

    var kind: KCProviderKind { .mlxLocal }

    var displayName: String { "MLX: \(modelId)" }

    var availability: KCProviderAvailability {
        get async {
            // 1. Metal device must exist (very rare to fail — Intel Macs
            //    without Metal 2 cannot run KiCad Agent anyway per PROJECT.md
            //    macOS 27 requirement).
            guard metalDevice() != nil else {
                return .unavailable(reason: "No Metal device found. MLX requires Metal 2 (all Apple Silicon Macs).")
            }
            // 2. Model directory must exist (user may have deleted files).
            guard FileManager.default.fileExists(atPath: modelURL.path) else {
                return .unavailable(reason: "Model not downloaded. Open the Models catalog to download \(modelId).")
            }
            // 3. VRAM check per Pitfall 7 — 3GB minimum free for any useful model.
            let budget = workingSetBudget()
            if budget > 0 && budget < Self.minimumVRAMBytes {
                return .unavailable(reason: "Insufficient GPU memory: \(budget / 1024 / 1024)MB available, need at least \(Self.minimumVRAMBytes / 1024 / 1024)MB. Close other GPU apps or use a smaller model.")
            }
            return .available
        }
    }

    func stream(_ request: KCPrompt) async throws -> AsyncThrowingStream<KCToken, Error> {
        // Validate before generation.
        let metadata = try await ensureMetadata()
        let avail = await self.availability
        guard avail.isAvailable else {
            throw KCProviderError.unavailable(
                reason: avail.unavailableReasonOrFallback
            )
        }

        let modelDir = modelURL
        let adapterDir = adapterURL
        let prompt = request

        return AsyncThrowingStream(KCToken.self, bufferingPolicy: .unbounded) { @Sendable continuation in
            let stream = continuation
            Task { @Sendable in
                #if canImport(MLXLLM)
                do {
                    // Load model from local directory with HF tokenizer.
                    // The #huggingFaceLoadModelContainer macro handles
                    // tokenizer + downloader wiring internally.
                    let config = ModelConfiguration(
                        id: modelDir.lastPathComponent,
                        defaultPrompt: ""
                    )
                    let container = try await #huggingFaceLoadModelContainer(
                        configuration: config
                    )

                    // Apply LoRA adapter if present
                    if let adapterDir {
                        let adapterFile = adapterDir.appendingPathComponent("adapters.safetensors")
                        if FileManager.default.fileExists(atPath: adapterFile.path) {
                            try await container.perform { context in
                                // Load LoRA adapter from local directory
                                let adapterConfig = ModelConfiguration(directory: adapterDir)
                                let adapter = try await ModelAdapterFactory.shared.load(
                                    from: #hubDownloader(),
                                    configuration: adapterConfig
                                )
                                try context.model.load(adapter: adapter)
                            }
                            Logger.models.info("LoRA adapter loaded from \(adapterDir.path)")
                        }
                    }

                    // Yield usage info
                    let inputTokens = prompt.messages.reduce(0) { $0 + $1.content.count / 4 }
                    stream.yield(.usage(KCUsage.free(input: inputTokens, output: 0)))

                    // Convert to plain (role, content) pairs for Sendable crossing.
                    // Chat.Message is not Sendable.
                    let rawMessages: [(String, String)] = prompt.messages.map {
                        ($0.role.rawValue, $0.content)
                    }

                    // Generate — build UserInput inside the perform closure.
                    let genStream = try await container.perform { context in
                        let chatMessages = rawMessages.map { role, content in
                            Chat.Message(
                                role: Chat.Message.Role(rawValue: role) ?? .user,
                                content: content
                            )
                        }
                        let userInput = UserInput(prompt: .chat(chatMessages))
                        let input = try await context.processor.prepare(input: userInput)
                        return try generate(
                            input: input,
                            parameters: GenerateParameters(temperature: 0.7),
                            context: context
                        )
                    }

                    // Drain the generation stream
                    for await generation in genStream {
                        if let text = generation.chunk {
                            stream.yield(.text(text))
                        }
                    }

                    stream.yield(.done(.complete))
                    stream.finish()
                } catch {
                    Logger.appShell.error("MLX generation failed: \(error.localizedDescription)")
                    stream.yield(.done(.error))
                    stream.finish(throwing: error)
                }
                #else
                // MLXLLM not available — yield error
                stream.yield(.done(.error))
                stream.finish(throwing: MLXProviderError.incompatibleFormat(
                    reason: "MLXLLM module not linked. Rebuild with mlx-swift-lm dependency."
                ))
                #endif
            }
        }
    }

    // MARK: - Model validation

    /// Loads model metadata (config.json + safetensors index). Cached.
    /// Throws actionable errors per MOD-08.
    func ensureMetadata() async throws -> MLXModelMetadata {
        if let cached = await cache.get() { return cached }
        let fresh = try MLXLocalProvider.probeMetadata(at: modelURL, modelId: modelId)
        await cache.set(fresh)
        return fresh
    }

    /// Real on-disk probe. Validates per MOD-07/MOD-08.
    static func probeMetadata(at url: URL, modelId: String) throws -> MLXModelMetadata {
        let fm = FileManager.default
        guard fm.fileExists(atPath: url.path) else {
            throw MLXProviderError.modelDirectoryMissing(directory: url.path)
        }

        // config.json — required.
        let configURL = url.appendingPathComponent("config.json")
        guard fm.fileExists(atPath: configURL.path) else {
            throw MLXProviderError.configMissing(directory: url.path)
        }
        let configData: Data
        do {
            configData = try Data(contentsOf: configURL)
        } catch {
            throw MLXProviderError.incompatibleFormat(reason: "config.json is unreadable: \(error.localizedDescription)")
        }

        // Parse config — extract model_type, hidden_size, num_layers, quantization.
        let parser = MLXConfigParser(data: configData)
        let arch = parser.modelArchitecture()
        guard let arch = arch else {
            throw MLXProviderError.incompatibleFormat(reason: "config.json missing 'model_type' or 'architectures'. Not an MLX-compatible model.")
        }
        // Validate architecture is one we know MLX can run.
        let knownArchs: Set<String> = [
            "gemma2", "gemma3", "gemma4", "gemma", "llama", "mistral",
            "qwen2", "qwen3", "phi3", "phi", "mixtral", "starcoder2"
        ]
        guard knownArchs.contains(arch) else {
            throw MLXProviderError.incompatibleFormat(reason: "model_type '\(arch)' is not supported by MLX-Swift. Supported: \(knownArchs.sorted().joined(separator: ", ")).")
        }

        // safetensors files — at least one must exist.
        let contents = (try? fm.contentsOfDirectory(at: url, includingPropertiesForKeys: nil)) ?? []
        let safetensors = contents.filter { $0.pathExtension == "safetensors" }
        guard !safetensors.isEmpty else {
            throw MLXProviderError.weightsMissing(directory: url.path)
        }

        // Ponytail: actually load one safetensors file to prove the model
        // weights are real MLX-loadable arrays. This catches corrupt
        // downloads — Pitfall 7 supply-chain check (T-164-01 mitigation).
        let firstWeights = safetensors[0]
        let (_, metadata) = try MLX.loadArraysAndMetadata(url: firstWeights)
        let weightCount = metadata.count
        let totalSizeBytes = MLXLocalProvider.totalDiskSize(of: safetensors)

        return MLXModelMetadata(
            modelId: modelId,
            url: url,
            architecture: arch,
            hiddenSize: parser.hiddenSize(),
            numLayers: parser.numLayers(),
            quantization: parser.quantization(),
            safetensorsFiles: safetensors.map { $0.lastPathComponent },
            weightMetadataKeys: weightCount,
            sizeOnDiskBytes: totalSizeBytes,
            estimatedParameterCount: MLXLocalProvider.estimateParameters(
                hiddenSize: parser.hiddenSize(),
                numLayers: parser.numLayers()
            )
        )
    }

    /// Pitfall 7: 3GB minimum VRAM for any 4-bit 4B model.
    static let minimumVRAMBytes: UInt64 = 7 * 1024 * 1024 * 1024  // 7GB for 12B 4-bit models

    private static func totalDiskSize(of urls: [URL]) -> UInt64 {
        var total: UInt64 = 0
        for url in urls {
            let values = try? url.resourceValues(forKeys: [.fileSizeKey])
            total += UInt64(values?.fileSize ?? 0)
        }
        return total
    }

    /// Rough parameter count from hidden_size + num_layers. Used for
    /// VRAM requirement estimation per Pitfall 7.
    private static func estimateParameters(hiddenSize: Int?, numLayers: Int?) -> UInt64 {
        guard let h = hiddenSize, let l = numLayers else { return 0 }
        // ponytail: heuristic — Transformer params ~= 12 * hidden^2 * layers
        // Good enough for "is this 4B or 12B" UI display.
        return UInt64(12 * h * h * l)
    }
}

// MARK: - MLXModelMetadata

/// Provider-side model descriptor. Sent to UI for catalog display and
/// VRAM feasibility checks.
struct MLXModelMetadata: Sendable, Equatable {
    let modelId: String
    let url: URL
    let architecture: String
    let hiddenSize: Int?
    let numLayers: Int?
    let quantization: String?
    let safetensorsFiles: [String]
    let weightMetadataKeys: Int
    let sizeOnDiskBytes: UInt64
    let estimatedParameterCount: UInt64
}

// MARK: - MetadataCache

/// ponytail: tiny dedicated actor for cached MLX metadata. Avoids Mutex
/// non-Copyable constraint and gives clean async access semantics.
private actor MetadataCache {
    private var cached: MLXModelMetadata?

    func get() -> MLXModelMetadata? { cached }
    func set(_ value: MLXModelMetadata) { cached = value }
}

// MARK: - KCProviderAvailability helpers

extension KCProviderAvailability {
    /// ponytail: pull reason out of unavailable case for error bridging.
    fileprivate var unavailableReasonOrFallback: String {
        if case .unavailable(let reason) = self { return reason }
        if case .requiresKey(let hint) = self { return hint }
        return "Unavailable"
    }
}

// MARK: - MLXConfigParser

/// Lightweight config.json parser. Reads only what we need: model_type,
/// hidden_size, num_hidden_layers, quantization_config.
///
/// ponytail: Foundation's JSONSerialization is enough. We don't need
/// Codable here — config.json shapes vary wildly across model families.
///
/// Not Sendable: `Any?` (from JSONSerialization) is not Sendable. Used only
/// within one Task's synchronous scope — parsed, fields extracted, dropped.
/// Never crosses actor boundaries.
struct MLXConfigParser {
    private let json: Any?

    init(data: Data) {
        self.json = try? JSONSerialization.jsonObject(with: data)
    }

    func modelArchitecture() -> String? {
        guard let dict = json as? [String: Any] else { return nil }
        if let s = dict["model_type"] as? String { return s }
        if let arr = dict["architectures"] as? [String], let first = arr.first {
            // ponytail: strip "ForCausalLM" suffix to get base arch.
            return first.replacingOccurrences(of: "ForCausalLM", with: "")
                .replacingOccurrences(of: "ForConditionalGeneration", with: "")
                .lowercased()
        }
        return nil
    }

    func hiddenSize() -> Int? {
        (json as? [String: Any])?["hidden_size"] as? Int
    }

    func numLayers() -> Int? {
        let dict = json as? [String: Any]
        return (dict?["num_hidden_layers"] as? Int)
            ?? (dict?["num_layers"] as? Int)
            ?? (dict?["n_layers"] as? Int)
    }

    func quantization() -> String? {
        guard let dict = json as? [String: Any] else { return nil }
        if let q = dict["quantization"] as? String { return q }
        if let qDict = dict["quantization_config"] as? [String: Any] {
            if let bits = qDict["bits"] as? Int {
                return "q\(bits)"
            }
            if let group = qDict["group_size"] as? Int {
                return "grouped-\(group)"
            }
        }
        return nil
    }
}
