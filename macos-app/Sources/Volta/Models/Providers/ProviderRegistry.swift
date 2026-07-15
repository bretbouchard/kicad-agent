//
//  ProviderRegistry.swift
//  Volta
//
//  Phase 164 — LLM Provider Protocol (Task 5)
//
//  Holds all KiCadModelProvider instances and exposes the runtime-available
//  subset. `defaultProvider()` returns FoundationModels if available (MOD-06:
//  always the default), otherwise the first available local provider
//  (MLX if a model is downloaded), otherwise a clear "no providers available"
//  signal the UI surfaces as the ProviderBanner.
//
//  Per Pitfall 3 prevention: this is queried lazily, never cached at launch
//  beyond the initial probe — FoundationModels availability can change
//  (user enables Apple Intelligence in System Settings) and MLX availability
//  changes (user downloads a model).
//

import Foundation
import OSLog

/// Provider registry. One instance lives in the app environment (Phase 165
/// injects via @Environment). Phase 164 ships the read-only shape; mutation
/// (adding cloud providers with keys) lands with Phase 166 BYOK.
final class ProviderRegistry: ObservableObject, @unchecked Sendable {
    /// All registered providers. Local providers (Apple, MLX, mock) are
    /// added at init. Cloud providers added later via `register(_:)`.
    @Published private(set) var allProviders: [any KiCadModelProvider] = []

    /// Cached availability probe results. Keyed by ObjectIdentifier so
    /// identity-based lookup is O(1).
    private var availabilityCache: [ObjectIdentifier: KCProviderAvailability] = [:]
    private let cacheLock = NSLock()

    init(extraProviders: [any KiCadModelProvider] = []) {
        // ponytail: FoundationModels always present (built-in). MLX only
        // present if user has downloaded a model — Router adds MLX providers
        // dynamically in Phase 165 as models come and go. For Phase 164 the
        // registry ships with just FoundationModels + any extras (tests
        // inject mocks).
        let apple = AppleLocalProvider()
        self.allProviders = [apple] + extraProviders
    }

    /// Add a provider at runtime. Phase 166 uses this when user enters an
    /// API key (each cloud provider gets registered once its key is set).
    func register(_ provider: any KiCadModelProvider) {
        // Synchronize — ObservableObject + Sendable + mutate from anywhere.
        cacheLock.lock()
        defer { cacheLock.unlock() }
        // Avoid duplicates by displayName+kind.
        let key = "\(provider.kind.rawValue)::\(provider.displayName)"
        let existingKeys = allProviders.map { "\($0.kind.rawValue)::\($0.displayName)" }
        guard !existingKeys.contains(key) else { return }
        DispatchQueue.main.async { [weak self] in
            self?.allProviders.append(provider)
        }
    }

    /// Remove a registered provider by kind. Phase 166 BYOK uses this when
    /// the user deletes an API key — the provider instance must go too so
    /// `availability` queries stop returning `.requiresKey`.
    func unregister(kind: KCProviderKind) {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        DispatchQueue.main.async { [weak self] in
            self?.allProviders.removeAll { $0.kind == kind }
        }
    }

    /// Phase 166: seed cloud providers from the Keychain. Called at app
    /// launch and on key changes from the Settings UI.
    ///
    /// Only includes a provider when its key is configured (or it's a
    /// local-only provider like Ollama — no key required, just reachable).
    /// Per MOD-05: pure BYOK. Per MOD-11: cloud providers are optional —
    /// when no key is set, the router falls back to FoundationModels.
    func seedCloudProviders(from keychain: KeychainManager) {
        // Ollama is local — always register; its `availability` checks
        // daemon reachability rather than key presence.
        register(OllamaCloudProvider())

        // Cloud providers — only when their key exists.
        for kind in keychain.configuredProviders() {
            switch kind {
            case .openAI:
                register(OpenAICompatibleCloudProvider.openAI(keychain: keychain))
            case .anthropic:
                register(AnthropicCloudProvider(keychain: keychain))
            case .gemini:
                register(GeminiCloudProvider(keychain: keychain))
            case .groq:
                register(OpenAICompatibleCloudProvider.groq(keychain: keychain))
            case .xai:
                register(OpenAICompatibleCloudProvider.xai(keychain: keychain))
            case .together:
                register(OpenAICompatibleCloudProvider.together(keychain: keychain))
            case .ollama:
                // Already registered above (only one Ollama instance).
                break
            case .appleLocal, .mlxLocal, .mock:
                // Local — already seeded at init.
                break
            }
        }
    }

    /// All providers whose `availability` returned `.available` at last probe.
    /// Refreshes each call — UI binds to this and re-renders on changes.
    func availableProviders() async -> [any KiCadModelProvider] {
        var result: [any KiCadModelProvider] = []
        for provider in allProviders {
            let avail = await provider.availability
            self.cacheAvailability(avail, for: provider)
            if avail.isAvailable {
                result.append(provider)
            }
        }
        return result
    }

    /// The user's default provider. Per MOD-06: FoundationModels first,
    /// then MLX if available, then any local provider, then nil (UI shows
    /// ProviderBanner explaining the situation).
    func defaultProvider() async -> (any KiCadModelProvider)? {
        let available = await self.availableProviders()
        // 1. FoundationModels.
        if let apple = available.first(where: { $0.kind == .appleLocal }) {
            return apple
        }
        // 2. MLX local.
        if let mlx = available.first(where: { $0.kind == .mlxLocal }) {
            return mlx
        }
        // 3. Any local provider (mock in tests).
        if let local = available.first(where: { $0.kind.isLocal }) {
            return local
        }
        // 4. First cloud provider (Phase 166).
        return available.first
    }

    /// True when at least one local provider is available. Used by banner
    /// logic — if no local + no cloud, user is in "nothing works" mode.
    func hasAnyLocalAvailable() async -> Bool {
        let available = await self.availableProviders()
        return available.contains { $0.kind.isLocal }
    }

    // MARK: - Cache helpers

    private func cacheAvailability(_ avail: KCProviderAvailability, for provider: any KiCadModelProvider) {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        availabilityCache[ObjectIdentifier(provider as AnyObject)] = avail
    }

    /// ponytail: synchronous read of last-probed availability. Returns nil
    /// if no probe has run yet. Used by the banner on first render before
    /// async probes complete.
    func lastKnownAvailability(for provider: any KiCadModelProvider) -> KCProviderAvailability? {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        return availabilityCache[ObjectIdentifier(provider as AnyObject)]
    }
}
