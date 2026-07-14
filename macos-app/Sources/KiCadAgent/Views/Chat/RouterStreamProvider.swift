//
//  RouterStreamProvider.swift
//  KiCadAgent
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
//

import Foundation

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
struct RouterStreamProvider: ChatStreamProvider {
    let router: KiCadModelRouter

    /// Called with the final usage stats when streaming completes.
    /// The view uses this to persist token counts + cost to SwiftData.
    var onUsage: (@Sendable (KCUsage) -> Void)?

    /// Maximum characters to buffer before forcing a flush. Prevents a
    /// chatty model from holding text hostage in a single growing block.
    /// Sized to ~2-3 sentences of typical English prose.
    var maxBufferChars: Int = 240

    func stream(prompt: String, attachments: [ImageAttachment]) -> AsyncThrowingStream<String, Error> {
        let router = router
        let usageCallback = onUsage
        let maxBuffer = maxBufferChars

        return AsyncThrowingStream { continuation in
            Task { @MainActor in
                do {
                    let kcPrompt = KCPrompt.user(prompt)
                    let tokenStream = try await router.generate(from: kcPrompt)

                    var buffer = ""

                    func flush(force: Bool = false) {
                        guard !buffer.isEmpty else { return }
                        // Flush if we hit a natural boundary or the buffer
                        // grew too long without a boundary (chatty model).
                        if force || shouldFlush(buffer: buffer, max: maxBuffer) {
                            continuation.yield(buffer)
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
