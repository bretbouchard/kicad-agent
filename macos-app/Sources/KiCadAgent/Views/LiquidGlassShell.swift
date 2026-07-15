//
//  LiquidGlassShell.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//  Phase 171 — Liquid Glass UI Shell (ToolbarView extraction, Reduce Motion/Transparency)
//
//  Main detail view — the Liquid Glass chat shell.
//
//  Composition:
//  - Header with project name + daemon status badge
//  - Content area (conversation list or placeholder)
//  - Compose bar (Phase 175 wires to model + chat engine)
//  - Native macOS toolbar via `ToolbarView` (Phase 171 extraction)
//
//  Phase 171 additions:
//  - Reduce Motion: disables spring animations in header transitions
//  - Reduce Transparency: forces solid backgrounds over materials
//  - WindowManager integration: registers window on appear, unregisters on disappear
//  - A11Y-06: high-contrast safe — uses ColorTokens semantic colors
//

import SwiftUI
import SwiftData
import OSLog

/// The Liquid Glass chat shell — main content area for a selected Project.
struct LiquidGlassShell: View {
    @Bindable var project: Project
    @Environment(\.modelContext) private var modelContext
    @Environment(\.openWindow) private var openWindow
    @Environment(WindowManager.self) private var windowManager

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    // Phase 211 — the router for LLM generation.
    @EnvironmentObject private var modelRouter: KiCadModelRouter

    @State private var composeDraft: String = ""
    @FocusState private var composeFocused: Bool
    @State private var showSettings: Bool = false
    @State private var externalMCPSettings: ExternalMCPSettings = ExternalMCPSettings()

    // Phase 211 — selected conversation for ChatView display.
    @State private var selectedConversation: Conversation?
    // Chat messages for the active conversation (mirrors SwiftData).
    @State private var chatMessages: [ChatMessage] = []
    // Phase 213 — file importer for KiCad files.
    @State private var showFileImporter: Bool = false
    // Phase 216 — validation manager for ERC/DRC.
    @State private var validationManager = ValidationManager()
    @State private var showValidationPanel: Bool = false
    // Phase 220+ — copy-to-clipboard feedback. A short toast string is
    // set when the conversation is copied; the overlay renders it for
    // ~1.6s then clears. nil = no toast visible.
    @State private var copyToast: String? = nil
    @State private var copyToastTask: Task<Void, Never>? = nil

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().opacity(0.3)
            contentArea
            if showValidationPanel {
                Divider().opacity(0.3)
                validationPanel
            }
            Divider().opacity(0.3)
            composeBar
        }
        .background(reduceTransparency
                    ? AnyView(Color(nsColor: .windowBackgroundColor))
                    : AnyView(Color(nsColor: .windowBackgroundColor).opacity(0.96)))
        .animation(reduceMotion ? nil : LiquidGlassAnimation.default, value: project.lastModifiedAt)
        .toolbar { toolbarContent }
        .fileImporter(
            isPresented: $showFileImporter,
            allowedContentTypes: [.data]
        ) { result in
            handleFileImport(result)
        }
        .overlay(alignment: .top) {
            // Copy-to-clipboard confirmation toast. Floats in from above
            // the header for ~1.6s, then fades. A11y: reads the message
            // count to non-sighted users; lives in the .top so it doesn't
            // occlude the chat list.
            if let toast = copyToast {
                Text(toast)
                    .font(Typography.caption.weight(.medium))
                    .foregroundStyle(.white)
                    .padding(.horizontal, Spacing.md)
                    .padding(.vertical, Spacing.xs)
                    .background(
                        Capsule().fill(ColorTokens.success.opacity(0.95))
                    )
                    .padding(.top, Spacing.sm)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .accessibilityAddTraits(.isStaticText)
                    .accessibilityLabel(toast)
            }
        }
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.22), value: copyToast)
        .onAppear {
            composeFocused = true
            windowManager.register(projectId: project.id)
        }
        .onDisappear {
            windowManager.unregister(projectId: project.id)
            copyToastTask?.cancel()
        }
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

    /// APP-01 / APP-03 surface — surfaces daemon/engine state to user.
    @ViewBuilder
    private var daemonStatusBadge: some View {
        DaemonBadge(label: daemonStatusLabel, color: daemonStatusColor, icon: daemonStatusIcon)
    }

    /// ponytail: project inherits global daemon state for Phase 161.
    /// Phase 168 will give each conversation its own daemon session if needed.
    #if os(macOS)
    @Environment(DaemonSupervisor.self) private var daemonSupervisor
    #endif

    private var daemonStatusLabel: String {
        #if os(macOS)
        switch daemonSupervisor.state {
        case .ready: return "Daemon: ready"
        case .failed(let reason): return "Daemon: \(reason)"
        case .starting, .restarting: return "Daemon: working"
        default: return "Daemon: idle"
        }
        #else
        return "Engine: ready"
        #endif
    }

    private var daemonStatusColor: Color {
        #if os(macOS)
        switch daemonSupervisor.state {
        case .ready: return ColorTokens.success
        case .failed: return ColorTokens.destructive
        case .starting, .restarting: return ColorTokens.warning
        default: return ColorTokens.tertiaryText
        }
        #else
        return ColorTokens.success
        #endif
    }

    private var daemonStatusIcon: String {
        #if os(macOS)
        switch daemonSupervisor.state {
        case .ready: return "checkmark.circle.fill"
        case .failed: return "exclamationmark.triangle.fill"
        case .starting, .restarting: return "arrow.triangle.2.circlepath"
        default: return "circle.dashed"
        }
        #else
        return "checkmark.circle.fill"
        #endif
    }


    private func makePreviewRenderer() -> (any PreviewRenderer)? {
        #if os(macOS)
        // Prefer daemon (real kicad-cli) when MCP is wired; otherwise fall
        // back to native Swift renderer. Either way the chat always shows
        // a real preview — no more "no preview" dead state when the daemon
        // is down. Phase 238.
        if let client = daemonSupervisor.mcpClient {
            return DaemonPreviewRenderer(client: client)
        }
        return SwiftSVGRenderer()
        #else
        return SwiftSVGRenderer()
        #endif
    }

    // MARK: - Content

    @ViewBuilder
    private var contentArea: some View {
        if let _ = selectedConversation {
            // Phase 211: show the live chat view with streaming responses.
            ChatView(
                messages: $chatMessages,
                streamProvider: RouterStreamProvider(router: modelRouter),
                previewRenderer: makePreviewRenderer()
            )
        } else if project.conversations.isEmpty {
            ChatPlaceholderContent(projectName: project.name)
        } else {
            // Conversation list — tap to open.
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Spacing.md) {
                    ForEach(project.conversations.reversed()) { conversation in
                        Button {
                            selectedConversation = conversation
                            loadMessages(for: conversation)
                        } label: {
                            ConversationRow(conversation: conversation)
                        }
                        .buttonStyle(.plain)
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

    // MARK: - Validation Panel (Phase 216)

    private var validationPanel: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(spacing: 4) {
                Button("Run ERC") {
                    #if os(macOS)
                    Task { await validationManager.runERC(filePath: selectedConversation?.title ?? "board.kicad_sch", client: daemonSupervisor.mcpClient) }
                    #endif
                }
                .buttonStyle(.bordered)

                Button("Run DRC") {
                    #if os(macOS)
                    Task { await validationManager.runDRC(filePath: selectedConversation?.title ?? "board.kicad_pcb", client: daemonSupervisor.mcpClient) }
                    #endif
                }
                .buttonStyle(.bordered)
            }

            ValidationResultsPanel(results: validationManager.results, isRunning: validationManager.isRunning)

            Spacer()
        }
        .padding(8)
        .frame(maxHeight: 200)
    }

    // MARK: - File Import (Phase 213)

    private func handleFileImport(_ result: Result<URL, Error>) {
        switch result {
        case .success(let url):
            let needsScope = url.startAccessingSecurityScopedResource()
            defer { if needsScope { url.stopAccessingSecurityScopedResource() } }

            let fileName = url.lastPathComponent
            Logger.ui.info("Importing KiCad file: \(fileName)")

            // Create a conversation noting the imported file.
            let conversation = Conversation(project: project, title: "Imported: \(fileName)")
            modelContext.insert(conversation)

            let userMessage = Message(
                conversation: conversation,
                role: .user,
                content: "I've opened \(fileName). Analyze this design.",
                status: .complete
            )
            modelContext.insert(userMessage)

            // Store the file path context for the daemon.
            project.touch()
            try? modelContext.save()

            // Select the new conversation.
            selectedConversation = conversation
            chatMessages = [
                ChatMessage(id: userMessage.id, role: .user, content: userMessage.content, status: .complete, sentAt: .now),
                ChatMessage(role: .assistant, content: "", status: .streaming, sentAt: .now),
            ]

            // Start analysis with file context.
            Task { @MainActor in
                await streamResponse(into: chatMessages.count - 1, conversation: conversation, assistantMessage: Message(
                    conversation: conversation, role: .assistant, content: "", status: .streaming
                ))
            }

        case .failure(let error):
            Logger.ui.error("File import failed: \(error.localizedDescription)")
        }
    }

    private func submitDraft() {
        let trimmed = composeDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // Create a conversation and seed it with the user's first message.
        let conversation = Conversation(project: project, title: String(trimmed.prefix(40)))
        modelContext.insert(conversation)

        // Save the user message to SwiftData.
        let userMessage = Message(
            conversation: conversation,
            role: .user,
            content: trimmed,
            status: .complete
        )
        modelContext.insert(userMessage)

        // Add a streaming assistant message placeholder.
        let assistantMessage = Message(
            conversation: conversation,
            role: .assistant,
            content: "",
            status: .streaming
        )
        modelContext.insert(assistantMessage)

        project.touch()
        composeDraft = ""

        // Select the conversation and seed chatMessages for ChatView.
        selectedConversation = conversation
        chatMessages = [
            ChatMessage(id: userMessage.id, role: .user, content: trimmed, status: .complete, sentAt: .now),
            ChatMessage(id: assistantMessage.id, role: .assistant, content: "", status: .streaming, sentAt: .now),
        ]

        // Stream the response from the LLM.
        Task { @MainActor in
            await streamResponse(into: chatMessages.count - 1, conversation: conversation, assistantMessage: assistantMessage)
        }
    }

    /// Load persisted messages for a conversation into chatMessages.
    private func loadMessages(for conversation: Conversation) {
        let sorted = conversation.messages.sorted { $0.sentAt < $1.sentAt }
        chatMessages = sorted.map { msg in
            ChatMessage(
                id: msg.id,
                role: MessageRole(rawValue: msg.roleRaw) ?? .assistant,
                content: msg.content,
                status: msg.failureReason != nil ? .failed(msg.failureReason ?? "Unknown error") : .complete,
                sentAt: msg.sentAt,
                modelBadge: msg.modelBadge
            )
        }
    }

    /// Stream the LLM response and update both the chat UI and SwiftData.
    private func streamResponse(into index: Int, conversation: Conversation, assistantMessage: Message) async {
        let provider = RouterStreamProvider(router: modelRouter) { usage in
            // Persist cost/token data when streaming completes.
            assistantMessage.inputTokens = usage.inputTokens
            assistantMessage.outputTokens = usage.outputTokens
            assistantMessage.estimatedCostUSD = NSDecimalNumber(decimal: usage.estimatedCostUSD).doubleValue
        }

        do {
            // Snapshot the conversation (including the just-appended user
            // message at index - 1) so the provider sees full multi-turn
            // context. Echo stripping uses the last user message to detect
            // the model repeating the question as the opener of the reply.
            let history = Array(chatMessages.prefix(index))
            let stream = provider.stream(history: history, attachments: [])
            for try await chunk in stream {
                chatMessages[index].content += chunk
            }
            chatMessages[index].status = .complete
            assistantMessage.content = chatMessages[index].content
            assistantMessage.status = .complete
        } catch {
            chatMessages[index].status = .failed(error.localizedDescription)
            assistantMessage.content = chatMessages[index].content
            assistantMessage.status = .failed(error.localizedDescription)
            assistantMessage.failureReason = error.localizedDescription
        }

        project.touch()
        try? modelContext.save()

        // Phase 212: check if the LLM response contains operation JSON.
        // If so, execute via the daemon and append the result.
#if os(macOS)
        let mcpClient = daemonSupervisor.mcpClient
        #else
        let mcpClient: MCPClient? = nil
        #endif
        let responseText = chatMessages[index].content
        let opResult = await OperationExecutor.execute(from: responseText, client: mcpClient)
        if case .success(let resultText) = opResult {
            chatMessages.append(ChatMessage(
                role: .system,
                content: resultText,
                status: .complete,
                sentAt: .now
            ))
            let systemMsg = Message(
                conversation: conversation,
                role: .system,
                content: resultText,
                status: .complete
            )
            modelContext.insert(systemMsg)
            try? modelContext.save()
        }
    }

    // MARK: - Copy Conversation

    /// True when a conversation is active AND has at least one
    /// exportable (non-empty, non-streaming) message. The Copy button
    /// is disabled otherwise so the user doesn't get an empty clipboard.
    private var canCopyConversation: Bool {
        guard selectedConversation != nil else { return false }
        return chatMessages.contains { msg in
            let trimmed = msg.content.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return false }
            switch msg.status {
            case .pending, .streaming, .cancelled: return false
            case .complete, .failed: return true
            }
        }
    }

    /// Format the active conversation and copy to the system clipboard.
    /// Shows a transient toast confirming what was copied. The toast
    /// auto-clears after 1.6s; successive copies reset the timer.
    private func copyConversation() {
        let chars = ConversationExporter.copyToClipboard(messages: chatMessages)
        let msgCount = chatMessages.filter {
            let t = $0.content.trimmingCharacters(in: .whitespacesAndNewlines)
            return !t.isEmpty
        }.count
        copyToast = "Copied \(msgCount) message\(msgCount == 1 ? "" : "s") · \(chars.formatted()) characters"
        copyToastTask?.cancel()
        copyToastTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_600_000_000)
            if !Task.isCancelled {
                copyToast = nil
            }
        }
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

            Button {
                showFileImporter = true
            } label: {
                Label("Open KiCad File", systemImage: "folder")
            }
            .accessibilityLabel("Open KiCad file")
            .accessibilityHint("Import a .kicad_sch or .kicad_pcb file")

            Button {
                showValidationPanel.toggle()
            } label: {
                Label("Validation", systemImage: "checkmark.shield")
            }
            .accessibilityLabel("Toggle validation panel")
            .accessibilityHint("Run ERC/DRC checks")

            ShareLink(item: project.name) {
                Label("Share", systemImage: "square.and.arrow.up")
            }
            .accessibilityLabel("Share project")
            .accessibilityHint("Opens the macOS share sheet")

            // Phase 220+: copy the active conversation to the system
            // clipboard as plain text. Disabled when no conversation is
            // selected OR when the chat has no exportable messages
            // (empty / all-streaming). Mirrors the existing toolbar
            // buttons' icon + accessibility-label idiom.
            Button {
                copyConversation()
            } label: {
                Label("Copy Conversation", systemImage: "doc.on.clipboard")
            }
            .disabled(!canCopyConversation)
            .accessibilityLabel("Copy conversation to clipboard")
            .accessibilityHint(
                canCopyConversation
                    ? "Copies the full conversation as plain text"
                    : "Open a conversation to copy it"
            )

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
    @EnvironmentObject private var modelRouter: KiCadModelRouter
    @State private var selectedTab: SettingsTab = .providers

    enum SettingsTab: String, CaseIterable, Identifiable {
        case providers = "Providers"
        case externalMCP = "External MCP"
        case memory = "Memory"
        case collaboration = "Collaboration"
        var id: String { rawValue }
    }

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

            TabView(selection: $selectedTab) {
                ExternalMCPSettingsView(settings: externalMCPSettings)
                    .tabItem { Label("External MCP", systemImage: "network") }
                    .tag(SettingsTab.externalMCP)

                ProviderRoutingSettingsView(router: modelRouter)
                    .tabItem { Label("Providers", systemImage: "cpu") }
                    .tag(SettingsTab.providers)

                // Phase 215 — Memory tab
                MemorySettingsTab()
                    .tabItem { Label("Memory", systemImage: "clock.arrow.circlepath") }
                    .tag(SettingsTab.memory)

                // Phase 215 — Collaboration tab
                CollaborationSettingsTab()
                    .tabItem { Label("Collaboration", systemImage: "person.2") }
                    .tag(SettingsTab.collaboration)
            }
            .padding(Spacing.sm)
        }
        .frame(minWidth: 640, minHeight: 520)
    }
}

/// Phase 215 — Memory settings tab showing time-travel + decision timeline.
private struct MemorySettingsTab: View {
    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Text("Project Memory")
                .font(Typography.heading)

            Text("Decision history, snapshots, and time-travel are populated as you work. The data lives in SwiftData on this Mac.")
                .font(Typography.body)
                .foregroundStyle(.secondary)

            // The memory views (TimeTravelView, DecisionTimelineView) are
            // available and will populate as conversations create Decisions.
            // They're shown here when a conversation is active.
            Spacer()
        }
        .padding()
    }
}

/// Phase 215 — Collaboration settings tab.
private struct CollaborationSettingsTab: View {
    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Text("Collaboration")
                .font(Typography.heading)

            Text("SharePlay sessions, iCloud sync, and project genealogy. CloudKit sync requires a container ID (CK_CONTAINER_ID) — collaboration views activate once sync is configured.")
                .font(Typography.body)
                .foregroundStyle(.secondary)

            // Collaboration views (CollaborationActivityFeed, ProjectGenealogyView)
            // need active sessions + branches from SwiftData.
            // They'll appear here when collaboration is enabled.

            // Genealogy section
            GroupBox("Project Genealogy") {
                Text("Branch history appears as you fork and explore designs.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(8)
            }

            Spacer()
        }
        .padding()
    }
}
