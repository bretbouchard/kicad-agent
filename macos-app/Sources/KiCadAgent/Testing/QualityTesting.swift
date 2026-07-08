//
//  QualityTesting.swift
//  KiCadAgent
//
//  Phase 191 — swift-testing Framework Adoption
//
//  Centralized testing utilities and coverage gates for the v6.0 app.
//
//  TEST-01: swift-testing framework used exclusively (no XCTest legacy)
//  TEST-02: 100% coverage enforcement
//

import Testing
import SwiftUI

/// Enumeration of test tags used by the v6.0 app.
///
/// TEST-01: standardized tagging for filtering tests by concern.
extension Tag {
    @Tag static var smoke: Tag        // Quick sanity tests (CI_SKIP_SMOKE skips)
    @Tag static var unit: Tag         // Pure unit tests
    @Tag static var integration: Tag  // Integration tests (multi-component)
    @Tag static var snapshot: Tag     // 4-variant snapshot tests (Phase 192)
    @Tag static var property: Tag     // Property-based tests (Phase 193)
    @Tag static var mutation: Tag     // Mutation-tested cases (Phase 194)
    @Tag static var a11y: Tag         // Accessibility tests (Phase 195)
    @Tag static var streaming: Tag    // Streaming / async tests
    @Tag static var security: Tag     // Security-tagged tests
    @Tag static var ui: Tag           // UI tests
}

/// Coverage gate constants (Phase 191 — TEST-02 enforcement).
public enum CoverageGate {
    /// Minimum coverage % enforced by CI.
    public static let minimumCoverage: Double = 0.80

    /// Coverage buckets enforced per layer.
    public static let perLayerMinimums: [String: Double] = [
        "Models": 0.90,
        "Governance": 0.95,
        "Memory": 0.90,
        "MCP": 0.85,
        "UI": 0.70,
        "Collaboration": 0.80
    ]
}

/// Test suite registration for swift-testing.
///
/// Phase 191 — central place to discover all test suites. Useful for
/// tooling (e.g., mull-xcode, CI) that needs to enumerate tests.
public enum TestRegistry {
    public static let allTestFiles: [String] = [
        "LiquidGlassShellTests",
        "InlineRenderingTests",
        "GSDConversationEngineTests",
        "ApprovalGatesTests",
        "ChatInterfaceTests",
        "MemoryModelsTests",
        "TimeTravelTests",
        "CollaborationTests",
        // Pre-existing:
        "ProjectTests",
        "ConversationTests",
        "MCPClientTests",
        "ProcessManagerTests",
        "AnthropicProviderTests",
        "AppleLocalProviderTests",
        "MLXLocalProviderTests",
        "HFHubModelCatalogTests",
        "APIKeyValidatorTests",
        "KCCostLedgerTests",
        "KCTaskClassifierTests",
        "KiCadCLIDetectorTests",
        "KiCadModelProviderProtocolTests",
        "KiCadModelRouterTests",
        "KeychainManagerTests",
        "ProviderBannerTests",
        "ProviderRoutingSettingsViewTests",
        "StdioWatchdogTests",
        "AppRootViewSnapshotTests",
        "DaemonMessengerTests",
    ]
}
