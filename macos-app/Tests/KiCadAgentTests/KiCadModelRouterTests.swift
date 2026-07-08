//
//  KiCadModelRouterTests.swift
//  KiCadAgentTests
//
//  Phase 165 — Provider Router
//
//  Tests for KiCadModelRouter routing rules:
//    - MOD-02: privacy mode → always AppleLocal
//    - MOD-02: vision → cloud with vision capability OR MLX
//    - MOD-02: complex reasoning → user's preferred (or AppleLocal fallback)
//    - MOD-02: quick reply → AppleLocal
//    - MOD-02 augmentation: unavailable preferred → AppleLocal fallback + one-time notification
//    - MOD-10: user preference per task type is respected when available
//    - MOD-11: falls back to AppleLocal when no cloud keys configured
//    - MOD-12: cost ledger records every routing decision
//
//  All tests use MockProvider so no real network or framework calls run.
//

import Testing
import Foundation
@testable import KiCadAgent

@MainActor
@Suite("KiCadModelRouter")
struct KiCadModelRouterTests {

    // MARK: - Privacy routing (MOD-02)

    @Test("privacySensitive task always routes to AppleLocal even with cloud available")
    func privacySensitiveAlwaysAppleLocal() async {
        let cloud = MockProvider(
            displayName: "OpenAI",
            availability: .available,
            tokens: [.text("ok"), .done(.complete)]
        )
        cloud.overrideKind(.openAI)
        let router = KiCadModelRouter(
            providers: [
                .appleLocal: makeAppleMock(),
                .openAI: cloud
            ]
        )

        let task = KCTask(taskType: .privacySensitive, requiresPrivacy: true)
        let decision = await router.selectProvider(for: task)

        #expect(decision.selectedKind == .appleLocal)
        #expect(decision.reason == .privacyOverride)
        #expect(!decision.didFallBack) // privacy override is not a "fallback"
    }

    @Test("Privacy mode toggle forces every task to a local provider")
    func privacyModeToggleForcesLocal() async {
        let cloud = MockProvider(displayName: "Anthropic", availability: .available)
        cloud.overrideKind(.anthropic)
        let router = KiCadModelRouter(
            providers: [
                .appleLocal: makeAppleMock(),
                .anthropic: cloud
            ],
            preferences: KCRoutingPreferences(
                preferredProviderPerTask: [.complexReasoning: .anthropic],
                privacyMode: true,
                costWarningThresholdUSD: 1000
            ),
            loadPersistedPreferences: false
        )

        let task = KCTask(taskType: .complexReasoning)
        let decision = await router.selectProvider(for: task)

        #expect(decision.selectedKind == .appleLocal)
        #expect(decision.reason == .privacyOverride)
    }

    // MARK: - Vision routing (MOD-02)

    @Test("vision task with cloud vision available routes to cloud")
    func visionRoutesToCloudWhenAvailable() async {
        let gemini = MockProvider(displayName: "Gemini", availability: .available)
        gemini.overrideKind(.gemini)
        let router = KiCadModelRouter(providers: [
            .appleLocal: makeAppleMock(),
            .gemini: gemini
        ])

        let task = KCTask(taskType: .vision, requiresVision: true)
        let decision = await router.selectProvider(for: task)

        #expect(decision.selectedKind == .gemini)
        #expect(decision.reason == .defaultVision)
    }

    @Test("vision task with no cloud vision falls back to MLX")
    func visionFallsBackToMLXWhenNoCloud() async {
        let mlx = MockProvider(displayName: "MLX Gemma", availability: .available)
        mlx.overrideKind(.mlxLocal)
        let router = KiCadModelRouter(providers: [
            .appleLocal: makeAppleMock(),
            .mlxLocal: mlx
        ])

        let task = KCTask(taskType: .vision, requiresVision: true)
        let decision = await router.selectProvider(for: task)

        #expect(decision.selectedKind == .mlxLocal)
        #expect(decision.reason == .defaultVisionLocal)
    }

    @Test("vision task with no cloud and no MLX falls back to AppleLocal with notification")
    func visionFallsBackToAppleLocalWithNotification() async {
        let center = NotificationCenter()
        let notifier = KCRoutingNotifier(center: center)
        let router = KiCadModelRouter(
            providers: [.appleLocal: makeAppleMock()],
            notifier: notifier
        )

        // ponytail: thread-safe capture box. NotificationCenter dispatches
        // observers on its own queue; bare var capture is a Swift 6
        // Sendable violation.
        let box = PayloadBox()
        let observer = center.addObserver(forName: .kcProviderFallbackOccurred, object: nil, queue: nil) { note in
            if let payload = note.userInfo?["payload"] as? KCRoutingNotificationPayload {
                box.set(payload)
            }
        }
        defer { center.removeObserver(observer) }

        let task = KCTask(taskType: .vision, requiresVision: true)
        let decision = await router.selectProvider(for: task)

        #expect(decision.selectedKind == .appleLocal)
        #expect(decision.didFallBack)
        let receivedPayload = box.value()
        #expect(receivedPayload?.fallbackKind == .appleLocal)
        #expect(receivedPayload?.taskType == .vision)
    }

    // MARK: - Complex reasoning routing (MOD-02, MOD-11)

    @Test("complexReasoning with no providers configured falls back to AppleLocal (MOD-11)")
    func complexReasoningNoCloudFallsBackToApple() async {
        let router = KiCadModelRouter(providers: [.appleLocal: makeAppleMock()])

        let task = KCTask(taskType: .complexReasoning)
        let decision = await router.selectProvider(for: task)

        // No MLX, no cloud → AppleLocal per MOD-11.
        #expect(decision.selectedKind == .appleLocal)
        #expect(decision.reason == .defaultAppleFallback)
    }

    @Test("complexReasoning with MLX available routes to MLX (cost $0)")
    func complexReasoningPrefersMLXWhenAvailable() async {
        let mlx = MockProvider(displayName: "MLX Qwen", availability: .available)
        mlx.overrideKind(.mlxLocal)
        let router = KiCadModelRouter(providers: [
            .appleLocal: makeAppleMock(),
            .mlxLocal: mlx
        ])

        let task = KCTask(taskType: .complexReasoning)
        let decision = await router.selectProvider(for: task)

        #expect(decision.selectedKind == .mlxLocal)
        #expect(decision.reason == .defaultLocalMLX)
    }

    // MARK: - Quick reply routing (MOD-02)

    @Test("quickReply routes to AppleLocal")
    func quickReplyRoutesToApple() async {
        let router = KiCadModelRouter(providers: [.appleLocal: makeAppleMock()])

        let task = KCTask(taskType: .quickReply)
        let decision = await router.selectProvider(for: task)

        #expect(decision.selectedKind == .appleLocal)
        #expect(decision.reason == .defaultAppleLocal)
    }

    @Test("boardAnalysis routes to AppleLocal")
    func boardAnalysisRoutesToApple() async {
        let router = KiCadModelRouter(providers: [.appleLocal: makeAppleMock()])

        let task = KCTask(taskType: .boardAnalysis)
        let decision = await router.selectProvider(for: task)

        #expect(decision.selectedKind == .appleLocal)
        #expect(decision.reason == .defaultAppleLocal)
    }

    // MARK: - User preference (MOD-10)

    @Test("MOD-10: user preference for complex reasoning respected when available")
    func userPreferenceRespectedWhenAvailable() async {
        let openai = MockProvider(displayName: "OpenAI", availability: .available)
        openai.overrideKind(.openAI)
        let router = KiCadModelRouter(
            providers: [
                .appleLocal: makeAppleMock(),
                .openAI: openai
            ],
            preferences: KCRoutingPreferences(
                preferredProviderPerTask: [.complexReasoning: .openAI],
                privacyMode: false,
                costWarningThresholdUSD: 1000
            ),
            loadPersistedPreferences: false
        )

        let task = KCTask(taskType: .complexReasoning)
        let decision = await router.selectProvider(for: task)

        #expect(decision.selectedKind == .openAI)
        #expect(decision.preferredKind == .openAI)
        #expect(decision.reason == .userPreference)
        #expect(!decision.didFallBack)
    }

    @Test("MOD-10 augmentation: unavailable preferred falls back + fires notification once")
    func unavailablePreferredFiresNotificationOnce() async {
        // OpenAI registered but unavailable (no key).
        let openaiUnavailable = MockProvider(
            displayName: "OpenAI",
            availability: .requiresKey(providerHint: "Add OpenAI key")
        )
        openaiUnavailable.overrideKind(.openAI)
        let center = NotificationCenter()
        let notifier = KCRoutingNotifier(center: center)

        let router = KiCadModelRouter(
            providers: [
                .appleLocal: makeAppleMock(),
                .openAI: openaiUnavailable
            ],
            preferences: KCRoutingPreferences(
                preferredProviderPerTask: [.complexReasoning: .openAI],
                privacyMode: false,
                costWarningThresholdUSD: 1000
            ),
            notifier: notifier,
            loadPersistedPreferences: false
        )

        // ponytail: thread-safe capture for cross-queue notification observer.
        let box = PayloadList()
        let observer = center.addObserver(forName: .kcProviderFallbackOccurred, object: nil, queue: nil) { note in
            if let p = note.userInfo?["payload"] as? KCRoutingNotificationPayload {
                box.append(p)
            }
        }
        defer { center.removeObserver(observer) }

        let task = KCTask(taskType: .complexReasoning)

        // First call: should fire notification.
        let d1 = await router.selectProvider(for: task)
        #expect(d1.selectedKind == .appleLocal)
        #expect(d1.preferredKind == .openAI)
        #expect(d1.didFallBack)

        // Second call: should NOT fire (deduped).
        _ = await router.selectProvider(for: task)

        let captured = box.snapshot()
        #expect(captured.count == 1)
        #expect(captured.first?.preferredKind == .openAI)
        #expect(captured.first?.fallbackKind == .appleLocal)
    }

    // MARK: - MOD-11 fallback

    @Test("MOD-11: no cloud providers configured → router still serves (AppleLocal)")
    func noCloudKeysFallsBackToApple() async {
        let router = KiCadModelRouter(providers: [.appleLocal: makeAppleMock()])
        let task = KCTask(taskType: .quickReply)
        let decision = await router.selectProvider(for: task)
        #expect(decision.selectedKind == .appleLocal)
    }

    // MARK: - MOD-12 cost recording

    @Test("MOD-12: record(usage:) appends to ledger")
    func recordAppendsToLedger() async {
        let router = KiCadModelRouter(providers: [.appleLocal: makeAppleMock()])
        let decision = await router.selectProvider(for: KCTask(taskType: .quickReply))

        let usage = KCUsage(inputTokens: 100, outputTokens: 50, estimatedCostUSD: 0)
        router.record(usage: usage, for: decision)

        #expect(router.ledger.entries.count == 1)
        let entry = router.ledger.entries[0]
        #expect(entry.providerKind == .appleLocal)
        #expect(entry.taskType == .quickReply)
        #expect(entry.inputTokens == 100)
        #expect(entry.outputTokens == 50)
    }

    // MARK: - one-shot route(prompt:)

    @Test("route(prompt:) classifies and routes in one call")
    func routeClassifiesAndRoutes() async {
        let router = KiCadModelRouter(providers: [.appleLocal: makeAppleMock()])

        // Privacy marker → privacySensitive → AppleLocal override.
        let prompt = KCPrompt.user("Generate a circuit. [confidential]")
        let decision = await router.route(prompt: prompt)
        #expect(decision.selectedKind == .appleLocal)
        #expect(decision.taskType == .privacySensitive || decision.taskType == .circuitGeneration)
    }

    // MARK: - Preferences persistence

    @Test("resetPreferences returns to defaults")
    func resetPreferencesRestoresDefaults() {
        let router = KiCadModelRouter(
            providers: [.appleLocal: makeAppleMock()],
            preferences: KCRoutingPreferences(
                preferredProviderPerTask: [.vision: .openAI],
                privacyMode: true,
                costWarningThresholdUSD: 50
            ),
            loadPersistedPreferences: false
        )

        router.resetPreferences()

        #expect(router.preferences.privacyMode == false)
        #expect(router.preferences.preferredProviderPerTask.isEmpty)
        #expect(router.preferences.costWarningThresholdUSD == KCCostLedger.defaultPerMessageWarningThreshold)
    }

    @Test("setPreference persists for a task type")
    func setPreferenceUpdatesPreferences() {
        let router = KiCadModelRouter(providers: [.appleLocal: makeAppleMock()])
        router.preferences.preferredProviderPerTask[.vision] = .gemini

        #expect(router.preferences.preferredProviderPerTask[.vision] == .gemini)
    }

    // MARK: - Helpers

    /// Build a mock provider tagged as AppleLocal. The real AppleLocalProvider
    /// requires macOS 27 + FoundationModels at runtime; tests use a mock with
    /// `.available` so routing logic can be exercised in any environment.
    private func makeAppleMock() -> MockProvider {
        let mock = MockProvider(
            displayName: "Apple Intelligence",
            availability: .available,
            tokens: [.text("hi"), .done(.complete)]
        )
        mock.overrideKind(.appleLocal)
        return mock
    }
}

// MARK: - MockProvider test helper

/// Test-only convenience so router tests read naturally.
extension MockProvider {
    /// Mutate kind in place. MockProvider.kind is a `var` (see Phase 165
    /// change) so tests can impersonate any provider kind for routing
    /// decisions. Production code never calls this — providers are tagged
    /// at construction.
    func overrideKind(_ newKind: KCProviderKind) {
        self.kind = newKind
    }
}

// MARK: - Thread-safe test capture boxes

/// ponytail: NSLock-based single-payload capture. Swift 6 forbids mutating
/// captured vars across actor/queue boundaries from sync contexts, and actor
/// isolation makes the notification observer deadlock. NSLock gives us
/// thread-safe sync mutation from any context.
final class PayloadBox: @unchecked Sendable {
    private var stored: KCRoutingNotificationPayload?
    private let lock = NSLock()
    func set(_ payload: KCRoutingNotificationPayload) {
        lock.lock(); defer { lock.unlock() }
        stored = payload
    }
    func value() -> KCRoutingNotificationPayload? {
        lock.lock(); defer { lock.unlock() }
        return stored
    }
}

/// Thread-safe multi-payload capture.
final class PayloadList: @unchecked Sendable {
    private(set) var items: [KCRoutingNotificationPayload] = []
    private let lock = NSLock()
    func append(_ payload: KCRoutingNotificationPayload) {
        lock.lock(); defer { lock.unlock() }
        items.append(payload)
    }
    func snapshot() -> [KCRoutingNotificationPayload] {
        lock.lock(); defer { lock.unlock() }
        return items
    }
}
