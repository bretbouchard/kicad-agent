//
//  FullScreenInspector.swift
//  Volta
//
//  Phase 172 — Inline Rendering
//
//  Full-screen inspector for rendered artifacts. Supports zoom/pan and export.
//  Used by SchematicPreviewView and PCBPreviewView tap-to-expand.
//

import SwiftUI

/// Full-screen viewer for a rendered artifact URL.
struct FullScreenInspector: View {
    let title: String
    let url: URL

    @Environment(\.dismiss) private var dismiss
    @State private var scale: CGFloat = 1.0

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(title)
                    .font(Typography.title)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Button("Done") { dismiss() }
                    .keyboardShortcut(.defaultAction)
                    .accessibilityLabel("Done")
            }
            .padding(Spacing.md)

            Divider().opacity(0.3)

            ScrollView([.horizontal, .vertical]) {
                fileViewer
                    .scaleEffect(scale)
            }
            .padding(Spacing.lg)

            Divider().opacity(0.3)

            HStack {
                Button {
                    withAnimation { scale = max(0.5, scale - 0.2) }
                } label: {
                    Image(systemName: "minus.magnifyingglass")
                }
                .accessibilityLabel("Zoom out")

                Text("\(Int(scale * 100))%")
                    .font(Typography.caption)
                    .monospacedDigit()
                    .frame(width: 60)

                Button {
                    withAnimation { scale = min(4.0, scale + 0.2) }
                } label: {
                    Image(systemName: "plus.magnifyingglass")
                }
                .accessibilityLabel("Zoom in")

                Spacer()

                ShareLink(item: url) {
                    Label("Share", systemImage: "square.and.arrow.up")
                }
                .accessibilityLabel("Share \(title)")
            }
            .padding(Spacing.md)
        }
        .frame(minWidth: 720, minHeight: 540)
    }

    /// Inline file viewer by extension.
    @ViewBuilder
    private var fileViewer: some View {
        let ext = url.pathExtension.lowercased()
        if ext == "svg" {
            SVGImageView(url: url)
                .frame(maxWidth: 600, maxHeight: 600)
        } else if ["png", "jpg", "jpeg"].contains(ext) {
            Image(nsImage: NSImage(byReferencing: url))
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(maxWidth: 600, maxHeight: 600)
        } else {
            Text("Unsupported file type: .\(ext)")
                .font(Typography.body)
                .foregroundStyle(ColorTokens.secondaryText)
        }
    }
}
