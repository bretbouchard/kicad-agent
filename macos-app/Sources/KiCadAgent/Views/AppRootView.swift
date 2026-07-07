//
//  AppRootView.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//
//  Root container for the KiCad Agent app.
//
//  Composition:
//  - NavigationSplitView: sidebar (ProjectSidebar) + main (LiquidGlassShell)
//  - Recovery UI overlay when daemon state is `.failed` (APP-01 augmentation)
//  - New Project button (modelContainer-aware)
//

import SwiftUI
import SwiftData
import OSLog

/// Root view of the KiCad Agent app shell.
struct AppRootView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(DaemonSupervisor.self) private var daemonSupervisor

    @Query(sort: \Project.lastModifiedAt, order: .reverse) private var projects: [Project]

    @State private var selectedProjectId: UUID?
    @State private var showErrorRecovery: Bool = false

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

    // MARK: - Mutations

    private func createProject() {
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
        .modelContainer(container)
}
#endif
