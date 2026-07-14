//
//  MessageBubbleView.swift
//  KiCadAgent
//
//  Phase 175 — Chat Interface
//
//  Renders a single chat message — user or assistant. Handles streaming
//  state, attachments, cost badges, and inline render artifacts.
//
//  CHAT-02: streaming
//  CHAT-06: attachments
//  CHAT-07: cost tracking
//
//  CHUNKING: The streamed message body is split into paragraph-sized
//  blocks (separated by `\n\n` or sentence boundaries) and rendered as
//  distinct visual chunks. This keeps long responses scannable instead
//  of presenting one continuously growing blob, and survives model
//  loops gracefully — each looped phrase becomes its own chunk with a
//  visible separator rather than a wall of repeated text.
//

import SwiftUI

/// Single message bubble.
struct MessageBubbleView: View {
    let message: ChatMessage
    let previewRenderer: PreviewRenderer?

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 40) }
            bubbleContent
            if message.role == .assistant { Spacer(minLength: 40) }
        }
    }

    private var bubbleContent: some View {
        VStack(alignment: message.role == .user ? .trailing : .leading, spacing: Spacing.xs) {
            // Authorship + model badge
            if message.role == .assistant, let badge = message.modelBadge {
                HStack(spacing: Spacing.xxs) {
                    Image(systemName: "sparkles")
                        .font(Typography.caption.weight(.semibold))
                    Text(badge)
                        .font(Typography.caption.weight(.semibold))
                }
                .foregroundStyle(ColorTokens.secondaryText)
                .accessibilityLabel("Assistant message via \(badge)")
            }

            // Attachments row (above text)
            if !message.attachments.isEmpty {
                attachmentsRow
            }

            // Main content — chunked into paragraph blocks
            if message.content.isEmpty && message.status == .streaming {
                typingIndicator
            } else {
                chunkedContent
            }

            // Inline render artifact (if present)
            if let artifact = message.renderArtifact {
                inlineArtifact(artifact)
            }

            // Cost + status row
            footer
        }
        .padding(Spacing.md)
        .frame(maxWidth: 640, alignment: message.role == .user ? .trailing : .leading)
        .background(bubbleBackground, in: bubbleShape)
        .accessibilityElement(children: .contain)
    }

    /// Render the message body as a vertical stack of chunk cards.
    /// Each chunk is a paragraph (split on `\n\n`) or, if no paragraph
    /// break is present, a sequence of sentence-sized fragments — so the
    /// user always sees readable pieces instead of a single blob.
    private var chunkedContent: some View {
        let chunks = ContentChunker.chunk(
            message.content,
            isStreaming: message.status == .streaming
        )
        return VStack(alignment: .leading, spacing: Spacing.xs) {
            ForEach(chunks) { chunk in
                chunkBlock(chunk)
            }
            // If the model is still streaming and the last chunk is short
            // (no terminator yet), show a soft caret so the user knows
            // more is coming.
            if message.status == .streaming, let last = chunks.last,
               !last.text.hasSuffix("\n") {
                caret
                    .padding(.leading, Spacing.xxs)
            }
        }
    }

    private func chunkBlock(_ chunk: ContentChunker.Chunk) -> some View {
        Text(chunk.text)
            .font(Typography.body)
            .foregroundStyle(Color.primary)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, Spacing.xxs)
            .accessibilityLabel("\(message.role.rawValue) message")
    }

    private var caret: some View {
        Text("▍")
            .font(Typography.body.weight(.semibold))
            .foregroundStyle(ColorTokens.tertiaryText)
            .accessibilityHidden(true)
    }

    private var attachmentsRow: some View {
        HStack(spacing: Spacing.xs) {
            ForEach(message.attachments) { attachment in
                ImageAttachmentView(attachment: attachment)
                    .frame(width: 60, height: 60)
            }
        }
    }

    private var typingIndicator: some View {
        HStack(spacing: Spacing.xxs) {
            ForEach(0..<3) { idx in
                Circle()
                    .fill(ColorTokens.tertiaryText)
                    .frame(width: 6, height: 6)
                    .opacity(0.6)
            }
        }
        .padding(Spacing.xs)
        .accessibilityLabel("Assistant is typing")
    }

    @ViewBuilder
    private func inlineArtifact(_ artifact: RenderArtifact) -> some View {
        if let renderer = previewRenderer {
            switch artifact.kind {
            case .schematicSVG:
                SchematicPreviewView(schematicPath: artifact.url, renderer: renderer)
            case .pcbPNG:
                PCBPreviewView(pcbPath: artifact.url, side: .front, renderer: renderer)
            }
        }
    }

    private var footer: some View {
        HStack(spacing: Spacing.xs) {
            if message.status == .streaming {
                ProgressView().controlSize(.mini)
                Text("Streaming…")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            } else if case .failed(let reason) = message.status {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(ColorTokens.destructive)
                Text(reason)
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.destructive)
            } else if case .cancelled = message.status {
                Text("Cancelled")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
            if let cost = message.costEstimate {
                Spacer(minLength: Spacing.sm)
                Text("\(cost.totalTokens) tok · \(cost.formattedCost)")
                    .font(Typography.caption.monospacedDigit())
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
        }
    }

    private var bubbleBackground: Color {
        switch message.role {
        case .user: return Color.accentColor.opacity(0.12)
        case .assistant: return Color(nsColor: .controlBackgroundColor)
        case .system: return ColorTokens.warning.opacity(0.12)
        }
    }

    private var bubbleShape: some Shape {
        RoundedRectangle(cornerRadius: CornerRadius.large, style: .continuous)
    }
}

// MARK: - ContentChunker

/// Splits a streamed message body into display-ready chunks.
///
/// Why this exists: the streaming provider already flushes on sentence
/// boundaries, but the model can still emit a long unbroken paragraph
/// (especially when it loops or doesn't add explicit paragraph breaks).
/// This chunker guarantees the view always receives multiple scannable
/// blocks — never a single 2,000-character wall of text.
///
/// Strategy:
/// 1. Split on `\n\n` first — those are real paragraph breaks.
/// 2. For each non-empty paragraph, if it exceeds `maxChunkChars`,
///    split on sentence boundaries (`. `, `? `, `! `).
/// 3. While streaming, the last chunk is marked partial so the view
///    can show a caret to signal "more coming".
/// 4. **Dedup:** runs of identical consecutive chunks are collapsed
///    into a single chunk with a "(×N)" annotation. Local MLX models
///    commonly loop on short prompts — without this, a 12x repetition
///    would render as 12 visually-identical stacked blocks. The user
///    still sees the loop happened (via the count), but the chat stays
///    scannable.
enum ContentChunker {
    /// Target maximum characters per rendered chunk. Tuned to ~2 short
    /// paragraphs of typical chat output — long enough to be coherent,
    /// short enough to scan.
    static let maxChunkChars = 320

    struct Chunk: Identifiable, Equatable {
        let id: Int
        let text: String
        let isPartial: Bool

        init(id: Int, text: String, isPartial: Bool = false) {
            self.id = id
            self.text = text
            self.isPartial = isPartial
        }
    }

    /// Split a message body into chunks. Empty input returns an empty
    /// array (the view falls back to its typing indicator).
    static func chunk(_ content: String, isStreaming: Bool) -> [Chunk] {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }

        // First pass: real paragraph breaks.
        let paragraphs = trimmed
            .components(separatedBy: "\n\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        // Second pass: split oversized paragraphs on sentence boundaries.
        var expanded: [String] = []
        for para in paragraphs {
            if para.count <= maxChunkChars {
                expanded.append(para)
            } else {
                expanded.append(contentsOf: splitSentences(para))
            }
        }

        // If splitting produced nothing usable (e.g. content is one giant
        // unterminated token), fall back to a single chunk so the user
        // sees something.
        if expanded.isEmpty {
            expanded = [trimmed]
        }

        // Build raw chunks. The last one is partial iff still streaming.
        var rawChunks: [Chunk] = []
        for (idx, text) in expanded.enumerated() {
            let isLast = idx == expanded.count - 1
            rawChunks.append(Chunk(
                id: idx,
                text: text,
                isPartial: isLast && isStreaming
            ))
        }

        // Dedup consecutive identical chunks. Local MLX models often loop
        // on small prompts; collapsing N identical runs into one chunk
        // with a "(×N)" marker keeps the chat scannable and still signals
        // the user that the model looped.
        return dedupConsecutive(rawChunks)
    }

    /// Collapse runs of identical consecutive chunks into one chunk with
    /// a "(×N)" marker. Single occurrences are emitted unchanged so the
    /// user's normal assistant output is not annotated. The first chunk's
    /// id is preserved so SwiftUI ForEach identity stays stable as the
    /// run length grows during streaming.
    private static func dedupConsecutive(_ chunks: [Chunk]) -> [Chunk] {
        var result: [Chunk] = []
        var i = 0
        while i < chunks.count {
            let text = chunks[i].text
            var count = 1
            var isPartial = chunks[i].isPartial
            // Walk forward while the next chunk has identical text.
            while i + count < chunks.count, chunks[i + count].text == text {
                isPartial = isPartial || chunks[i + count].isPartial
                count += 1
            }
            let finalText: String
            if count > 1 {
                finalText = "\(text)\n\n(repeated \(count)×)"
            } else {
                finalText = text
            }
            result.append(Chunk(
                id: chunks[i].id,
                text: finalText,
                isPartial: isPartial
            ))
            i += count
        }
        return result
    }

    /// Split an oversized paragraph on sentence-ending punctuation.
    /// Keeps the terminator attached to its sentence so the chunk reads
    /// naturally on its own.
    private static func splitSentences(_ text: String) -> [String] {
        var sentences: [String] = []
        var current = ""
        let chars = Array(text)
        var i = 0
        while i < chars.count {
            current.append(chars[i])
            let c = chars[i]
            // Period / question / exclamation followed by space or end.
            if c == "." || c == "?" || c == "!" {
                // Look ahead for whitespace or end of string.
                let nextIsBoundary = (i + 1 >= chars.count) || chars[i + 1].isWhitespace
                if nextIsBoundary && current.count >= 8 {
                    let trimmed = current.trimmingCharacters(in: .whitespacesAndNewlines)
                    if !trimmed.isEmpty {
                        sentences.append(trimmed)
                    }
                    current.removeAll(keepingCapacity: true)
                }
            }
            i += 1
        }
        let tail = current.trimmingCharacters(in: .whitespacesAndNewlines)
        if !tail.isEmpty {
            sentences.append(tail)
        }
        return sentences
    }
}
