//
//  LiquidGlassShell.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//
//  Main detail view — the Liquid Glass chat shell.
//
//  Composition:
//  - Toolbar with New/Open/Settings/Share (APP-06 multi-window handled at scene level)
//  - Conversation list (left rail inside detail, optional)
//  - Chat area (placeholder for Phase 165)
//  - Compose bar (placeholder for Phase 165)
//

import SwiftUI
import SwiftData
import OSLog

/// The Liquid Glass chat shell — main content area for a selected Project.
struct LiquidGlassShell: View {
    @Bindable var project: Project
    @Environment(\.modelContext) private var modelContext
    @Environment(\.openWindow) private var openWindow

    @State private var composeDraft: String = ""
    @FocusState private var composeFocused: Bool
    @State private var showSettings: Bool = false
    @State private var externalMCPSettings: ExternalMCPSettings = ExternalMCPSettings()

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().opacity(0.3)
            contentArea
            Divider().opacity(0.3)
            composeBar
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .toolbar { toolbarContent }
        .onAppear { composeFocused = true }
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(project.name)
                    .font(Typography.title)
                    .accessibilityAddTraits(.isHeader)
                Text("Last modified \(project.lastModifiedAt.formatted(.relative(presentation: .named)))")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.secondaryText)
            }
            Spacer()
            daemonStatusBadge
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.md)
    }

    /// APP-01 / APP-03 surface — surfaces daemon state to user.
    @ViewBuilder
    private var daemonStatusBadge: some View {
        switch projectDaemonState {
        case .notStarted, .shutDown:
            DaemonBadge(label: "Daemon: idle", color: ColorTokens.tertiaryText, icon: "circle.dashed")
        case .starting, .shuttingDown, .restarting:
            DaemonBadge(label: "Daemon: working", color: ColorTokens.warning, icon: "arrow.triangle.2.circlepath")
        case .ready:
            DaemonBadge(label: "Daemon: ready", color: ColorTokens.success, icon: "checkmark.circle.fill")
        case .failed(let reason):
            DaemonBadge(label: "Daemon: \(reason)", color: ColorTokens.destructive, icon: "exclamationmark.triangle.fill")
        }
    }

    /// ponytail: project inherits global daemon state for Phase 161.
    /// Phase 168 will give each conversation its own daemon session if needed.
    @Environment(DaemonSupervisor.self) private var daemonSupervisor
    private var projectDaemonState: DaemonState { daemonSupervisor.state }

    // MARK: - Content

    @ViewBuilder
    private var contentArea: some View {
        if project.conversations.isEmpty {
            ChatPlaceholderContent(projectName: project.name)
        } else {
            // Phase 165 will replace this with ConversationListView.
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Spacing.md) {
                    ForEach(project.conversations) { conversation in
                        ConversationRow(conversation: conversation)
                    }
                }
                .padding(Spacing.lg)
            }
        }
    }

    // MARK: - Compose bar (Phase 165 wires to model)

    private var composeBar: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "paperclip")
                .font(Typography.body)
                .foregroundStyle(ColorTokens.secondaryText)
                .accessibilityLabel("Attach reference image")
                .accessibilityHint("Opens file picker for reference schematics or photos")
            TextField(
                "Describe your hardware intent…",
                text: $composeDraft,
                axis: .vertical
            )
            .textFieldStyle(.plain)
            .font(Typography.body)
            .focused($composeFocused)
            .lineLimit(1...4)
            .submitLabel(.send)
            .onSubmit(submitDraft)
            .accessibilityLabel("Hardware design intent")
            .accessibilityHint("Describe what you want to design. Press return to send.")
            Button(action: submitDraft) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 24))
            }
            .buttonStyle(.plain)
            .disabled(composeDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .accessibilityLabel("Send message")
            .accessibilityHint("Sends your design intent to the model")
        }
        .liquidGlassToolbar()
        .padding(Spacing.md)
    }

    private func submitDraft() {
        let trimmed = composeDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        // Phase 165 will route this to ConversationEngine + KiCadModelProvider.
        Logger.ui.info("Compose submitted (Phase 165 wires model): \(trimmed.prefix(80), privacy: .public)…")
        let conversation = Conversation(project: project, title: String(trimmed.prefix(40)))
        modelContext.insert(conversation)
        project.touch()
        composeDraft = ""
    }

    // MARK: - Toolbar

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            Button {
                // APP-06: cmd+N at scene level. This button creates a new project
                // in the current window rather than opening a new window.
                let new = Project.newDefault()
                modelContext.insert(new)
            } label: {
                Label("New Project", systemImage: "plus")
            }
            .accessibilityLabel("New project")
            .accessibilityHint("Creates a new project in this window")

            Button {
                openWindow(id: "default")
            } label: {
                Label("New Window", systemImage: "macwindow")
            }
            .accessibilityLabel("New window")
            .accessibilityHint("Opens a new project window (cmd+N)")

            ShareLink(item: project.name) {
                Label("Share", systemImage: "square.and.arrow.up")
            }
            .accessibilityLabel("Share project")
            .accessibilityHint("Opens the macOS share sheet")

            Button {
                showSettings = true
            } label: {
                Label("Settings", systemImage: "gearshape")
            }
            .accessibilityLabel("Settings")
            .accessibilityHint("Opens provider settings, model configuration, and daemon options")
            .sheet(isPresented: $showSettings) {
                SettingsSheet(externalMCPSettings: externalMCPSettings)
            }
        }
    }
}

// MARK: - Subviews

/// Compact daemon status pill.
private struct DaemonBadge: View {
    let label: String
    let color: Color
    let icon: String

    var body: some View {
        HStack(spacing: Spacing.xxs) {
            Image(systemName: icon)
            Text(label)
                .font(Typography.caption.weight(.medium))
        }
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, Spacing.xxs)
        .background(color.opacity(0.12), in: Capsule())
        .foregroundStyle(color)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(label)
    }
}

/// Chat placeholder shown when the project has no conversations yet.
private struct ChatPlaceholderContent: View {
    let projectName: String

    var body: some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.system(size: 48))
                .foregroundStyle(ColorTokens.tertiaryText)
                .accessibilityHidden(true)
            Text("Start designing \(projectName)")
                .font(Typography.heading)
                .foregroundStyle(ColorTokens.secondaryText)
            Text("Describe your hardware intent in the bar below.")
                .font(Typography.body)
                .foregroundStyle(ColorTokens.tertiaryText)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Single conversation row — minimal for Phase 161.
private struct ConversationRow: View {
    let conversation: Conversation

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(conversation.title)
                .font(Typography.heading)
            Text(conversation.startedAt.formatted(date: .abbreviated, time: .shortened))
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.tertiaryText)
        }
        .liquidGlassPanel()
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Conversation \(conversation.title)")
        .accessibilityHint("Started \(conversation.startedAt.formatted(.relative(presentation: .named)))")
    }
}

/// Top-level settings sheet. Phase 163 wires External MCP; Phase 203 adds
/// the rest (Provider Settings, model config, daemon options).
struct SettingsSheet: View {
    @Bindable var externalMCPSettings: ExternalMCPSettings
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Settings")
                    .font(Typography.title)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Button("Done") { dismiss() }
                    .accessibilityLabel("Done")
                    .keyboardShortcut(.defaultAction)
            }
            .padding(Spacing.md)

            Divider().opacity(0.3)

            ExternalMCPSettingsView(settings: externalMCPSettings)
        }
        .frame(minWidth: 560, minHeight: 480)
    }
}
