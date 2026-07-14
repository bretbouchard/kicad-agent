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

    // MARK: - ContentChunker (paragraph chunking for readable streaming)

    @Test("ContentChunker splits on double newlines")
    func chunkerDoubleNewlines() {
        let chunks = ContentChunker.chunk("Para one.\n\nPara two.\n\nPara three.", isStreaming: false)
        #expect(chunks.count == 3)
        #expect(chunks[0].text == "Para one.")
        #expect(chunks[1].text == "Para two.")
        #expect(chunks[2].text == "Para three.")
        #expect(chunks.allSatisfy { !$0.isPartial })
    }

    @Test("ContentChunker splits oversized paragraph on sentence boundaries")
    func chunkerOversizedParagraph() {
        // Build a paragraph > maxChunkChars with multiple *distinct* sentences.
        // (If we used repeated sentences, the dedup pass would collapse them
        // into a single chunk — which is correct behavior, but it would
        // defeat the point of testing sentence-level splitting.)
        let sentences = (1...20).map { "Sentence number \($0) explains a concept." }
        let para = sentences.joined(separator: " ")
        #expect(para.count > ContentChunker.maxChunkChars)
        let chunks = ContentChunker.chunk(para, isStreaming: false)
        #expect(chunks.count > 1, "expected oversized paragraph to be split")
        #expect(chunks.allSatisfy { !$0.text.isEmpty })
        // Reconstructed text should preserve sentence content.
        let rejoined = chunks.map(\.text).joined(separator: " ")
        #expect(rejoined.contains("explains a concept"))
    }

    @Test("ContentChunker marks last chunk as partial while streaming")
    func chunkerPartialLast() {
        let chunks = ContentChunker.chunk("Para one.\n\nPara two.", isStreaming: true)
        #expect(chunks.count == 2)
        #expect(chunks[0].isPartial == false)
        #expect(chunks[1].isPartial == true)
    }

    @Test("ContentChunker does not mark anything partial when done")
    func chunkerCompleteNotPartial() {
        let chunks = ContentChunker.chunk("Single paragraph.", isStreaming: false)
        #expect(chunks.count == 1)
        #expect(chunks[0].isPartial == false)
    }

    @Test("ContentChunker handles empty content")
    func chunkerEmpty() {
        #expect(ContentChunker.chunk("", isStreaming: false).isEmpty)
        #expect(ContentChunker.chunk("   \n\n  ", isStreaming: false).isEmpty)
    }

    @Test("ContentChunker handles single sentence")
    func chunkerSingleSentence() {
        let chunks = ContentChunker.chunk("Just one short thought.", isStreaming: false)
        #expect(chunks.count == 1)
        #expect(chunks[0].text == "Just one short thought.")
    }

    @Test("ContentChunker collapses consecutive identical chunks with repetition marker")
    func chunkerCollapsesRepeatedChunks() {
        // Phase 220+: the local MLX model commonly loops on short prompts,
        // producing N copies of the same sentence. The chunker must surface
        // this as ONE visible block with a "(repeated N×)" marker so the
        // chat stays scannable instead of showing 12 identical stacked
        // blocks. The user can still see the loop happened via the count.
        let looped = String(repeating: "Designing a distortion pedal. ", count: 12)
        let chunks = ContentChunker.chunk(looped, isStreaming: false)
        #expect(chunks.count == 1,
                "consecutive identical chunks must be collapsed into one")
        #expect(chunks[0].text.contains("Designing a distortion pedal."))
        #expect(chunks[0].text.contains("(repeated 12×)"),
                "collapsed chunk should annotate the repetition count")
    }

    @Test("ContentChunker does not annotate non-repeating content")
    func chunkerLeavesNonRepeatingAlone() {
        // Regression: dedup must not affect normal multi-paragraph output.
        // Each paragraph is unique, so no "(repeated N×)" marker should appear.
        let content = "First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here."
        let chunks = ContentChunker.chunk(content, isStreaming: false)
        #expect(chunks.count == 3)
        for chunk in chunks {
            #expect(!chunk.text.contains("(repeated"),
                    "non-repeating chunks must not be annotated with a repetition marker")
        }
    }

    @Test("ContentChunker preserves partial flag on a collapsed run while streaming")
    func chunkerCollapsedRunStaysPartial() {
        // When the model is still streaming and a run is the tail of the
        // output, the deduped chunk must remain partial so the view still
        // shows the streaming caret.
        let looped = String(repeating: "Designing a distortion pedal. ", count: 4)
        let chunks = ContentChunker.chunk(looped, isStreaming: true)
        #expect(chunks.count == 1)
        #expect(chunks[0].isPartial == true)
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
