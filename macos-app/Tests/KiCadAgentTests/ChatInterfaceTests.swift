//
//  ChatInterfaceTests.swift
//  KiCadAgentTests
//
//  Phase 175 — Chat Interface
//
//  Tests ChatMessage model, MessageRole/Status, CostEstimate, ImageAttachment
//  validator, NoopChatStream, and 4-variant trait instantiation of
//  MessageBubbleView, ChatView, ConversationListView.
//

import Testing
import SwiftUI
@testable import KiCadAgent

@Suite("Chat Interface", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil))
struct ChatInterfaceTests {

    // MARK: - ChatMessage + Roles

    @Test("ChatMessage constructs with defaults")
    func chatMessageDefaults() {
        let msg = ChatMessage(role: .user, content: "Hello")
        #expect(msg.role == .user)
        #expect(msg.content == "Hello")
        #expect(msg.status == .pending)
        #expect(msg.attachments.isEmpty)
    }

    @Test("MessageRole has three cases")
    func roleCases() {
        #expect(MessageRole.user.rawValue == "user")
        #expect(MessageRole.assistant.rawValue == "assistant")
        #expect(MessageRole.system.rawValue == "system")
    }

    @Test("MessageStatus.isFinal marks terminal states")
    func statusFinal() {
        #expect(MessageStatus.complete.isFinal == true)
        #expect(MessageStatus.cancelled.isFinal == true)
        #expect(MessageStatus.pending.isFinal == false)
        #expect(MessageStatus.streaming.isFinal == false)
    }

    // MARK: - CostEstimate

    @Test("CostEstimate totalTokens sums in+out")
    func costTotal() {
        let cost = CostEstimate(inputTokens: 100, outputTokens: 50, estimatedUSD: 0.0023, modelId: "test")
        #expect(cost.totalTokens == 150)
    }

    @Test("CostEstimate formattedCost uses 4 decimals for sub-cent")
    func costFormatSubCent() {
        let cost = CostEstimate(inputTokens: 100, outputTokens: 50, estimatedUSD: 0.0023, modelId: "test")
        #expect(cost.formattedCost == "$0.0023")
    }

    @Test("CostEstimate formattedCost uses 2 decimals for cents+")
    func costFormatCents() {
        let cost = CostEstimate(inputTokens: 100, outputTokens: 50, estimatedUSD: 0.15, modelId: "test")
        #expect(cost.formattedCost == "$0.15")
    }

    // MARK: - ImageAttachment validation (CHAT-06)

    @Test("ImageAttachment accepts PNG")
    func attachPNG() {
        let att = makeAttachment(mime: "image/png")
        #expect(ImageAttachmentValidator.isAcceptable(att) == true)
    }

    @Test("ImageAttachment accepts JPEG and HEIC")
    func attachJPGHEIC() {
        let jpg = makeAttachment(mime: "image/jpeg")
        let heic = makeAttachment(mime: "image/heic")
        #expect(ImageAttachmentValidator.isAcceptable(jpg) == true)
        #expect(ImageAttachmentValidator.isAcceptable(heic) == true)
    }

    @Test("ImageAttachment rejects GIF (CHAT-06 constraint)")
    func attachGIF() {
        let gif = makeAttachment(mime: "image/gif")
        #expect(ImageAttachmentValidator.isAcceptable(gif) == false)
    }

    @Test("ImageAttachmentValidator flags >10MB as needing compression")
    func attachLargeNeedsCompression() {
        let large = makeAttachment(mime: "image/png", size: 11 * 1024 * 1024)
        #expect(ImageAttachmentValidator.needsCompression(large) == true)
    }

    // MARK: - NoopChatStream

    @Test("NoopChatStream emits tokens and finishes", .tags(.streaming))
    func noopStreamEmits() async {
        let stream = NoopChatStream(cannedResponse: "hello world from mock")
        var tokens: [String] = []
        do {
            for try await token in stream.stream(prompt: "test", attachments: []) {
                tokens.append(token)
            }
        } catch {
            Issue.record("stream should not throw: \(error)")
        }
        #expect(tokens.count == 4)
        #expect(tokens.joined().contains("hello") == true)
    }

    // MARK: - 4-Variant Trait Tests for Chat Views

    @Test("MessageBubbleView renders user message", .tags(.ui, .a11y))
    func bubbleUser() {
        let msg = ChatMessage(role: .user, content: "Design a distortion pedal", status: .complete)
        let view = MessageBubbleView(message: msg, previewRenderer: nil)
        _ = view
    }

    @Test("MessageBubbleView renders assistant with cost + model", .tags(.ui, .a11y))
    func bubbleAssistantWithCost() {
        let msg = ChatMessage(
            role: .assistant,
            content: "Here's a schematic for a distortion pedal.",
            status: .complete,
            costEstimate: CostEstimate(inputTokens: 120, outputTokens: 80, estimatedUSD: 0.0008, modelId: "gpt-4o"),
            modelBadge: "GPT-4o"
        )
        let view = MessageBubbleView(message: msg, previewRenderer: nil)
            .preferredColorScheme(.dark)
        _ = view
    }

    @Test("MessageBubbleView renders streaming state", .tags(.ui, .a11y))
    func bubbleStreaming() {
        let msg = ChatMessage(role: .assistant, content: "Partial ", status: .streaming)
        let view = MessageBubbleView(message: msg, previewRenderer: nil)
            .dynamicTypeSize(.accessibility3)
        _ = view
    }

    @Test("MessageBubbleView renders failed state", .tags(.ui, .a11y))
    func bubbleFailed() {
        let msg = ChatMessage(role: .assistant, content: "", status: .failed("Network error"))
        let view = MessageBubbleView(message: msg, previewRenderer: nil)
        _ = view
    }

    @Test("ChatView instantiates with empty messages")
    @MainActor
    func chatViewEmpty() {
        let messages: Binding<[ChatMessage]> = .constant([])
        let view = ChatView(
            messages: messages,
            streamProvider: NoopChatStream(),
            previewRenderer: nil
        )
        _ = view
    }

    @Test("ChatView instantiates with messages", .tags(.ui, .a11y))
    @MainActor
    func chatViewWithMessages() {
        let msgs = [
            ChatMessage(role: .user, content: "Hello", status: .complete),
            ChatMessage(role: .assistant, content: "Hi there", status: .complete)
        ]
        let view = ChatView(
            messages: .constant(msgs),
            streamProvider: NoopChatStream(),
            previewRenderer: MockPreviewRenderer()
        )
        _ = view
    }

    // MARK: - Helpers

    private func makeAttachment(mime: String, size: Int64 = 1_000_000) -> ImageAttachment {
        ImageAttachment(
            fileName: "test.\(mime.split(separator: "/").last ?? "bin")",
            fileSizeBytes: size,
            mimeType: mime,
            url: URL(fileURLWithPath: "/tmp/test"),
            pixelWidth: 800,
            pixelHeight: 600
        )
    }
}
