//
//  AppRootViewSnapshotTests.swift
//  KiCadAgentTests
//
//  Phase 161 — App Shell Foundation
//
//  PLACEHOLDER — full snapshot infra lands in Phase 192 (Track H — Quality).
//
//  TEST-03 requires 4 variants per view (light/dark/XXXL/high-contrast).
//  That infra (swift-snapshot-testing + signature stability helpers) is
//  Phase 192's responsibility. This file asserts the views exist and
//  instantiate without crashing — a smoke test before the real suite lands.
//

import Testing
import SwiftUI
import SwiftData
@testable import KiCadAgent

@Suite("App Root View Smoke", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil), .serialized)
struct AppRootViewSnapshotTests {

    @MainActor
    @Test("AppRootView instantiates with empty store")
    func instantiatesEmpty() async throws {
        let container = try ModelContainer(
            for: Project.self, Conversation.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let view = AppRootView()
            .environment(DaemonSupervisor())
            .modelContainer(container)
        _ = view  // Smoke test: instantiates without crash.
        // Allow SwiftUI's @Query to settle before container dealloc runs.
        try await Task.sleep(for: .milliseconds(50))
    }

    @MainActor
    @Test("AppRootView instantiates with a project")
    func instantiatesWithProject() async throws {
        let container = try ModelContainer(
            for: Project.self, Conversation.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let ctx = container.mainContext
        let project = Project(name: "Test Project", projectDescription: "", createdAt: .now, lastModifiedAt: .now)
        ctx.insert(project)
        try ctx.save()
        let view = AppRootView()
            .environment(DaemonSupervisor())
            .modelContainer(container)
        _ = view
        // Allow SwiftUI's @Query to settle before container dealloc runs.
        try await Task.sleep(for: .milliseconds(50))
    }

    @MainActor
    @Test("ChatPlaceholderView instantiates")
    func placeholderInstantiates() {
        let view = ChatPlaceholderView(onStartFirstDesign: {})
        _ = view
    }

    // TODO(TEST-03-Phase192): Replace these smoke tests with full 4-variant
    // snapshot tests (light/dark/XXXL/high-contrast) once swift-snapshot-testing
    // is integrated in Phase 192. Tracked as DEFERRED-TO-NAMED-TARGET.
}
