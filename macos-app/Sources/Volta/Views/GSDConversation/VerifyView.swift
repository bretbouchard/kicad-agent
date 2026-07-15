//
//  VerifyView.swift
//  Volta
//
//  Phase 173 — GSD Conversation Engine
//
//  GSD-08: Verify phase — completion summary with renders + exports.
//

import SwiftUI

/// Verify phase view — completion summary.
struct VerifyView: View {
    let summary: CompletionSummary
    let previewRenderer: PreviewRenderer?
    let onComplete: () -> Void
    let onShare: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                header

                rendersSection
                exportsSection
                decisionsSection
                durationSection

                actionRow
            }
            .padding(Spacing.lg)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Phase completion summary")
        .accessibilityHint("View renders, exports, and decisions for this phase")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Label("Phase Complete", systemImage: "checkmark.seal.fill")
                .font(Typography.title)
                .foregroundStyle(ColorTokens.success)
                .accessibilityAddTraits(.isHeader)
            Text(summary.phaseName)
                .font(Typography.body)
                .foregroundStyle(ColorTokens.secondaryText)
        }
    }

    @ViewBuilder
    private var rendersSection: some View {
        if summary.schematicPath != nil || summary.pcbPath != nil || previewRenderer != nil {
            VStack(alignment: .leading, spacing: Spacing.md) {
                Text("Renders")
                    .font(Typography.heading)
                if let schematicPath = summary.schematicPath, let renderer = previewRenderer {
                    SchematicPreviewView(schematicPath: schematicPath, renderer: renderer)
                }
                if let pcbPath = summary.pcbPath, let renderer = previewRenderer {
                    PCBPreviewView(pcbPath: pcbPath, side: .front, renderer: renderer)
                }
            }
        }
    }

    @ViewBuilder
    private var exportsSection: some View {
        if !summary.exports.isEmpty {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("Exports")
                    .font(Typography.heading)
                ForEach(summary.exports) { export in
                    HStack {
                        Image(systemName: iconForKind(export.kind))
                            .foregroundStyle(ColorTokens.secondaryText)
                        Text(export.fileName)
                            .font(Typography.body)
                        Spacer()
                        Text(export.formattedSize)
                            .font(Typography.caption.monospacedDigit())
                            .foregroundStyle(ColorTokens.tertiaryText)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        }
    }

    private var decisionsSection: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text("Decisions Made")
                .font(Typography.heading)
            Text("\(summary.decisionsCount) decisions captured during this phase.")
                .font(Typography.body)
        }
    }

    private var durationSection: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text("Phase Duration")
                .font(Typography.heading)
            Text(summary.formattedDuration)
                .font(Typography.mono)
                .foregroundStyle(ColorTokens.secondaryText)
        }
    }

    private var actionRow: some View {
        HStack {
            Button("Share Files", action: onShare)
                .buttonStyle(.bordered)
                .accessibilityHint("Opens share sheet with generated files")
            Spacer()
            Button("Complete Phase", action: onComplete)
                .buttonStyle(.borderedProminent)
                .accessibilityHint("Marks phase as complete and archives summary")
        }
    }

    private func iconForKind(_ kind: ExportKind) -> String {
        switch kind {
        case .gerber: return "square.grid.3x3"
        case .drill: return "dot.scope"
        case .bom: return "list.clipboard"
        case .position: return "mappin.and.ellipse"
        case .step: return "cube"
        case .other: return "doc"
        }
    }
}
