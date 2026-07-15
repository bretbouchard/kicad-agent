//
//  RouterStreamProvider.swift
//  Volta
//
//  Phase 211 — Chat → Router → Stream Pipeline
//
//  Bridges KiCadModelRouter to the ChatStreamProvider protocol.
//  The router returns AsyncThrowingStream<KCToken, Error>; ChatView
//  wants AsyncThrowingStream<String, Error>. This adapter:
//    1. Maps .text tokens to String
//    2. Drops .usage/.done/.toolCall tokens
//    3. Buffers tokens and flushes on sentence/paragraph boundaries
//       so the view receives coherent chunks instead of one growing blob
//    4. Strips echoed user input from the head of the first chunk
//       (local MLX models commonly repeat the user's prompt as the
//        opening of the response — visually noisy and confusing)
//

import Foundation
import OSLog

/// Production ChatStreamProvider backed by KiCadModelRouter.
///
/// Wraps the router's `generate(from:)` call and extracts text tokens
/// for the chat UI. Cost/usage metadata is available via the closure
/// callback after streaming completes.
///
/// **Chunking strategy:** tokens are buffered and flushed at natural
/// sentence/paragraph boundaries (`. `, `? `, `! `, `\n\n`, `\n`). This
/// gives the user coherent readable chunks instead of one continuously
/// growing string that becomes unreadable when the model loops. The
/// final partial chunk is flushed on stream end.
///
/// **Echo stripping:** the first emitted chunk is compared to the
/// most recent user message; if the chunk starts with the user's
/// text (a common local-model artifact), the prefix is dropped so
/// the chat doesn't visually duplicate the question into the answer.
struct RouterStreamProvider: ChatStreamProvider {
    let router: KiCadModelRouter

    /// Called with the final usage stats when streaming completes.
    /// The view uses this to persist token counts + cost to SwiftData.
    var onUsage: (@Sendable (KCUsage) -> Void)?

    /// Maximum characters to buffer before forcing a flush. Prevents a
    /// chatty model from holding text hostage in a single growing block.
    /// Sized to ~2-3 sentences of typical English prose.
    var maxBufferChars: Int = 240

    func stream(history: [ChatMessage], attachments: [ImageAttachment]) -> AsyncThrowingStream<String, Error> {
        let router = router
        let usageCallback = onUsage
        let maxBuffer = maxBufferChars

        return AsyncThrowingStream { continuation in
            Task { @MainActor in
                do {
                    let kcPrompt = Self.buildKCPrompt(history: history, attachments: attachments)
                    let tokenStream = try await router.generate(from: kcPrompt)

                    var buffer = ""
                    // Track whether we've emitted anything yet — echo
                    // stripping only applies to the FIRST chunk, since
                    // by the second chunk the model is past any opener
                    // echo and continuing its real response.
                    var hasEmitted = false
                    // The user's last message text — used to detect a
                    // model echo at the start of the response.
                    let lastUserText = history.last(where: { $0.role == .user })?.content ?? ""

                    func flush(force: Bool = false) {
                        guard !buffer.isEmpty else { return }
                        // Flush if we hit a natural boundary or the buffer
                        // grew too long without a boundary (chatty model).
                        if force || shouldFlush(buffer: buffer, max: maxBuffer) {
                            var chunk = buffer
                            if !hasEmitted {
                                chunk = Self.stripEcho(chunk, userPrompt: lastUserText)
                                hasEmitted = true
                            }
                            if !chunk.isEmpty {
                                continuation.yield(chunk)
                            }
                            buffer.removeAll(keepingCapacity: true)
                        }
                    }

                    for try await token in tokenStream {
                        switch token {
                        case .text(let text):
                            buffer.append(text)
                            flush(force: false)
                        case .usage(let usage):
                            usageCallback?(usage)
                        case .done:
                            flush(force: true)
                            break
                        case .toolCall:
                            break
                        }
                    }
                    flush(force: true)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    // MARK: - Helpers

    /// Build a `KCPrompt` from a full conversation history. Each
    /// `ChatMessage` becomes a `KCMessage` in the prompt envelope so
    /// providers that natively support multi-turn (MLX, OpenAI, Anthropic)
    /// get the full context, and providers that flatten to a single
    /// string (AppleLocal) at least see the prior assistant turns
    /// prefixed with "Assistant:".
    ///
    /// Image attachments from the chat UI are bridged into `KCAttachment`
    /// here (Phase 239). We read the file bytes off the `ImageAttachment.url`
    /// synchronously — by the time the user hits send, the picker / drop
    /// / paste pipeline has already produced a stable URL on disk. If a
    /// read fails, we log and skip that attachment so a single bad file
    /// doesn't poison the whole send. The compressed image (when
    /// `compressIfNeeded` ran in the picker) is what we send — it's
    /// already a small JPEG on a temp URL.
    static func buildKCPrompt(history: [ChatMessage], attachments: [ImageAttachment]) -> KCPrompt {
        let messages: [KCMessage] = history
            .filter { $0.role != .system }
            .map { msg in
                let role: KCRole = (msg.role == .user) ? .user : .assistant
                return KCMessage(role: role, content: msg.content)
            }
        let kcAttachments = attachments.compactMap(makeKCAttachment)
        return KCPrompt(messages: messages, attachments: kcAttachments)
    }

    /// Read an ImageAttachment's file bytes and wrap them in a
    /// KCAttachment. Returns nil on read failure (with a log entry)
    /// so a single bad file doesn't kill the whole stream.
    private static func makeKCAttachment(from image: ImageAttachment) -> KCAttachment? {
        guard let data = try? Data(contentsOf: image.url) else {
            Logger.stream.error(
                "Attachment read failed: \(image.url.path, privacy: .public)"
            )
            return nil
        }
        return KCAttachment(data: data, mimeType: image.mimeType)
    }

    /// Strip a leading user-input echo from the assistant's first chunk.
    /// Local models (especially small MLX GGMU/Gemma) often open their
    /// response by repeating the user's question verbatim. If the chunk
    /// starts with the user's text (allowing for an optional leading
    /// newline, or trailing punctuation the model may have added), trim it.
    /// Returns the chunk unchanged if no echo is detected.
    static func stripEcho(_ chunk: String, userPrompt: String) -> String {
        let trimmedPrompt = userPrompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedPrompt.isEmpty else { return chunk }
        let normalized = chunk.trimmingCharacters(in: .whitespacesAndNewlines)
        // Exact match — entire chunk is the echo.
        if normalized.caseInsensitiveCompare(trimmedPrompt) == .orderedSame {
            return ""
        }
        // Prefix match (case-insensitive, allowing for a trailing
        // punctuation/whitespace the model may have appended).
        if normalized.lowercased().hasPrefix(trimmedPrompt.lowercased()) {
            let tail = normalized.dropFirst(trimmedPrompt.count)
            return String(tail).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        // The model sometimes repeats the question with a leading newline
        // inside the chunk — try the first line in isolation.
        if let firstLine = normalized.split(separator: "\n", maxSplits: 1, omittingEmptySubsequences: true).first,
           firstLine.lowercased() == trimmedPrompt.lowercased() {
            let remainder = normalized
                .dropFirst(firstLine.count)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return remainder
        }
        return chunk
    }

    /// True when the buffer ends at a natural break point (sentence or
    /// paragraph) — emitting now gives the user a coherent chunk to read
    /// without waiting for the next token. Also true when the buffer is
    /// unreasonably long with no boundary in sight.
    private func shouldFlush(buffer: String, max: Int) -> Bool {
        // Paragraph break — strongest signal.
        if buffer.hasSuffix("\n\n") { return true }
        // Sentence terminators followed by whitespace.
        let sentenceEnders: [String] = [". ", "? ", "! ", ".\n", "?\n", "!\n"]
        for ender in sentenceEnders where buffer.hasSuffix(ender) {
            return true
        }
        // Last-resort: buffer grew too long without a boundary.
        if buffer.count >= max { return true }
        return false
    }
}
