//
//  ProjectSidebar.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//
//  Sidebar showing all projects. Source of truth: @Query in AppRootView.
//

import SwiftUI
import SwiftData
import OSLog

/// Sidebar listing all projects with create / delete actions.
struct ProjectSidebar: View {
    let projects: [Project]
    @Binding var selectedProjectId: UUID?
    let onCreateProject: () -> Void
    let onDeleteProject: (Project) -> Void
    /// Phase 242 — when the workspace is empty, surface a "Show tour"
    /// button that re-opens the onboarding flow.
    let onShowTour: () -> Void

    var body: some View {
        List(selection: $selectedProjectId) {
            Section("Projects") {
                ForEach(projects) { project in
                    ProjectRow(project: project)
                        .tag(project.id)
                        .contextMenu {
                            Button("Delete", role: .destructive) {
                                onDeleteProject(project)
                            }
                            .accessibilityLabel("Delete project \(project.name)")
                        }
                }
                if projects.isEmpty {
                    emptyStateRow
                }
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom) {
            sidebarFooter
        }
        .navigationTitle("KiCad Agent")
        .accessibilityLabel("Project list")
    }

    private var emptyStateRow: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text("No projects yet")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.secondaryText)
            Button(action: onShowTour) {
                Label("Show welcome tour", systemImage: "hand.wave.fill")
                    .font(Typography.caption)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Show welcome tour")
            .accessibilityHint("Re-opens the 3-step onboarding walkthrough")
        }
        .padding(.vertical, Spacing.xs)
    }

    private var sidebarFooter: some View {
        HStack {
            Button(action: onCreateProject) {
                Label("New Project", systemImage: "plus.circle.fill")
            }
            .buttonStyle(.borderedProminent)
            .accessibilityLabel("New project")
            .accessibilityHint("Creates a new KiCad Agent project")
            Spacer()
            Text("\(projects.count) project\(projects.count == 1 ? "" : "s")")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.secondaryText)
                .accessibilityLabel("\(projects.count) projects")
        }
        .padding(Spacing.sm)
        .background(.ultraThinMaterial)
    }
}

/// Single project row in the sidebar.
private struct ProjectRow: View {
    @Bindable var project: Project

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(project.name)
                .font(Typography.body.weight(.medium))
                .lineLimit(1)
            HStack(spacing: Spacing.xxs) {
                Image(systemName: "calendar")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
                    .accessibilityHidden(true)
                Text(project.lastModifiedAt.formatted(.relative(presentation: .named)))
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(project.name)
        .accessibilityHint("Last modified \(project.lastModifiedAt.formatted(.relative(presentation: .named))). Double-click to open.")
    }
}
