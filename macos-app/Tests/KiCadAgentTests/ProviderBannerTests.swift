//
//  ProviderBannerTests.swift
//  KiCadAgentTests
//
//  Phase 164 — LLM Provider Protocol (Task 6 verification)
//
//  Tests for ProviderBanner state mapping per MOD-06 augmentation.
//

import Testing
import Foundation
import SwiftUI
@testable import KiCadAgent

@Suite("ProviderBanner")
struct ProviderBannerTests {

    // MARK: - BannerState

    @Test(".hidden shouldShow is false")
    func hiddenDoesntShow() {
        #expect(!ProviderBanner.BannerState.hidden.shouldShow)
    }

    @Test(".localOnlyMode has correct message")
    func localOnlyMessage() {
        let state = ProviderBanner.BannerState.localOnlyMode(
            providerName: "MLX: gemma3",
            appleIntelligenceReason: "not enabled"
        )
        #expect(state.shouldShow)
        #expect(state.title == "Local-only mode")
        #expect(state.message.contains("MLX: gemma3"))
        #expect(state.message.contains("not enabled"))
        #expect(state.message.contains("API key"))
    }

    @Test(".noProvidersAvailable has destructive accent")
    func noProvidersStyling() {
        let state = ProviderBanner.BannerState.noProvidersAvailable
        #expect(state.shouldShow)
        #expect(state.title == "No AI providers available")
        #expect(state.accentColor == ColorTokens.destructive)
    }

    @Test("BannerState equatable")
    func equatable() {
        let a: ProviderBanner.BannerState = .hidden
        let b: ProviderBanner.BannerState = .hidden
        #expect(a == b)

        let c = ProviderBanner.BannerState.localOnlyMode(providerName: "p", appleIntelligenceReason: "r")
        let d = ProviderBanner.BannerState.localOnlyMode(providerName: "p", appleIntelligenceReason: "r")
        #expect(c == d)

        let e = ProviderBanner.BannerState.localOnlyMode(providerName: "p1", appleIntelligenceReason: "r")
        #expect(c != e)
    }
}
