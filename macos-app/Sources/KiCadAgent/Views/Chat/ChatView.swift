//
//  ChatView.swift
//  KiCadAgent
//
//  Phase 175 — Chat Interface
//
//  Main chat surface — message list, streaming, image attachments, cost
//  tracking, inline renders. Composes MessageBubbleView + ImageAttachmentView.
//
//  CHAT-01/02/05/06/07/08.
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

import SwiftUI
import OSLog

/// Main chat view for a conversation.
struct ChatView: View {
    @Binding var messages: [ChatMessage]
    let streamProvider: ChatStreamProvider
    let previewRenderer: PreviewRenderer?

    @State private var inputDraft: String = ""
    @State private var attachments: [ImageAttachment] = []
    @State private var pendingImages: [ImageAttachment] = []
    @State private var streamingTask: Task<Void, Never>?
    @State private var scrollProxy: ScrollViewProxy?

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
        Button {
            // Phase 175: stub — Phase 196 (UI Automation) wires PhotosPicker / file picker
            Logger.ui.info("Attach button tapped — picker wires in Phase 196")
        } label: {
            Image(systemName: "paperclip")
                .font(Typography.body)
                .foregroundStyle(ColorTokens.secondaryText)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Attach reference image")
        .accessibilityHint("Opens picker for reference schematics or photos")
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

        // Kick off streaming.
        streamingTask?.cancel()
        streamingTask = Task { [streamProvider] in
            do {
                for try await chunk in streamProvider.stream(prompt: trimmed, attachments: promptAttachments) {
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
