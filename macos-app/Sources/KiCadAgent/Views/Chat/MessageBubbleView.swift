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

            // Main content
            if message.content.isEmpty && message.status == .streaming {
                typingIndicator
            } else {
                Text(message.content.isEmpty && message.status == .pending ? "…" : message.content)
                    .font(Typography.body)
                    .foregroundStyle(Color.primary)
                    .textSelection(.enabled)
                    .accessibilityLabel("\(message.role.rawValue) message")
            }

            // Inline render artifact (if present)
            if let artifact = message.renderArtifact {
                inlineArtifact(artifact)
            }

            // Cost + status row
            footer
        }
        .padding(Spacing.md)
        .background(bubbleBackground, in: bubbleShape)
        .accessibilityElement(children: .contain)
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
