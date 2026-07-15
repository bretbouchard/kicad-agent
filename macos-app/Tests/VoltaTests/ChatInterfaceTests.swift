//
//  ChatInterfaceTests.swift
//  VoltaTests
//
//  Phase 175 — Chat Interface
//
//  Tests ChatMessage model, MessageRole/Status, CostEstimate, ImageAttachment
//  validator, NoopChatStream, and 4-variant trait instantiation of
//  MessageBubbleView, ChatView, ConversationListView.
//

import Testing
import SwiftUI
@testable import Volta

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
            let history = [
                ChatMessage(role: .user, content: "test")
            ]
            for try await token in stream.stream(history: history, attachments: []) {
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

    // MARK: - Intra-chunk loop detection (Phase 220+)
    //
    // Local MLX models commonly loop on a single sentence INSIDE one
    // emitted chunk (e.g. "X. X. X. X. X. X." as a single streamed
    // paragraph). The previous dedup only collapsed across separate
    // chunks; intra-chunk loops slipped through and produced a wall of
    // repeated text inside one rendered block. collapseIntraChunkLoop
    // catches this.

    @Test("ContentChunker collapses repeated sentence inside a single chunk")
    func chunkerCollapsesIntraChunkLoop() {
        let looped = String(repeating: "Designing a distortion pedal. ", count: 8)
        let chunks = ContentChunker.chunk(looped, isStreaming: false)
        #expect(chunks.count == 1)
        #expect(chunks[0].text.contains("(×8)"),
                "intra-chunk loop must be collapsed with a repetition marker")
        #expect(chunks[0].text.contains("Designing a distortion pedal"))
    }

    @Test("ContentChunker does not collapse short repeats (below threshold)")
    func chunkerLeavesShortRepeatsAlone() {
        // Two copies is normal repetition (e.g. "Yes. Yes you can.").
        // The dedup threshold is 3, so 2 copies should be left alone.
        let text = "Yes. Yes that is right."
        let chunks = ContentChunker.chunk(text, isStreaming: false)
        #expect(chunks.count == 1)
        #expect(!chunks[0].text.contains("(×"),
                "two-sentence repeat must not be collapsed")
    }

    @Test("ContentChunker preserves unique tail after intra-chunk loop")
    func chunkerPreservesTailAfterLoop() {
        // 3 copies of "Designing a distortion pedal." followed by a
        // distinct final sentence. The loop should be collapsed but the
        // tail preserved.
        let text = String(repeating: "Designing a distortion pedal. ", count: 3)
            + "Now let me know your target gain."
        let chunks = ContentChunker.chunk(text, isStreaming: false)
        #expect(chunks.count == 1)
        #expect(chunks[0].text.contains("(×3)"))
        #expect(chunks[0].text.contains("target gain"),
                "unique tail after a loop must not be dropped")
    }

    @Test("ContentChunker loop fingerprint is case-insensitive")
    func chunkerLoopCaseInsensitive() {
        // Model emits the same sentence with mixed casing — still a loop.
        let text = "Designing a distortion pedal. designing a distortion pedal. DESIGNING A DISTORTION PEDAL. Designing a distortion pedal."
        let chunks = ContentChunker.chunk(text, isStreaming: false)
        #expect(chunks.count == 1)
        #expect(chunks[0].text.contains("(×4)"),
                "case-variant repeats must still be recognized as a loop")
    }

    // MARK: - RouterStreamProvider.stripEcho (Phase 220+)
    //
    // Local MLX models frequently open their response by echoing the
    // user's question verbatim. The first chunk of the stream is checked
    // against the most recent user message; a leading echo is stripped
    // so the chat doesn't visually duplicate the question into the
    // answer.

    @Test("stripEcho drops exact-match echo of the user prompt")
    func stripEchoExactMatch() {
        let result = RouterStreamProvider.stripEcho(
            "What gain do you want for the pedal?",
            userPrompt: "What gain do you want for the pedal?"
        )
        #expect(result.isEmpty,
                "when the chunk is entirely the echo, the result must be empty")
    }

    @Test("stripEcho drops echo prefix and keeps real answer")
    func stripEchoPrefixOnly() {
        let result = RouterStreamProvider.stripEcho(
            "What gain do you want for the pedal? You probably want 20dB for a Tube Screamer.",
            userPrompt: "What gain do you want for the pedal?"
        )
        #expect(result.contains("You probably want 20dB"))
        #expect(!result.lowercased().contains("what gain do you want"),
                "echo prefix must be removed")
    }

    @Test("stripEcho is case-insensitive")
    func stripEchoCaseInsensitive() {
        let result = RouterStreamProvider.stripEcho(
            "WHAT GAIN DO YOU WANT FOR THE PEDAL? Try 20dB.",
            userPrompt: "what gain do you want for the pedal?"
        )
        #expect(result.contains("Try 20dB"))
    }

    @Test("stripEcho leaves unrelated content alone")
    func stripEchoLeavesUnrelatedAlone() {
        let result = RouterStreamProvider.stripEcho(
            "A good starting point is 20dB of gain.",
            userPrompt: "What gain do you want for the pedal?"
        )
        #expect(result == "A good starting point is 20dB of gain.",
                "chunk that doesn't start with the echo must be returned unchanged")
    }

    @Test("stripEcho handles empty user prompt gracefully")
    func stripEchoEmptyUserPrompt() {
        let result = RouterStreamProvider.stripEcho("Just an answer.", userPrompt: "")
        #expect(result == "Just an answer.",
                "empty user prompt must not trigger echo stripping")
    }

    // MARK: - KCTaskPromptFormatter.generalSystemPrompt
    //
    // The system prompt drives the model's behavior. It must instruct
    // the model to ask clarifying questions for vague prompts rather
    // than emit a generic "this is complex" disclaimer.

    @Test("generalSystemPrompt instructs the model to ask clarifying questions")
    func generalSystemPromptAsksClarifyingQuestions() {
        #expect(KCTaskPromptFormatter.generalSystemPrompt.contains("clarifying"),
                "general system prompt must mention clarifying questions")
        #expect(KCTaskPromptFormatter.generalSystemPrompt.contains("echo") ||
                KCTaskPromptFormatter.generalSystemPrompt.contains("restate"),
                "general system prompt must explicitly forbid echoing/restating the question")
    }

    // MARK: - ConversationExporter
    //
    // Phase 220+: the user pastes chat history into bug reports, design
    // docs, and emails. The exporter formats the full conversation as
    // self-describing plain text. We test the pure function (not the
    // clipboard write, which is @MainActor and side-effecting).

    @Test("ConversationExporter formats user and assistant turns with labels")
    func exporterFormatsBothRoles() {
        let messages = [
            ChatMessage(role: .user, content: "Design a 20dB gain stage.", status: .complete),
            ChatMessage(role: .assistant, content: "Use a non-inverting op-amp.", status: .complete, modelBadge: "gemma-4-12b-it-mlx-q4")
        ]
        let text = ConversationExporter.plainText(messages: messages)
        #expect(text.contains("Volta PCB Conversation Export"))
        #expect(text.contains("User:"))
        #expect(text.contains("Assistant (gemma-4-12b-it-mlx-q4):"))
        #expect(text.contains("Design a 20dB gain stage."))
        #expect(text.contains("Use a non-inverting op-amp."))
    }

    @Test("ConversationExporter falls back to bare Assistant label when no model badge")
    func exporterBareAssistantLabel() {
        let messages = [
            ChatMessage(role: .assistant, content: "An answer.", status: .complete)
        ]
        let text = ConversationExporter.plainText(messages: messages)
        #expect(text.contains("Assistant:"), "no model badge should fall back to plain 'Assistant:'")
        #expect(!text.contains("Assistant ()"), "must not emit an empty '()' after the label")
    }

    @Test("ConversationExporter labels system messages explicitly")
    func exporterLabelsSystem() {
        let messages = [
            ChatMessage(role: .system, content: "ERC check passed.", status: .complete)
        ]
        let text = ConversationExporter.plainText(messages: messages)
        #expect(text.contains("System:"))
    }

    @Test("ConversationExporter skips empty messages")
    func exporterSkipsEmpty() {
        let messages = [
            ChatMessage(role: .user, content: "", status: .complete),
            ChatMessage(role: .user, content: "Real question.", status: .complete)
        ]
        let text = ConversationExporter.plainText(messages: messages)
        #expect(text.contains("Real question."))
        // The empty content should not produce a stray "User:" header
        // with nothing under it.
        let userHeaders = text.components(separatedBy: "User:\n").count - 1
        #expect(userHeaders == 1, "expected exactly one User: header, got \(userHeaders)")
    }

    @Test("ConversationExporter skips streaming and cancelled messages")
    func exporterSkipsInFlightAndCancelled() {
        let messages = [
            ChatMessage(role: .user, content: "Already done.", status: .complete),
            ChatMessage(role: .assistant, content: "Half-written response", status: .streaming),
            ChatMessage(role: .assistant, content: "Cancelled mid-stream", status: .cancelled),
            ChatMessage(role: .user, content: "Also done.", status: .complete)
        ]
        let text = ConversationExporter.plainText(messages: messages)
        #expect(text.contains("Already done."))
        #expect(text.contains("Also done."))
        #expect(!text.contains("Half-written response"),
                "streaming content must not be exported")
        #expect(!text.contains("Cancelled mid-stream"),
                "cancelled content must not be exported")
    }

    @Test("ConversationExporter includes failed messages (errors are exportable context)")
    func exporterIncludesFailed() {
        let messages = [
            ChatMessage(
                role: .assistant,
                content: "Provider error: rate limited",
                status: .failed("429 Too Many Requests")
            )
        ]
        let text = ConversationExporter.plainText(messages: messages)
        #expect(text.contains("Provider error: rate limited"),
                "failed messages are part of the session record and must be exported")
    }

    @Test("ConversationExporter output ends with a single trailing newline")
    func exporterTrailingNewline() {
        let text = ConversationExporter.plainText(messages: [
            ChatMessage(role: .user, content: "Hi.", status: .complete)
        ])
        #expect(text.hasSuffix("\n"))
        #expect(!text.hasSuffix("\n\n"),
                "exactly one trailing newline; not two")
    }

    @Test("ConversationExporter handles empty input gracefully")
    func exporterEmptyInput() {
        let text = ConversationExporter.plainText(messages: [])
        #expect(text.contains("Volta PCB Conversation Export"),
                "header should still be present for empty input so the paste is self-describing")
    }

    @Test("ConversationExporter separates turns with a blank line")
    func exporterBlankLineBetweenTurns() {
        let messages = [
            ChatMessage(role: .user, content: "First.", status: .complete),
            ChatMessage(role: .assistant, content: "Second.", status: .complete)
        ]
        let text = ConversationExporter.plainText(messages: messages)
        // Each turn block ends with a newline; the separator adds a
        // second newline before the next "[" header. Check the gap.
        #expect(text.contains("First.\n\n["),
                "expected a blank line between turns")
        #expect(text.contains("Second.\n"),
                "last turn must end with exactly one newline")
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
