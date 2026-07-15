//
//  ChatView.swift
//  Volta
//
//  Phase 175 — Chat Interface
//  Phase 239 — Image Attachment UI
//
//  Main chat surface — message list, streaming, image attachments, cost
//  tracking, inline renders. Composes MessageBubbleView + ImageAttachmentView.
//
//  CHAT-01/02/05/06/07/08.
//  IMG-01/02/03/04: attach button (NSOpenPanel), drop target, paste
//  handler, validation + compression, router bridging.
//
//  Scroll behavior:
//  - Smart auto-scroll: only auto-scrolls to the bottom if the user is
//    already near the bottom. If they've scrolled up to read older
//    content, streaming updates do NOT yank them back to the bottom.
//  - Floating "jump to bottom" button appears when the user is scrolled
//    away from the latest message.
//  - Trailing invisible spacer inside the ScrollView ensures the last
//    message can scroll fully above the bottom edge.
//
//  Image attachment sources (Phase 239):
//  1. Paperclip button → NSOpenPanel filtered to png/jpeg/heic
//  2. Drag & drop a file onto the compose bar
//  3. Cmd+V with a screenshot on the clipboard
//  All three funnel through `attachImage(from:)` which validates,
//  compresses if needed, and appends to `pendingImages`.
//

import SwiftUI
import OSLog
import AppKit
import UniformTypeIdentifiers

/// Main chat view for a conversation.
struct ChatView: View {
    @Binding var messages: [ChatMessage]
    let streamProvider: ChatStreamProvider
    let previewRenderer: PreviewRenderer?

    @State private var inputDraft: String = ""
    @State private var attachments: [ImageAttachment] = []
    @State private var pendingImages: [ImageAttachment] = []
    @State private var attachError: String?
    @State private var streamingTask: Task<Void, Never>?
    @State private var scrollProxy: ScrollViewProxy?
    @State private var pasteMonitor: Any?

    /// Tracks whether the user is "stuck to the bottom" (within ~80pt of
    /// the last message). Updated by `onScrollGeometryChange`. Drives
    /// both auto-scroll behavior and the jump-to-bottom button visibility.
    @State private var isAtBottom: Bool = true

    /// Last `messages.count` seen. Used so we only auto-scroll on a real
    /// new-message event, not on every content mutation of the last message.
    @State private var lastMessageCount: Int = 0

    var body: some View {
        VStack(spacing: 0) {
            messageList
            Divider().opacity(0.3)
            composeBar
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Spacing.md) {
                    ForEach(messages) { msg in
                        MessageBubbleView(message: msg, previewRenderer: previewRenderer)
                            .id(msg.id)
                    }
                    // Tail spacer — gives the last message breathing room
                    // so it can scroll fully into view above the compose
                    // bar (without this, the bottom of the last message
                    // gets clipped by the ScrollView's bottom edge).
                    Color.clear
                        .frame(height: Spacing.md)
                        .id("__tail__")
                }
                .padding(Spacing.lg)
            }
            .frame(maxHeight: .infinity)
            // Detect user-initiated scrolling via a simultaneous drag
            // gesture. When the user drags up to read older content,
            // mark them as "not at the bottom" so streaming updates
            // stop yanking them back, and show the jump-to-bottom
            // button. When a new message arrives we re-arm it.
            .simultaneousGesture(
                DragGesture(minimumDistance: 4)
                    .onChanged { _ in
                        if isAtBottom { isAtBottom = false }
                    }
            )
            .onAppear {
                scrollProxy = proxy
                lastMessageCount = messages.count
                isAtBottom = true
            }
            .onChange(of: messages.count) { _, newCount in
                let isNewMessage = newCount > lastMessageCount
                lastMessageCount = newCount
                if isNewMessage, let lastId = messages.last?.id {
                    // A brand new message arrived — always reveal it.
                    withAnimation(.easeOut(duration: 0.18)) {
                        proxy.scrollTo(lastId, anchor: .bottom)
                    }
                    isAtBottom = true
                } else if isAtBottom, let lastId = messages.last?.id {
                    // Streaming into the last message and user is at bottom
                    // — follow along so the caret stays visible.
                    proxy.scrollTo(lastId, anchor: .bottom)
                }
            }
            .overlay(alignment: .bottomTrailing) {
                if !isAtBottom {
                    jumpToBottomButton
                        .padding(Spacing.md)
                        .transition(.opacity.combined(with: .scale(scale: 0.9)))
                }
            }
            .animation(.easeInOut(duration: 0.18), value: isAtBottom)
        }
        .accessibilityLabel("Conversation messages")
    }

    private var jumpToBottomButton: some View {
        Button {
            guard let proxy = scrollProxy, let lastId = messages.last?.id else { return }
            withAnimation(.easeOut(duration: 0.22)) {
                proxy.scrollTo(lastId, anchor: .bottom)
            }
            isAtBottom = true
        } label: {
            Image(systemName: "arrow.down.circle.fill")
                .font(.system(size: 28))
                .foregroundStyle(Color.accentColor)
                .background(
                    Circle()
                        .fill(Color(nsColor: .controlBackgroundColor))
                        .shadow(color: .black.opacity(0.15), radius: 4, y: 1)
                )
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Jump to latest message")
        .accessibilityHint("Scrolls the conversation to the most recent message")
    }

    private var composeBar: some View {
        VStack(spacing: Spacing.xs) {
            if let attachError {
                attachErrorBanner(attachError)
            }
            if !pendingImages.isEmpty {
                pendingImagesRow
            }
            HStack(spacing: Spacing.sm) {
                attachButton
                TextField(
                    "Describe your hardware intent…",
                    text: $inputDraft,
                    axis: .vertical
                )
                .textFieldStyle(.plain)
                .font(Typography.body)
                .lineLimit(1...4)
                .submitLabel(.send)
                .onSubmit(sendMessage)
                .accessibilityLabel("Hardware design intent")
                .accessibilityHint("Type what you want to design, then press return")
                sendButton
            }
            .liquidGlassToolbar()
            .padding(Spacing.md)
        }
        .onDrop(of: [.fileURL], isTargeted: nil) { providers in
            handleDrop(providers: providers)
        }
        .onAppear { installPasteMonitor() }
        .onDisappear { removePasteMonitor() }
        // Phase 242 — listen for the onboarding tour's "starter picked"
        // notification and pre-fill the compose bar with the canonical
        // prompt. Idempotent: only fires when the prompt is non-empty
        // and the field is currently empty (so a second notification
        // doesn't overwrite the user's edits).
        .onReceive(NotificationCenter.default.publisher(for: .onboardingStarterPicked)) { note in
            if let prompt = note.userInfo?["prompt"] as? String,
               !prompt.isEmpty,
               inputDraft.isEmpty {
                inputDraft = prompt
            }
        }
    }

    /// Compact error banner shown above the compose bar when an
    /// attachment failed (wrong file type, read error, etc). Tap to dismiss.
    @ViewBuilder
    private func attachErrorBanner(_ message: String) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(ColorTokens.destructive)
            Text(message)
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.destructive)
                .lineLimit(2)
            Spacer(minLength: 0)
            Button {
                attachError = nil
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(ColorTokens.secondaryText)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss attachment error")
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.xs)
        .background(
            RoundedRectangle(cornerRadius: CornerRadius.small, style: .continuous)
                .fill(ColorTokens.destructive.opacity(0.1))
        )
        .padding(.horizontal, Spacing.md)
        .padding(.top, Spacing.xs)
    }

    private var pendingImagesRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Spacing.xs) {
                ForEach(pendingImages) { attachment in
                    ImageAttachmentView(attachment: attachment)
                        .frame(width: 48, height: 48)
                        .overlay(alignment: .topTrailing) {
                            Button {
                                pendingImages.removeAll { $0.id == attachment.id }
                            } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundStyle(.white, Color.black.opacity(0.6))
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Remove attachment \(attachment.fileName)")
                        }
                }
            }
            .padding(.horizontal, Spacing.md)
            .padding(.top, Spacing.xs)
        }
    }

    private var attachButton: some View {
        Button(action: presentOpenPanel) {
            Image(systemName: "paperclip")
                .font(Typography.body)
                .foregroundStyle(ColorTokens.secondaryText)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Attach reference image")
        .accessibilityHint("Opens picker for reference schematics or photos")
    }

    /// Open NSOpenPanel filtered to image types. Multi-select enabled
    /// so the user can drop a screenshot + a reference image at once.
    @MainActor
    private func presentOpenPanel() {
        let panel = NSOpenPanel()
        panel.title = "Attach reference image"
        panel.message = "Pick one or more PNG, JPEG, or HEIC images to attach to this message."
        panel.prompt = "Attach"
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        if #available(macOS 12.0, *) {
            panel.allowedContentTypes = [
                UTType.png,
                UTType.jpeg,
                UTType.heic
            ]
        }
        let response = panel.runModal()
        guard response == .OK else { return }
        for url in panel.urls {
            attachImage(from: url)
        }
    }

    /// Handle a SwiftUI .onDrop event. SwiftUI gives us NSItemProviders;
    /// we need to extract a file URL out of each, then run the same
    /// `attachImage(from:)` pipeline as the picker. Returns true if
    /// any attachment was successfully added (SwiftUI's contract).
    private func handleDrop(providers: [NSItemProvider]) -> Bool {
        var handled = false
        for provider in providers {
            guard provider.canLoadObject(ofClass: URL.self) else { continue }
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                guard let url else { return }
                DispatchQueue.main.async {
                    attachImage(from: url)
                }
            }
            handled = true
        }
        return handled
    }

    /// Install a local NSEvent monitor that catches Cmd+V when the
    /// compose bar's text field has focus. If the pasteboard has an
    /// image, dump it to a temp file and attach it. Other content
    /// types pass through (the system handles plain-text paste).
    @MainActor
    private func installPasteMonitor() {
        guard pasteMonitor == nil else { return }
        pasteMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            // Only intercept when the user is in our compose bar's
            // text field (not when they're reading history, or
            // focused on a preview thumbnail, etc).
            guard event.keyCode == 9 /* V */ else { return event }
            let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            guard flags.contains(.command) else { return event }
            guard NSApp.keyWindow?.firstResponder is NSText else { return event }
            if let url = writeClipboardImageToTemp() {
                attachImage(from: url)
                // Swallow the event so the text field doesn't paste
                // a base64 blob in addition to attaching the image.
                return nil
            }
            return event
        }
    }

    @MainActor
    private func removePasteMonitor() {
        if let monitor = pasteMonitor {
            NSEvent.removeMonitor(monitor)
            pasteMonitor = nil
        }
    }

    /// If the clipboard has an image, write it to a temp file and
    /// return the URL. Returns nil if the clipboard doesn't have an
    /// image (e.g. plain text or a file URL).
    @MainActor
    private func writeClipboardImageToTemp() -> URL? {
        let pb = NSPasteboard.general
        // PNG is the most reliable cross-app format for screenshots.
        guard let data = pb.data(forType: .png) ?? pb.data(forType: .tiff) else {
            return nil
        }
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("kicad-agent-attachments", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent("paste-\(UUID().uuidString).png")
        do {
            try data.write(to: url, options: .atomic)
            return url
        } catch {
            Logger.ui.error(
                "Paste image write failed: \(error.localizedDescription, privacy: .public)"
            )
            return nil
        }
    }

    /// Validate, optionally compress, and append a file URL as a chat
    /// image attachment. Surfaces a friendly error in the banner if
    /// the file isn't a supported image.
    @MainActor
    private func attachImage(from url: URL) {
        do {
            var attachment = try ImageAttachmentFactory.make(from: url)
            if let compressed = try ImageAttachmentCompressor.compressIfNeeded(attachment) {
                attachment = compressed
            }
            // Replace an existing attachment with the same id (idempotent
            // re-attaches from the same source).
            pendingImages.removeAll { $0.id == attachment.id }
            pendingImages.append(attachment)
            attachError = nil
        } catch let error as ImageAttachmentError {
            attachError = error.errorDescription
            Logger.ui.info(
                "Attach rejected: \(error.errorDescription ?? "unknown", privacy: .public)"
            )
        } catch {
            attachError = error.localizedDescription
            Logger.ui.error(
                "Attach failed: \(error.localizedDescription, privacy: .public)"
            )
        }
    }

    private var sendButton: some View {
        Button(action: sendMessage) {
            Image(systemName: "arrow.up.circle.fill")
                .font(.system(size: 24))
        }
        .buttonStyle(.plain)
        .disabled(inputDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && pendingImages.isEmpty)
        .accessibilityLabel("Send message")
        .accessibilityHint("Sends your design intent to the model")
    }

    private func sendMessage() {
        let trimmed = inputDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || !pendingImages.isEmpty else { return }

        let userMessage = ChatMessage(
            role: .user,
            content: trimmed,
            status: .complete,
            attachments: pendingImages
        )
        messages.append(userMessage)

        // Stub assistant message that streams.
        let assistantId = UUID()
        let assistantMessage = ChatMessage(
            id: assistantId,
            role: .assistant,
            content: "",
            status: .streaming,
            modelBadge: "AppleLocal"
        )
        messages.append(assistantMessage)

        // Reset input.
        inputDraft = ""
        let promptAttachments = pendingImages
        pendingImages = []

        // Snapshot the conversation history (including the just-appended
        // user message) so the provider sees the full multi-turn context.
        // Sending the @Binding array directly would race with the UI's
        // streaming mutations.
        let historySnapshot = messages

        // Kick off streaming.
        streamingTask?.cancel()
        streamingTask = Task { [streamProvider] in
            do {
                for try await chunk in streamProvider.stream(history: historySnapshot, attachments: promptAttachments) {
                    try Task.checkCancellation()
                    await MainActor.run {
                        guard let idx = messages.firstIndex(where: { $0.id == assistantId }) else { return }
                        messages[idx].content += chunk
                        // If user is at the bottom, follow along. The
                        // proxy.scrollTo call in onChange(of:messages.count)
                        // won't fire here (count is unchanged) so we
                        // manually re-scroll to keep the caret visible.
                        if isAtBottom, let proxy = scrollProxy {
                            proxy.scrollTo(assistantId, anchor: .bottom)
                        }
                    }
                }
                await MainActor.run {
                    guard let idx = messages.firstIndex(where: { $0.id == assistantId }) else { return }
                    messages[idx].status = .complete
                }
            } catch is CancellationError {
                await MainActor.run {
                    guard let idx = messages.firstIndex(where: { $0.id == assistantId }) else { return }
                    messages[idx].status = .cancelled
                }
            } catch {
                Logger.ui.error("Stream failed: \(error.localizedDescription, privacy: .public)")
                await MainActor.run {
                    guard let idx = messages.firstIndex(where: { $0.id == assistantId }) else { return }
                    messages[idx].status = .failed(error.localizedDescription)
                }
            }
        }
    }
}
