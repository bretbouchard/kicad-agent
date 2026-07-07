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
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom) {
            sidebarFooter
        }
        .navigationTitle("KiCad Agent")
        .accessibilityLabel("Project list")
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
