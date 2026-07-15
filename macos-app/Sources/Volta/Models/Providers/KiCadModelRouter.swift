//
//  KiCadModelRouter.swift
//  Volta
//
//  Phase 165 — Provider Router
//
//  Task-aware, cost-aware, privacy-aware model router. Implements MOD-02
//  routing rules:
//    - privacySensitive → always AppleLocal (never cloud, never logged out)
//    - vision → cloud with vision capability OR MLX with Gemma vision,
//               else AppleLocal with one-time fallback notification
//    - complexReasoning → user's preferred (or AppleLocal fallback per MOD-11)
//    - quickReply → AppleLocal (free, fast)
//
//  Per MOD-10: user can pick preferred model per task type via Settings.
//  Per MOD-11: falls back to FoundationModels when no cloud keys configured.
//  Per MOD-02 augmentation: unavailable preferred model falls back to
//                            FoundationModels with one-time notification.
//
//  Per MOD-12: every call routes through `record(usage:)` so the cost ledger
//  captures per-message token counts + cost. Per-message badges in chat UI
//  consume KCUsage directly from the KCToken stream; the ledger is for
//  aggregate tracking in Settings.
//
//  Architecture: the router is an ObservableObject so Settings UI re-renders
//  when preferences change. It holds a [KCProviderKind: KiCadModelProvider]
//  map populated at init from the Phase 164 ProviderRegistry. Cloud providers
//  (openAI/anthropic/etc.) are added by Phase 166 BYOK wiring; Phase 165's
//  router works correctly when that map is empty (everything falls back to
//  AppleLocal per MOD-11).
//

import Foundation
import OSLog

/// User-tunable preferences. Persisted to UserDefaults (Phase 166+ adds
/// SwiftData persistence; Phase 165 ships the in-memory shape + UserDefaults
/// round-trip). Observable so the Settings UI mutates and the router picks
/// up changes immediately.
struct KCRoutingPreferences: Sendable, Equatable, Codable {
    /// Per-task-type preferred provider. Keyed by `preferenceCategory` so
    /// the four user-visible categories (quickReply, complexReasoning,
    /// vision, privacySensitive) drive all routing decisions; internal
    /// pipeline stages map onto them via `KCTaskType.preferenceCategory`.
    var preferredProviderPerTask: [KCTaskType: KCProviderKind]

    /// True = force every task to a local provider (FoundationModels/MLX).
    /// Per MOD-02 augmentation: privacy mode is a global toggle.
    var privacyMode: Bool

    /// User-friendly cost ceiling for the Settings UI warning. Per T-165-03
    /// mitigation. The ledger independently enforces its own per-message
    /// threshold; this is the user-facing knob.
    var costWarningThresholdUSD: Decimal

    static let `default` = KCRoutingPreferences(
        preferredProviderPerTask: [:],  // empty = use router defaults
        privacyMode: false,
        costWarningThresholdUSD: KCCostLedger.defaultPerMessageWarningThreshold
    )

    // ponytail: non-isolated default accessor for use outside MainActor
    // contexts (e.g. other static initializers). The struct itself is pure
    // data; the @MainActor isolation lives on KiCadModelRouter only.
    nonisolated static var defaults: KCRoutingPreferences { .default }
}

/// Task-aware, cost-aware, privacy-aware model router.
///
/// `selectProvider(for:)` returns the right `KiCadModelProvider` for a task,
/// applying privacy-mode override, user preferences, and fallback rules.
/// `route(prompt:)` is the one-shot convenience that classifies + selects
/// in a single call.
@MainActor
final class KiCadModelRouter: ObservableObject {
    /// Provider instances by kind. Built at init from the Phase 164
    /// ProviderRegistry; Phase 166 adds cloud entries when API keys land.
    @Published private(set) var providers: [KCProviderKind: any KiCadModelProvider]

    /// User-tunable preferences. Mutated by Settings UI; observable so the
    /// UI re-renders on change.
    @Published var preferences: KCRoutingPreferences

    /// Cost ledger. Observable so Settings summary re-renders on each call.
    @Published private(set) var ledger: KCCostLedger

    /// Fallback notifier. Dedupes one-time-per-shape notifications.
    let notifier: KCRoutingNotifier

    /// Convenience: the FoundationModels provider. Always present in the
    /// map; unwrapped here so fallback paths don't have to re-fetch.
    private var appleLocal: any KiCadModelProvider {
        // Defensively fall back to creating a fresh AppleLocalProvider if
        // the map was constructed without one (test scenarios). Production
        // always seeds one via ProviderRegistry.
        if let p = providers[.appleLocal] { return p }
        let fresh = AppleLocalProvider()
        providers[.appleLocal] = fresh
        return fresh
    }

    init(
        providers: [KCProviderKind: any KiCadModelProvider] = [:],
        preferences: KCRoutingPreferences = .default,
        ledger: KCCostLedger = KCCostLedger(),
        notifier: KCRoutingNotifier = KCRoutingNotifier(),
        loadPersistedPreferences: Bool = true
    ) {
        // Always ensure AppleLocal is present — MOD-11 guarantee.
        var map = providers
        if map[.appleLocal] == nil {
            map[.appleLocal] = AppleLocalProvider()
        }
        self.providers = map
        self.preferences = preferences
        self.ledger = ledger
        self.notifier = notifier

        // Production loads persisted prefs so user changes survive app relaunch.
        // Tests pass `loadPersistedPreferences: false` (or use a fresh
        // preferenceArgument) to avoid UserDefaults bleed-through across
        // test cases.
        if loadPersistedPreferences, let loaded = Self.loadPreferences() {
            self.preferences = loaded
        }

        // Persist on changes (debounced — write on next idle).
        // Using Combine would add a dep; we use a simple didSet observer.
        // ponytail: stored as JSON blob in UserDefaults.
    }

    // MARK: - Selection

    /// Pick a provider for a task. Applies the full MOD-02 / MOD-10 / MOD-11
    /// decision tree. Returns the provider and a `RoutingDecision` for
    /// audit / UI / cost recording.
    func selectProvider(for task: KCTask) async -> RoutingDecision {
        // 1. Privacy override — always wins (MOD-02).
        // Also applies when the prompt is itself privacy-marked
        // (task.requiresPrivacy) or global privacy mode is on.
        if preferences.privacyMode || task.requiresPrivacy || task.taskType == .privacySensitive {
            let provider = preferredLocalProvider(for: task)
            return RoutingDecision(
                provider: provider,
                taskType: task.taskType,
                selectedKind: provider.kind,
                preferredKind: preferences.preferredProviderPerTask[task.taskType.preferenceCategory] ?? provider.kind,
                reason: .privacyOverride,
                fellBack: false
            )
        }

        // 2. User preference for this task's category (MOD-10).
        let prefCategory = task.taskType.preferenceCategory
        if let preferredKind = preferences.preferredProviderPerTask[prefCategory] {
            if let candidate = providers[preferredKind] {
                let avail = await candidate.availability
                if avail.isAvailable {
                    return RoutingDecision(
                        provider: candidate,
                        taskType: task.taskType,
                        selectedKind: preferredKind,
                        preferredKind: preferredKind,
                        reason: .userPreference,
                        fellBack: false
                    )
                } else {
                    // Preferred is configured but unavailable (key missing,
                    // model not downloaded, etc.). Fall back + notify once.
                    let fallback = fallbackProvider(for: task, preferred: preferredKind, unavailableReason: avail)
                    let payloadReason = availabilityMessage(avail)
                    if fallback.kind != preferredKind {
                        _ = notifier.post(
                            preferred: preferredKind,
                            fallback: fallback.kind,
                            taskType: task.taskType,
                            reason: payloadReason
                        )
                    }
                    return RoutingDecision(
                        provider: fallback,
                        taskType: task.taskType,
                        selectedKind: fallback.kind,
                        preferredKind: preferredKind,
                        reason: .preferredUnavailable,
                        fellBack: fallback.kind != preferredKind
                    )
                }
            } else {
                // Preferred kind is set but no provider instance registered
                // (e.g. user picked OpenAI but Phase 166 hasn't run yet).
                // Fall back + notify.
                let fallback = fallbackProvider(for: task, preferred: preferredKind, unavailableReason: .unavailable(reason: "Provider not registered"))
                _ = notifier.post(
                    preferred: preferredKind,
                    fallback: fallback.kind,
                    taskType: task.taskType,
                    reason: "Provider not registered"
                )
                return RoutingDecision(
                    provider: fallback,
                    taskType: task.taskType,
                    selectedKind: fallback.kind,
                    preferredKind: preferredKind,
                    reason: .preferredUnavailable,
                    fellBack: true
                )
            }
        }

        // 3. Default routing per task type.
        return await selectDefault(for: task)
    }

    /// One-shot: classify a prompt → pick provider.
    func route(prompt: KCPrompt) async -> RoutingDecision {
        let task = KCTaskClassifier.classify(prompt)
        return await selectProvider(for: task)
    }

    /// Full pipeline: classify → format → route → stream.
    /// This is the primary entry point for user-facing model calls.
    /// Phase D: applies task-specific system prompts and prefixes before
    /// dispatching to the selected provider.
    func generate(from prompt: KCPrompt) async throws -> AsyncThrowingStream<KCToken, Error> {
        // 1. Classify intent
        let task = KCTaskClassifier.classify(prompt)

        // 2. Format prompt with task-specific system prompt + prefix + max tokens
        let formatted = KCTaskPromptFormatter.format(prompt, for: task)

        // 3. Select provider based on task type
        let decision = await selectProvider(for: task)

        // 4. Stream from the selected provider
        return try await decision.provider.stream(formatted)
    }

    // MARK: - Default routing

    /// Per-task-type default when no user preference is set. Implements the
    /// MOD-02 routing table.
    private func selectDefault(for task: KCTask) async -> RoutingDecision {
        switch task.taskType {
        case .privacySensitive:
            // Already covered by step 1, but defensive.
            let provider = preferredLocalProvider(for: task)
            return RoutingDecision(
                provider: provider,
                taskType: task.taskType,
                selectedKind: provider.kind,
                preferredKind: provider.kind,
                reason: .privacyOverride,
                fellBack: false
            )

        case .vision, .pcbRouting:
            // Vision priority: cloud vision-capable → MLX Gemma vision → AppleLocal.
            if let cloud = await firstAvailableCloudVisionProvider() {
                return RoutingDecision(
                    provider: cloud,
                    taskType: task.taskType,
                    selectedKind: cloud.kind,
                    preferredKind: cloud.kind,
                    reason: .defaultVision,
                    fellBack: false
                )
            }
            if let mlx = await firstAvailableMLXProvider() {
                // MLX with Gemma vision (the catalog lists Gemma 3 4B/12B).
                return RoutingDecision(
                    provider: mlx,
                    taskType: task.taskType,
                    selectedKind: mlx.kind,
                    preferredKind: mlx.kind,
                    reason: .defaultVisionLocal,
                    fellBack: false
                )
            }
            // AppleLocal has vision support in macOS 27+ (multimodal models).
            // Notify the user once — they asked for vision but got AppleLocal.
            _ = notifier.post(
                preferred: .mlxLocal, // ideal non-cloud vision target
                fallback: .appleLocal,
                taskType: task.taskType,
                reason: "No cloud vision provider or local MLX vision model available — using Apple Intelligence."
            )
            return RoutingDecision(
                provider: appleLocal,
                taskType: task.taskType,
                selectedKind: .appleLocal,
                preferredKind: .appleLocal,
                reason: .defaultVisionFallbackApple,
                fellBack: true
            )

        case .complexReasoning, .circuitGeneration,
             .circuitTheory, .spiceSimulation:
            // Phase D: theory + SPICE route same as codegen — prefer MLX local
            // with v5 adapter (cost $0, has task-specific training), then AppleLocal.
            if let mlx = await firstAvailableMLXProvider() {
                return RoutingDecision(
                    provider: mlx,
                    taskType: task.taskType,
                    selectedKind: mlx.kind,
                    preferredKind: mlx.kind,
                    reason: .defaultLocalMLX,
                    fellBack: false
                )
            }
            return RoutingDecision(
                provider: appleLocal,
                taskType: task.taskType,
                selectedKind: .appleLocal,
                preferredKind: .appleLocal,
                reason: .defaultAppleFallback,
                fellBack: false
            )

        case .quickReply, .boardAnalysis, .conversationHistory:
            // Free + fast — AppleLocal is ideal.
            return RoutingDecision(
                provider: appleLocal,
                taskType: task.taskType,
                selectedKind: .appleLocal,
                preferredKind: .appleLocal,
                reason: .defaultAppleLocal,
                fellBack: false
            )
        }
    }

    // MARK: - Fallback selection

    /// Choose a fallback provider when the user-preferred one is unavailable.
    /// Per MOD-11: FoundationModels is the universal fallback.
    private func fallbackProvider(for task: KCTask, preferred: KCProviderKind, unavailableReason: KCProviderAvailability) -> any KiCadModelProvider {
        // Vision tasks need a vision-capable fallback.
        if task.taskType == .vision || task.taskType == .pcbRouting || task.requiresVision {
            if let mlx = providers[.mlxLocal] { return mlx }
        }
        // Universal: AppleLocal. Always present after init guard.
        return appleLocal
    }

    /// Pick the "best" local provider for a privacy task. MLX first if a
    /// model is downloaded and the task is reasoning-heavy, else AppleLocal.
    private func preferredLocalProvider(for task: KCTask) -> any KiCadModelProvider {
        // Quick replies → AppleLocal (faster cold-start than MLX).
        if task.taskType == .privacySensitive && task.complexity < 0.5 {
            return appleLocal
        }
        // Reasoning-heavy → prefer MLX if available.
        if task.complexity >= 0.7, let mlx = providers[.mlxLocal] {
            // MLX availability check would need async; here we trust the map
            // and rely on stream() surfacing a real error if unavailable.
            return mlx
        }
        return appleLocal
    }

    // MARK: - Provider queries

    /// First cloud provider with vision capability that's currently available.
    /// Phase 166 BYOK registers cloud providers; for Phase 165 this returns
    /// nil until keys land, which is correct — falls back to MLX/Apple.
    private func firstAvailableCloudVisionProvider() async -> (any KiCadModelProvider)? {
        // Vision-capable cloud kinds (per STACK.md, all support image input):
        let visionCloudKinds: [KCProviderKind] = [.openAI, .anthropic, .gemini]
        for kind in visionCloudKinds {
            guard let provider = providers[kind] else { continue }
            let avail = await provider.availability
            if avail.isAvailable { return provider }
        }
        return nil
    }

    /// First MLX provider currently available. Phase 164 ships a single
    /// MLXLocalProvider per downloaded model; the registry adds them as
    /// models come and go.
    private func firstAvailableMLXProvider() async -> (any KiCadModelProvider)? {
        guard let provider = providers[.mlxLocal] else { return nil }
        let avail = await provider.availability
        return avail.isAvailable ? provider : nil
    }

    // MARK: - Helpers

    private func availabilityMessage(_ avail: KCProviderAvailability) -> String {
        switch avail {
        case .available: return "Available"
        case .unavailable(let reason): return reason
        case .requiresKey(let hint): return hint
        }
    }

    // MARK: - Persistence

    private static let prefsKey = "com.kicadagent.router.preferences.v1"

    private static func loadPreferences() -> KCRoutingPreferences? {
        guard let data = UserDefaults.standard.data(forKey: prefsKey) else { return nil }
        return try? JSONDecoder().decode(KCRoutingPreferences.self, from: data)
    }

    /// Persist current preferences. Called from Settings UI's save action
    /// (debounced on the main actor).
    func persistPreferences() {
        if let data = try? JSONEncoder().encode(preferences) {
            UserDefaults.standard.set(data, forKey: Self.prefsKey)
        }
    }

    /// Reset preferences to defaults. Settings "Reset to defaults" button.
    func resetPreferences() {
        preferences = .default
        persistPreferences()
    }

    // MARK: - Recording

    /// Record a completed call into the cost ledger. The chat engine calls
    /// this after each stream finishes, passing the `KCUsage` token.
    func record(usage: KCUsage, for decision: RoutingDecision) {
        ledger.record(
            usage: usage,
            providerKind: decision.selectedKind,
            taskType: decision.taskType
        )
    }
}

// MARK: - RoutingDecision

/// Result of a routing decision. Captures not just the chosen provider but
/// the reason + fallback flag — useful for chat UI badges ("used Apple
/// Intelligence because OpenAI key missing") and audit logging.
struct RoutingDecision: Sendable {
    let provider: any KiCadModelProvider
    let taskType: KCTaskType
    let selectedKind: KCProviderKind
    let preferredKind: KCProviderKind
    let reason: RoutingReason
    let fellBack: Bool

    var didFallBack: Bool { fellBack }
}

/// Why the router picked this provider. Surfaced in chat UI badges and
/// cost ledger entries for debugging.
enum RoutingReason: Sendable, Equatable {
    case privacyOverride
    case userPreference
    case preferredUnavailable
    case defaultVision
    case defaultVisionLocal
    case defaultVisionFallbackApple
    case defaultLocalMLX
    case defaultAppleFallback
    case defaultAppleLocal

    var userFacingDescription: String {
        switch self {
        case .privacyOverride: return "Privacy mode — local only"
        case .userPreference: return "Your preferred model"
        case .preferredUnavailable: return "Preferred unavailable — fell back"
        case .defaultVision: return "Cloud vision"
        case .defaultVisionLocal: return "Local vision (MLX)"
        case .defaultVisionFallbackApple: return "Apple Intelligence (no vision cloud)"
        case .defaultLocalMLX: return "Local MLX"
        case .defaultAppleFallback: return "Apple Intelligence (no cloud key)"
        case .defaultAppleLocal: return "Apple Intelligence (free, fast)"
        }
    }
}
