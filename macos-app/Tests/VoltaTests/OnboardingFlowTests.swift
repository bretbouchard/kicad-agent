//
//  OnboardingFlowTests.swift
//  VoltaTests
//
//  Phase 242 — First-run Onboarding
//
//  Tests the persisted state round-trip and the starter catalog.
//  Does NOT exercise the SwiftUI view directly (the @View body
//  requires a fully wired SwiftData environment + WindowManager).
//  View-level wiring is covered by the AppRootView compile and
//  the manual end-to-end test.
//

import Testing
import Foundation
import SwiftData
@testable import Volta

@Suite("Onboarding (Phase 242)")
struct OnboardingFlowTests {

    // MARK: - SwiftData round-trip

    @Test("OnboardingState: round-trips through SwiftData (default state on first launch)")
    @MainActor
    func stateDefault() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        let state = OnboardingStateStore.current(in: ctx)
        #expect(state.dismissed == false, "First launch should not be dismissed")
        #expect(state.completed == false, "First launch should not be completed")
        #expect(state.currentStep == 0)
        #expect(state.lastShownAt == nil)
    }

    @Test("OnboardingState: re-fetching returns the same canonical row, not a duplicate")
    @MainActor
    func stateSingleRow() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        let first = OnboardingStateStore.current(in: ctx)
        first.dismissed = true
        try ctx.save()
        let second = OnboardingStateStore.current(in: ctx)
        #expect(second.dismissed == true, "Re-fetch should see the same row's mutations")
        // Count all rows in the container.
        let count = try ctx.fetchCount(FetchDescriptor<OnboardingState>())
        #expect(count == 1, "Should be exactly one OnboardingState row")
    }

    @Test("OnboardingState: canonical id is stable across runs")
    func canonicalIdIsStable() {
        // The canonical UUID is hard-coded so a fresh install doesn't
        // create multiple rows over time. If you change this, you
        // break fetch-or-create semantics.
        #expect(OnboardingState.canonicalId == UUID(uuidString: "00000000-0000-0000-0000-00000000F100")!)
    }

    // MARK: - Starters

    @Test("OnboardingStarter: catalog has exactly 3 starters")
    func startersCount() {
        #expect(OnboardingStarter.all.count == 3)
    }

    @Test("OnboardingStarter: each starter has a non-empty prompt")
    func startersHavePrompts() {
        for starter in OnboardingStarter.all {
            #expect(!starter.name.isEmpty)
            #expect(!starter.blurb.isEmpty)
            #expect(!starter.prompt.isEmpty)
            // Prompts must be terse enough for the chat compose bar
            // preview to show the whole thing.
            #expect(starter.prompt.count <= 200, "Prompt too long for \(starter.id): \(starter.prompt.count) chars")
        }
    }

    @Test("OnboardingStarter: ids are unique")
    func startersUniqueIds() {
        let ids = OnboardingStarter.all.map(\.id)
        #expect(Set(ids).count == ids.count)
    }

    // MARK: - Skip / complete semantics

    @Test("OnboardingState: skip sets dismissed but not completed")
    @MainActor
    func skipSemantics() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        let state = OnboardingStateStore.current(in: ctx)
        state.dismissed = true
        try ctx.save()
        let reloaded = OnboardingStateStore.current(in: ctx)
        #expect(reloaded.dismissed == true)
        #expect(reloaded.completed == false)
    }

    @Test("OnboardingState: complete sets both flags")
    @MainActor
    func completeSemantics() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        let state = OnboardingStateStore.current(in: ctx)
        state.dismissed = true
        state.completed = true
        state.lastShownAt = .now
        try ctx.save()
        let reloaded = OnboardingStateStore.current(in: ctx)
        #expect(reloaded.dismissed == true)
        #expect(reloaded.completed == true)
        #expect(reloaded.lastShownAt != nil)
    }

    // MARK: - Helpers

    @MainActor
    private func makeContainer() throws -> ModelContainer {
        try ModelContainer(
            for: OnboardingState.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
    }
}
