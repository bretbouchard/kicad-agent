//
//  ChatTypes.swift
//  Volta
//
//  Phase 175 — Chat Interface
//
//  Value types for chat: ChatMessage, MessageRole, MessageStatus, CostEstimate.
//  UI layer types — kept separate from SwiftData @Model (Phase 176 ships
//  SwiftData Message model for Track E Memory).
//
//  CHAT-01: natural language hardware design intent
//  CHAT-02: streamed responses token-by-token
//  CHAT-06: image attachments
//  CHAT-07: cost tracking per message
//  CHAT-08: conversation forking
//

import Foundation
import SwiftUI
import AppKit

/// Who sent a chat message.
enum MessageRole: String, Codable, Sendable, Equatable {
    case user
    case assistant
    case system
}

/// Where the message is in its lifecycle.
enum MessageStatus: Codable, Sendable, Equatable {
    case pending       // Queued, not sent
    case streaming     // Tokens arriving
    case complete      // Done
    case failed(String) // Error with reason
    case cancelled     // User hit ESC

    var isFinal: Bool {
        switch self {
        case .complete, .failed, .cancelled: return true
        case .pending, .streaming: return false
        }
    }
}

/// A single chat message in the UI layer. The SwiftData @Model layer
/// (Phase 176) will persist these as `Message` rows.
struct ChatMessage: Identifiable, Sendable, Equatable {
    let id: UUID
    let role: MessageRole
    var content: String
    var status: MessageStatus
    var sentAt: Date
    var costEstimate: CostEstimate?
    var modelBadge: String?
    var attachments: [ImageAttachment]
    /// Optional artifact rendered alongside (schematic/PCB).
    var renderArtifact: RenderArtifact?

    init(
        id: UUID = UUID(),
        role: MessageRole,
        content: String = "",
        status: MessageStatus = .pending,
        sentAt: Date = .now,
        costEstimate: CostEstimate? = nil,
        modelBadge: String? = nil,
        attachments: [ImageAttachment] = [],
        renderArtifact: RenderArtifact? = nil
    ) {
        self.id = id
        self.role = role
        self.content = content
        self.status = status
        self.sentAt = sentAt
        self.costEstimate = costEstimate
        self.modelBadge = modelBadge
        self.attachments = attachments
        self.renderArtifact = renderArtifact
    }
}

/// Cost estimate for an assistant message.
struct CostEstimate: Sendable, Equatable {
    let inputTokens: Int
    let outputTokens: Int
    let estimatedUSD: Double
    let modelId: String

    init(inputTokens: Int, outputTokens: Int, estimatedUSD: Double, modelId: String) {
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.estimatedUSD = estimatedUSD
        self.modelId = modelId
    }

    var totalTokens: Int { inputTokens + outputTokens }

    var formattedCost: String {
        if estimatedUSD < 0.01 {
            return String(format: "$%.4f", estimatedUSD)
        }
        return String(format: "$%.2f", estimatedUSD)
    }
}

/// Image attached to a chat message.
struct ImageAttachment: Identifiable, Sendable, Equatable {
    let id: UUID
    let fileName: String
    let fileSizeBytes: Int64
    let mimeType: String
    /// Stable file URL (could be temp or persisted).
    let url: URL
    /// Pixel dimensions (for display aspect).
    let pixelWidth: Int
    let pixelHeight: Int

    init(id: UUID = UUID(), fileName: String, fileSizeBytes: Int64, mimeType: String, url: URL, pixelWidth: Int, pixelHeight: Int) {
        self.id = id
        self.fileName = fileName
        self.fileSizeBytes = fileSizeBytes
        self.mimeType = mimeType
        self.url = url
        self.pixelWidth = pixelWidth
        self.pixelHeight = pixelHeight
    }

    var formattedSize: String {
        ByteCountFormatter.string(fromByteCount: fileSizeBytes, countStyle: .file)
    }

    /// True if attachment is acceptable per CHAT-06 constraints.
    static var acceptedMimeTypes: Set<String> {
        ["image/png", "image/jpeg", "image/heic"]
    }

    /// Max file size before auto-compression kicks in.
    static let maxFileSizeBytes: Int64 = 10 * 1024 * 1024 // 10 MB

    /// Max dimension after compression.
    static let maxDimension: CGFloat = 2048
}

/// Validator for image attachments (CHAT-06).
enum ImageAttachmentValidator {
    /// True if the attachment is acceptable as-is.
    static func isAcceptable(_ attachment: ImageAttachment) -> Bool {
        ImageAttachment.acceptedMimeTypes.contains(attachment.mimeType)
    }

    /// True if attachment exceeds the size limit and needs compression.
    static func needsCompression(_ attachment: ImageAttachment) -> Bool {
        attachment.fileSizeBytes > ImageAttachment.maxFileSizeBytes
    }
}

/// Test-friendly chat stream protocol.
///
/// ponytail: protocol, not concrete class. Phase 175 ships NoopChatStream
/// for previews. Phase 175+ wires ProviderRouter as ChatStreamProvider.
///
/// Pass the full conversation history (including the in-flight user
/// message) so providers can render multi-turn context into the model's
/// chat template. The first element is the oldest turn; the last is the
/// most recent user message that triggered this stream.
protocol ChatStreamProvider: Sendable {
    /// Stream tokens for a full conversation.
    /// Returns `AsyncThrowingStream<String, Error>` — caller cancels via task cancellation.
    func stream(history: [ChatMessage], attachments: [ImageAttachment]) -> AsyncThrowingStream<String, Error>
}

/// Default stream provider used in previews/tests — emits canned text.
struct NoopChatStream: ChatStreamProvider {
    let cannedResponse: String

    init(cannedResponse: String = "I'm a mock assistant response for preview.") {
        self.cannedResponse = cannedResponse
    }

    func stream(history: [ChatMessage], attachments: [ImageAttachment]) -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { continuation in
            // Emit word-by-word so streaming UI is exercisable.
            Task {
                for word in cannedResponse.split(separator: " ") {
                    try? await Task.sleep(nanoseconds: 10_000_000)
                    continuation.yield(String(word) + " ")
                }
                continuation.finish()
            }
        }
    }
}

// MARK: - ConversationExporter

/// Formats a chat conversation for export to the system clipboard.
///
/// Why this exists: chat history is the user's design intent + the
/// model's engineering response. Both halves are valuable artifacts that
/// the user wants to paste into bug reports, design docs, share with
/// collaborators, or save alongside their KiCad project. Exporter is a
/// pure function so it's testable without NSPasteboard and reusable
/// from any future export destinations (file, share sheet, etc.).
enum ConversationExporter {
    /// Format the full conversation as plain text, suitable for paste
    /// into a text editor, GitHub issue, email, or document.
    ///
    /// Format:
    /// ```
    /// [2026-07-14 09:42] User:
    /// Design a 20dB gain stage for guitar.
    ///
    /// [2026-07-14 09:42] Assistant (gemma-4-12b-it-mlx-q4):
    /// Sure — here's a non-inverting op-amp stage...
    /// ```
    ///
    /// System messages (operation results, daemon errors) are included
    /// with a `System:` label so the full session context is preserved.
    /// Empty / streaming / cancelled messages are skipped — only finished
    /// content is exported.
    static func plainText(messages: [ChatMessage]) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withYear, .withMonth, .withDay, .withTime]

        var parts: [String] = []
        for message in messages {
            // Skip empty / in-flight messages — pasting a half-streamed
            // response is worse than not pasting it.
            let content = message.content.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !content.isEmpty else { continue }
            if case .pending = message.status { continue }
            if case .streaming = message.status { continue }
            if case .cancelled = message.status { continue }

            let label: String
            switch message.role {
            case .user: label = "User"
            case .assistant:
                if let badge = message.modelBadge, !badge.isEmpty {
                    label = "Assistant (\(badge))"
                } else {
                    label = "Assistant"
                }
            case .system: label = "System"
            }
            let timestamp = formatter.string(from: message.sentAt)
            parts.append("[\(timestamp)] \(label):\n\(content)")
        }

        // Header + body. The header signals the export format so pasted
        // text is self-describing.
        let header = "Volta PCB Conversation Export"
        let generated = formatter.string(from: Date())
        return "\(header) — generated \(generated)\n\n" + parts.joined(separator: "\n\n") + "\n"
    }

    /// Copy the formatted conversation to the system clipboard.
    /// Returns the number of characters written so callers can show a
    /// confirmation toast ("Copied 1,243 characters").
    @discardableResult
    @MainActor
    static func copyToClipboard(messages: [ChatMessage]) -> Int {
        let text = plainText(messages: messages)
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
        return text.count
    }
}
