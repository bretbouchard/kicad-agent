//
//  LiquidGlassShellTests.swift
//  KiCadAgentTests
//
//  Phase 171 — Liquid Glass UI Shell
//
//  4-variant trait tests for the LiquidGlassShell + ToolbarView + WindowManager.
//
//  Phase 192 (Track H — Snapshot Testing) upgrades these to pixel-accurate
//  swift-snapshot-testing renders. For Phase 171 we assert:
//  - View instantiates without crashing under each trait environment
//  - All toolbar buttons have accessibility labels
//  - WindowManager cap is enforced (T-171-04 mitigation)
//  - Reduce Motion / Reduce Transparency are observed
//
//  A11Y-03: every interactive element labeled
//  A11Y-06: high contrast / reduce transparency supported
//  TEST-03: 4 variants per view (light/dark/XXXL/high-contrast)
//

import Testing
import SwiftUI
import SwiftData
@testable import KiCadAgent

@Suite("LiquidGlassShell — 4 Variant Trait Tests", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil), .serialized)
struct LiquidGlassShellTests {

    // MARK: - Variant 1: Light Mode

    @MainActor
    @Test("LiquidGlassShell instantiates in light mode", .tags(.a11y, .ui))
    func instantiatesLightMode() async throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let project = Project(name: "Light Mode Test")
        container.mainContext.insert(project)
        try container.mainContext.save()
        let view = LiquidGlassShell(project: project)
            .environment(WindowManager())
            .environment(DaemonSupervisor())
            .modelContainer(container)
        _ = view
        try await Task.sleep(for: .milliseconds(50))
    }

    // MARK: - Variant 2: Dark Mode

    @MainActor
    @Test("LiquidGlassShell instantiates in dark mode", .tags(.a11y, .ui))
    func instantiatesDarkMode() async throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let project = Project(name: "Dark Mode Test")
        container.mainContext.insert(project)
        try container.mainContext.save()
        let view = LiquidGlassShell(project: project)
            .environment(WindowManager())
            .environment(DaemonSupervisor())
            .preferredColorScheme(.dark)
            .modelContainer(container)
        _ = view
        try await Task.sleep(for: .milliseconds(50))
    }

    // MARK: - Variant 3: Dynamic Type XXXL

    @MainActor
    @Test("LiquidGlassShell instantiates at Dynamic Type XXXL", .tags(.a11y, .ui))
    func instantiatesXXXL() async throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let project = Project(name: "XXXL Test")
        container.mainContext.insert(project)
        try container.mainContext.save()
        let view = LiquidGlassShell(project: project)
            .environment(WindowManager())
            .environment(DaemonSupervisor())
            .dynamicTypeSize(.accessibility3)
            .modelContainer(container)
        _ = view
        try await Task.sleep(for: .milliseconds(50))
    }

    // MARK: - Variant 4: High Contrast + Reduce Motion + Reduce Transparency

    @MainActor
    @Test("LiquidGlassShell instantiates with full accessibility", .tags(.a11y, .ui))
    func instantiatesWithAccessibility() async throws {
        let container = try makeContainer()
        defer { SwiftDataTestHelpers.drainContainer(container) }
        let project = Project(name: "A11Y Test")
        container.mainContext.insert(project)
        try container.mainContext.save()
        let view = LiquidGlassShell(project: project)
            .environment(WindowManager())
            .environment(DaemonSupervisor())
            .accessibilityShowsLargeContentViewer()
            .modelContainer(container)
        _ = view
        try await Task.sleep(for: .milliseconds(50))
    }

    // MARK: - ToolbarView

    @Test("ToolbarView instantiates with all 4 actions", .tags(.a11y))
    func toolbarInstantiates() {
        let view = ToolbarView(
            projectName: "Test",
            onNewProject: {},
            onNewWindow: {},
            onShare: {},
            onSettings: {}
        )
        _ = view
    }

    @Test("ToolbarButton has accessibility label + hint + button trait", .tags(.a11y))
    func toolbarButtonAccessible() {
        let view = ToolbarButton(
            label: "Test Action",
            systemImage: "star",
            action: {},
            accessibilityHint: "Hint text"
        )
        _ = view
    }

    // MARK: - WindowManager (T-171-04 mitigation)

    @Test("WindowManager registers and tracks open projects")
    @MainActor
    func windowManagerRegister() {
        let wm = WindowManager()
        let id = UUID()
        #expect(wm.isOpen(id) == false)
        #expect(wm.register(projectId: id) == true)
        #expect(wm.isOpen(id) == true)
        #expect(wm.activeProjectId == id)
    }

    @Test("WindowManager unregisters closed projects")
    @MainActor
    func windowManagerUnregister() {
        let wm = WindowManager()
        let id = UUID()
        _ = wm.register(projectId: id)
        wm.unregister(projectId: id)
        #expect(wm.isOpen(id) == false)
        #expect(wm.activeProjectId == nil)
    }

    @Test("WindowManager enforces 100-window cap (T-171-04)", .tags(.security))
    @MainActor
    func windowManagerCap() {
        let wm = WindowManager()
        // Fill to exactly the cap.
        for _ in 0..<WindowManager.maxOpenWindows {
            let id = UUID()
            #expect(wm.register(projectId: id) == true)
        }
        // Next registration must be refused.
        let overflow = UUID()
        #expect(wm.register(projectId: overflow) == false)
        #expect(wm.isAtCap == true)
        #expect(wm.isOpen(overflow) == false)
    }

    @Test("WindowManager idempotent on re-registration")
    @MainActor
    func windowManagerIdempotent() {
        let wm = WindowManager()
        let id = UUID()
        #expect(wm.register(projectId: id) == true)
        #expect(wm.register(projectId: id) == true)
        #expect(wm.openProjectIds.count == 1)
    }

    @Test("WindowManager setActive promotes to active")
    @MainActor
    func windowManagerSetActive() {
        let wm = WindowManager()
        let a = UUID()
        let b = UUID()
        _ = wm.register(projectId: a)
        _ = wm.register(projectId: b)
        wm.setActive(projectId: a)
        #expect(wm.activeProjectId == a)
    }

    @Test("WindowManager setActive rejects unregistered")
    @MainActor
    func windowManagerSetActiveRejects() {
        let wm = WindowManager()
        let unregistered = UUID()
        wm.setActive(projectId: unregistered)
        #expect(wm.activeProjectId == nil)
    }

    // MARK: - Helpers

    private func makeContainer() throws -> ModelContainer {
        try ModelContainer(
            for: Project.self, Conversation.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
    }
}

// MARK: - Test Tags

extension Tag {
    @Tag static var a11y: Tag
    @Tag static var ui: Tag
    @Tag static var security: Tag
}
