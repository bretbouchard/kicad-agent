//
//  AppRootView.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//  Phase 242 — First-run Onboarding
//
//  Root container for the KiCad Agent app.
//
//  Composition:
//  - NavigationSplitView: sidebar (ProjectSidebar) + main (LiquidGlassShell)
//  - OnboardingFlowView as the detail when no projects exist and the
//    user hasn't dismissed/completed the tour (Phase 242, F3).
//  - Recovery UI overlay when daemon state is `.failed` (APP-01 augmentation)
//  - New Project button (modelContainer-aware)
//
//  Note: KiCad is no longer a hard requirement (Phase 220+). The app runs
//  entirely on the local MLX model for chat/inference and only invokes
//  external KiCad CLI for optional ERC/DRC/validation. The KiCad install
//  onboarding was removed in Phase 220; the welcome tour replaced it in
//  Phase 242.
//

import SwiftUI
import SwiftData
import OSLog

/// Root view of the KiCad Agent app shell.
struct AppRootView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(DaemonSupervisor.self) private var daemonSupervisor

    @Query(sort: \Project.lastModifiedAt, order: .reverse) private var projects: [Project]
    @Query private var onboardingStates: [OnboardingState]

    @State private var selectedProjectId: UUID?
    @State private var showErrorRecovery: Bool = false
    @State private var onboardingCompletedInSession: Bool = false

    var body: some View {
        NavigationSplitView {
            ProjectSidebar(
                projects: projects,
                selectedProjectId: $selectedProjectId,
                onCreateProject: createProject,
                onDeleteProject: deleteProject,
                onShowTour: showTour
            )
            .navigationSplitViewColumnWidth(
                min: WindowLayout.sidebarMinWidth,
                ideal: WindowLayout.sidebarWidth,
                max: WindowLayout.sidebarMaxWidth
            )
        } detail: {
            detailContent
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
    }

    // MARK: - Detail content

    @ViewBuilder
    private var detailContent: some View {
        if let selected = selectedProject {
            LiquidGlassShell(project: selected)
        } else if shouldShowOnboarding {
            OnboardingFlowView(
                onPickStarter: pickStarter,
                onComplete: completeOnboarding,
                onSkip: skipOnboarding
            )
        } else {
            ChatPlaceholderView(
                onStartFirstDesign: createProject,
                onShowTour: showTour
            )
        }
    }

    // MARK: - Derived state

    private var selectedProject: Project? {
        guard let id = selectedProjectId else { return projects.first }
        return projects.first { $0.id == id }
    }

    /// Onboarding shows when:
    /// 1. No projects exist (first launch / fully cleared workspace), AND
    /// 2. The state row exists (the @Query fires before we lazily create
    ///    it on first show), AND
    /// 3. The user hasn't dismissed or completed it in a prior session.
    /// 4. The user hasn't already finished it in this session (avoids
    ///    re-flashing if they immediately create another project).
    private var shouldShowOnboarding: Bool {
        guard projects.isEmpty, !onboardingCompletedInSession else { return false }
        guard let state = onboardingStates.first else { return true }
        return !state.dismissed && !state.completed
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

    // MARK: - Mutations

    private func createProject() {
        // Phase 220+: KiCad is no longer required. Project creation runs
        // on the local MLX engine only; KiCad CLI is only used for optional
        // ERC/DRC/validation when present.
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

    // MARK: - Onboarding

    /// Step 1 "Continue" callback. Creates a project named after the
    /// starter and switches to it. The chat compose bar's pre-fill is
    /// delivered via NotificationCenter because ChatView's `inputDraft`
    /// is private to that view (per Phase 175 encapsulation).
    private func pickStarter(_ starter: OnboardingStarter) {
        let project = Project(name: starter.name, projectDescription: starter.blurb)
        modelContext.insert(project)
        try? modelContext.save()
        selectedProjectId = project.id
        // Hand the prefilled prompt to the chat. The notification fires
        // after `selectedProjectId` is set so the chat view has a project
        // to attach to. LiquidGlassShell listens and pushes the value
        // into ChatView's TextField via the binding we'll add.
        let payload: [String: Any] = [
            "projectId": project.id.uuidString,
            "prompt": starter.prompt
        ]
        NotificationCenter.default.post(
            name: .onboardingStarterPicked,
            object: nil,
            userInfo: payload
        )
        // Mark in-session as completed so we don't re-show the tour if
        // they delete the project. The SwiftData row is updated only on
        // final "Done".
        onboardingCompletedInSession = true
        Logger.ui.info("Onboarding: picked starter \(starter.id, privacy: .public)")
    }

    /// Step 3 "Start designing" — finalize the tour.
    private func completeOnboarding() {
        let state = OnboardingStateStore.current(in: modelContext)
        state.completed = true
        state.dismissed = true
        state.lastShownAt = .now
        try? modelContext.save()
        onboardingCompletedInSession = true
        Logger.ui.info("Onboarding: completed")
    }

    /// Skip — sets dismissed but not completed. Re-shows the tour on
    /// next empty-workspace launch.
    private func skipOnboarding() {
        let state = OnboardingStateStore.current(in: modelContext)
        state.dismissed = true
        state.lastShownAt = .now
        try? modelContext.save()
        Logger.ui.info("Onboarding: skipped (dismissed)")
    }

    /// "Take the tour again" entry point. Resets the dismissed flag
    /// so the tour re-appears. Called from the sidebar's empty-state
    /// button or the placeholder view's tour button.
    private func showTour() {
        let state = OnboardingStateStore.current(in: modelContext)
        state.dismissed = false
        state.completed = false
        state.currentStep = 0
        state.lastShownAt = .now
        try? modelContext.save()
        // Clear selection so the empty-state branch fires.
        selectedProjectId = nil
        Logger.ui.info("Onboarding: re-opened via sidebar / placeholder")
    }
}

/// Notification name used to hand the prefilled prompt from the
/// onboarding flow to the chat compose bar. Defined here so both
/// publisher and subscriber can use the same name without coupling.
extension Notification.Name {
    static let onboardingStarterPicked = Notification.Name("onboardingStarterPicked")
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
        .modelContainer(for: [Project.self, Conversation.self, OnboardingState.self], inMemory: true)
}

#Preview("App Root — With Project") {
    let container = try! ModelContainer(
        for: Project.self, Conversation.self, OnboardingState.self,
        configurations: ModelConfiguration(isStoredInMemoryOnly: true)
    )
    let ctx = container.mainContext
    let project = Project(name: "Distortion Pedal for Bass")
    ctx.insert(project)
    return AppRootView()
        .environment(DaemonSupervisor())
        .modelContainer(container)
}
#endif
