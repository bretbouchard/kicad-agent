//
//  ImageAttachmentView.swift
//  Volta
//
//  Phase 175 — Chat Interface
//
//  Thumbnail + meta for an image attached to a chat message.
//
//  CHAT-06: image attachments.
//

import SwiftUI

/// Image attachment thumbnail with size badge.
struct ImageAttachmentView: View {
    let attachment: ImageAttachment

    var body: some View {
        VStack(spacing: 0) {
            imageContent
            metaOverlay
        }
        .clipShape(RoundedRectangle(cornerRadius: CornerRadius.small, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: CornerRadius.small, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.1), lineWidth: StrokeWidth.hairline)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Image attachment \(attachment.fileName), \(attachment.formattedSize)")
    }

    private var imageContent: some View {
        Image(nsImage: NSImage(byReferencing: attachment.url))
            .resizable()
            .aspectRatio(contentMode: .fill)
            .frame(width: 60, height: 60)
            .clipped()
    }

    private var metaOverlay: some View {
        HStack {
            Image(systemName: "photo")
                .font(.system(size: 8))
            Text(attachment.formattedSize)
                .font(.system(size: 9, weight: .medium))
        }
        .padding(.horizontal, 4)
        .padding(.vertical, 2)
        .background(.ultraThinMaterial, in: Capsule())
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
        .padding(2)
        .accessibilityHidden(true)
    }
}
