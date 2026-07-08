//
//  Message.swift
//  KiCadAgent
//
//  Phase 176 — SwiftData Models
//
//  SwiftData @Model for a single message within a Conversation.
//
//  MEM-01: every message persisted
//  MEM-03: conversations append-only
//

import Foundation
import SwiftData
import OSLog

/// A single chat message within a Conversation.
///
/// Persisted forever (MEM-03 append-only). Phase 175 ChatMessage is the
/// UI-layer value type; this @Model is the persistence layer.
@Model
final class Message {
    /// Stable identifier.
    @Attribute(.unique) var id: UUID

    /// Owning conversation.
    var conversation: Conversation?

    /// Foreign key kept denormalized.
    var conversationId: UUID

    /// Who sent the message (user / assistant / system).
    var roleRaw: String

    /// Message content (sanitized per Phase 173 SpecValidator on write).
    var content: String

    /// Status raw value (pending/streaming/complete/failed/cancelled).
    var statusRaw: String

    /// Optional failure reason when status is "failed".
    var failureReason: String?

    /// Sent timestamp (UTC).
    var sentAt: Date

    /// Optional model badge ("AppleLocal", "GPT-4o", etc.).
    var modelBadge: String?

    /// Token cost (input). 0 for user messages.
    var inputTokens: Int

    /// Token cost (output). 0 for user messages.
    var outputTokens: Int

    /// Estimated USD cost. 0 for user messages.
    var estimatedCostUSD: Double

    init(
        id: UUID = UUID(),
        conversation: Conversation,
        role: MessageRole,
        content: String = "",
        status: MessageStatus = .complete,
        sentAt: Date = .now,
        modelBadge: String? = nil,
        inputTokens: Int = 0,
        outputTokens: Int = 0,
        estimatedCostUSD: Double = 0
    ) {
        precondition(!role.rawValue.isEmpty, "Message role must not be empty")
        self.id = id
        self.conversation = conversation
        self.conversationId = conversation.id
        self.roleRaw = role.rawValue
        self.content = content
        self.statusRaw = Message.statusKey(for: status)
        self.failureReason = Message.extractFailureReason(status)
        self.sentAt = sentAt
        self.modelBadge = modelBadge
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.estimatedCostUSD = estimatedCostUSD
        Logger.models.info("Message created id=\(self.id.uuidString.prefix(8)) role=\(self.roleRaw)")
    }
}

extension Message {
    /// Typed accessor for role.
    var role: MessageRole {
        get { MessageRole(rawValue: roleRaw) ?? .user }
        set { roleRaw = newValue.rawValue }
    }

    /// Typed accessor for status. Reconstructs from raw + failureReason.
    var status: MessageStatus {
        get {
            switch statusRaw {
            case "pending": return .pending
            case "streaming": return .streaming
            case "complete": return .complete
            case "cancelled": return .cancelled
            case "failed": return .failed(failureReason ?? "Unknown error")
            default: return .pending
            }
        }
        set {
            statusRaw = Message.statusKey(for: newValue)
            failureReason = Message.extractFailureReason(newValue)
        }
    }

    /// Total tokens (input + output) for cost ledger.
    var totalTokens: Int { inputTokens + outputTokens }

    /// Helper: stable raw key for a MessageStatus (without associated value).
    static func statusKey(for status: MessageStatus) -> String {
        switch status {
        case .pending: return "pending"
        case .streaming: return "streaming"
        case .complete: return "complete"
        case .failed: return "failed"
        case .cancelled: return "cancelled"
        }
    }

    /// Helper: extract failure reason from status (for separate column).
    static func extractFailureReason(_ status: MessageStatus) -> String? {
        if case .failed(let reason) = status { return reason }
        return nil
    }
}
