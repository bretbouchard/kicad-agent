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
                }
                .padding(Spacing.lg)
            }
            .onAppear { scrollProxy = proxy }
            .onChange(of: messages.count) { _, _ in
                if let lastId = messages.last?.id {
                    withAnimation { proxy.scrollTo(lastId, anchor: .bottom) }
                }
            }
        }
        .accessibilityLabel("Conversation messages")
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
                for try await token in streamProvider.stream(prompt: trimmed, attachments: promptAttachments) {
                    try Task.checkCancellation()
                    await MainActor.run {
                        guard let idx = messages.firstIndex(where: { $0.id == assistantId }) else { return }
                        messages[idx].content += token
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
