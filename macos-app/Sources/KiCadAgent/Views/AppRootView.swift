//
//  AppRootView.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//  Phase 163 — KiCad CLI Integration (onboarding gate)
//
//  Root container for the KiCad Agent app.
//
//  Composition:
//  - NavigationSplitView: sidebar (ProjectSidebar) + main (LiquidGlassShell)
//  - Recovery UI overlay when daemon state is `.failed` (APP-01 augmentation)
//  - New Project button (modelContainer-aware)
//  - KiCad onboarding sheet when status is not `.ready` (APP-04 augmentation)
//

import SwiftUI
import SwiftData
import OSLog

/// Root view of the KiCad Agent app shell.
struct AppRootView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(DaemonSupervisor.self) private var daemonSupervisor
    @Environment(KiCadCLIDetector.self) private var kicadDetector

    @Query(sort: \Project.lastModifiedAt, order: .reverse) private var projects: [Project]

    @State private var selectedProjectId: UUID?
    @State private var showErrorRecovery: Bool = false
    @State private var showKiCadOnboarding: Bool = false

    var body: some View {
        NavigationSplitView {
            ProjectSidebar(
                projects: projects,
                selectedProjectId: $selectedProjectId,
                onCreateProject: createProject,
                onDeleteProject: deleteProject
            )
            .navigationSplitViewColumnWidth(
                min: WindowLayout.sidebarMinWidth,
                ideal: WindowLayout.sidebarWidth,
                max: WindowLayout.sidebarMaxWidth
            )
        } detail: {
            if let selected = selectedProject {
                LiquidGlassShell(project: selected)
            } else {
                ChatPlaceholderView(onStartFirstDesign: createProject)
            }
        }
        .frame(minWidth: WindowLayout.minWidth, minHeight: WindowLayout.minHeight)
        .alert(
            "Daemon unavailable",
            isPresented: daemonFailedBinding,
            actions: {
                Button("Retry") {
                    daemonSupervisor.retry()
                }
                Button("Quit", role: .destructive) {
                    NSApplication.shared.terminate(nil)
                }
            },
            message: {
                Text(daemonSupervisor.state.failureMessage ?? "Unknown daemon error.")
            }
        )
        .sheet(isPresented: kiCadOnboardingBinding) {
            KiCadInstallView(
                detector: kicadDetector,
                onQuit: {
                    NSApplication.shared.terminate(nil)
                },
                onReady: {
                    showKiCadOnboarding = false
                }
            )
            .interactiveDismissDisabled(true) // User must resolve before proceeding.
        }
        .onChange(of: kicadDetector.status) { _, newStatus in
            // APP-04 augmentation: gate main workflow on `.ready`.
            // Show onboarding whenever status is NOT ready. Dismiss when ready.
            showKiCadOnboarding = !newStatus.isReady
            if newStatus.isReady {
                Logger.kicad.info("KiCad ready — main workflow unblocked")
            }
        }
        .onAppear {
            // Initial state — if detector hasn't run yet, assume worst case
            // until the first detect() lands.
            showKiCadOnboarding = !kicadDetector.status.isReady
        }
    }

    // MARK: - Derived state

    private var selectedProject: Project? {
        guard let id = selectedProjectId else { return projects.first }
        return projects.first { $0.id == id }
    }

    /// Binding that drives the recovery alert (APP-01 augmentation).
    private var daemonFailedBinding: Binding<Bool> {
        Binding(
            get: {
                if case .failed = daemonSupervisor.state { return true }
                return false
            },
            set: { newValue in
                if !newValue { showErrorRecovery = false }
            }
        )
    }

    /// Binding that drives the KiCad onboarding sheet (APP-04 augmentation).
    /// Disables default dismiss behavior — user must resolve before proceeding.
    private var kiCadOnboardingBinding: Binding<Bool> {
        Binding(
            get: { showKiCadOnboarding },
            set: { newValue in showKiCadOnboarding = newValue }
        )
    }

    // MARK: - Mutations

    private func createProject() {
        // APP-04: refuse to create a project if KiCad isn't ready.
        // The onboarding sheet is already visible; this just no-ops.
        guard kicadDetector.status.isReady else {
            Logger.ui.warning("createProject blocked — KiCad not ready")
            showKiCadOnboarding = true
            return
        }
        let project = Project.newDefault()
        modelContext.insert(project)
        selectedProjectId = project.id
        Logger.ui.info("Created project via sidebar — selecting id=\(project.id.uuidString.prefix(8))")
    }

    private func deleteProject(_ project: Project) {
        Logger.ui.info("Deleting project id=\(project.id.uuidString.prefix(8))")
        if selectedProjectId == project.id {
            selectedProjectId = projects.first(where: { $0.id != project.id })?.id
        }
        modelContext.delete(project)
    }
}

/// Convenience extension surfacing a human-readable failure message.
extension DaemonState {
    var failureMessage: String? {
        if case .failed(let reason) = self { return reason }
        return nil
    }
}

#if DEBUG
#Preview("App Root — Empty") {
    AppRootView()
        .environment(DaemonSupervisor())
        .environment(KiCadCLIDetector())
        .modelContainer(for: [Project.self, Conversation.self], inMemory: true)
}

#Preview("App Root — With Project") {
    let container = try! ModelContainer(
        for: Project.self, Conversation.self,
        configurations: ModelConfiguration(isStoredInMemoryOnly: true)
    )
    let ctx = container.mainContext
    let project = Project(name: "Distortion Pedal for Bass")
    ctx.insert(project)
    return AppRootView()
        .environment(DaemonSupervisor())
        .environment(KiCadCLIDetector())
        .modelContainer(container)
}
#endif
