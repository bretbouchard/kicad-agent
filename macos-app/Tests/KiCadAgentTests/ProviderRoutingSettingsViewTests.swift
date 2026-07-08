//
//  ProviderRoutingSettingsViewTests.swift
//  KiCadAgentTests
//
//  Phase 165 — Provider Router
//
//  Tests for ProviderRoutingSettingsView. Per TEST-03 (Phase 161 deferral),
//  full 4-variant snapshot testing lands in Phase 192 (Track H — Quality).
//  This file ships smoke tests + structural assertions.
//

import Testing
import SwiftUI
@testable import KiCadAgent

@MainActor
@Suite("ProviderRoutingSettingsView")
struct ProviderRoutingSettingsViewTests {

    // MARK: - Instantiation

    @Test("View instantiates with default router (no entries)")
    func instantiatesEmpty() {
        let router = KiCadModelRouter(providers: [.appleLocal: AppleLocalProvider()])
        let view = ProviderRoutingSettingsView(router: router)
        _ = view
    }

    @Test("View instantiates with populated ledger")
    func instantiatesWithEntries() {
        let ledger = KCCostLedger()
        ledger.append(KCCostEntry(providerKind: .openAI, taskType: .vision, inputTokens: 2400, outputTokens: 600, costUSD: 0.108))
        ledger.append(KCCostEntry(providerKind: .appleLocal, taskType: .quickReply, inputTokens: 120, outputTokens: 40, costUSD: 0))
        let router = KiCadModelRouter(
            providers: [.appleLocal: AppleLocalProvider()],
            ledger: ledger
        )
        let view = ProviderRoutingSettingsView(router: router)
        _ = view
    }

    // MARK: - Preferences mutation

    @Test("Toggling privacy mode persists to router.preferences")
    func privacyModeMutation() {
        let router = KiCadModelRouter(providers: [.appleLocal: AppleLocalProvider()])
        let _ = ProviderRoutingSettingsView(router: router)

        // Mutate directly as the Settings UI would via binding.
        router.preferences.privacyMode = true
        #expect(router.preferences.privacyMode)
    }

    @Test("Per-task preference setter mutates preferences")
    func perTaskPreferenceMutation() {
        let router = KiCadModelRouter(providers: [.appleLocal: AppleLocalProvider()])
        router.preferences.preferredProviderPerTask[.vision] = .openAI

        #expect(router.preferences.preferredProviderPerTask[.vision] == .openAI)
    }

    @Test("Reset preferences clears all customization")
    func resetPreferences() {
        let router = KiCadModelRouter(
            providers: [.appleLocal: AppleLocalProvider()],
            preferences: KCRoutingPreferences(
                preferredProviderPerTask: [.complexReasoning: .openAI],
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

    // MARK: - Ledger reflects in summary accessors

    @Test("Ledger summary accessors return data after append")
    func ledgerSummaryReflectsAppend() {
        let ledger = KCCostLedger()
        let router = KiCadModelRouter(
            providers: [.appleLocal: AppleLocalProvider()],
            ledger: ledger
        )

        // Before.
        #expect(router.ledger.allTime.callCount == 0)

        // After.
        ledger.record(providerKind: .openAI, taskType: .vision, inputTokens: 100, outputTokens: 50, costUSD: 0.05)
        #expect(router.ledger.allTime.callCount == 1)
        #expect(router.ledger.allTime.totalCostUSD == 0.05)
    }

    // MARK: - Routing notifier integration

    @Test("Router carries a notifier usable from Settings context")
    func routerCarriesNotifier() {
        let router = KiCadModelRouter(providers: [.appleLocal: AppleLocalProvider()])
        // Notifier starts with zero announcements.
        #expect(router.notifier.announcedSwapCount == 0)
    }

    // TODO(TEST-03-Phase192): Replace these smoke tests with full 4-variant
    // snapshot tests (light/dark/XXXL/high-contrast) once swift-snapshot-testing
    // is integrated in Phase 192. Tracked as DEFERRED-TO-NAMED-TARGET.
}
