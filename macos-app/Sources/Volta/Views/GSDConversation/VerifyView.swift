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
                verificationSection
                governedSection
                manufacturingSection
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

    @ViewBuilder
    private var verificationSection: some View {
        if let verification = summary.governedVerification {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("Governed Verification")
                    .font(Typography.heading)
                HStack {
                    Image(systemName: verification.gateSatisfied ? "checkmark.shield" : "xmark.shield")
                        .foregroundStyle(ColorTokens.secondaryText)
                    Text(verification.gateSatisfied ? "Gate satisfied" : "Gate unsatisfied")
                        .font(Typography.body)
                    Spacer()
                    Text("\(verification.liveEvidenceCount) evidence · \(verification.historianChainCount) trace")
                        .font(Typography.caption.monospacedDigit())
                        .foregroundStyle(ColorTokens.tertiaryText)
                }
                Text(verification.claim)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.projectReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.revisionReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.schematicReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.sheetReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.componentReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.netReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.bomReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.pcbReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.footprintReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.verificationArtifactReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(verification.objectReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
            .accessibilityElement(children: .combine)
        }
    }

    @ViewBuilder
    private var governedSection: some View {
        if let governed = summary.governedExport {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("Governed Release")
                    .font(Typography.heading)
                HStack {
                    Image(systemName: "lock.doc")
                        .foregroundStyle(ColorTokens.secondaryText)
                    Text(governed.fileName)
                        .font(Typography.body)
                    Spacer()
                    Text("\(governed.evidenceCount) evidence")
                        .font(Typography.caption.monospacedDigit())
                        .foregroundStyle(ColorTokens.tertiaryText)
                }
                Text("Approval \(governed.approvalRequestID.uuidString.prefix(8))")
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(governed.projectReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(governed.revisionReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(governed.schematicReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(governed.sheetReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(governed.componentReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(governed.netReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(governed.bomReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(governed.pcbReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(governed.footprintReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(governed.objectReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
            .accessibilityElement(children: .combine)
        }
    }

    @ViewBuilder
    private var manufacturingSection: some View {
        if let handoff = summary.governedManufacturingHandoff {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("Manufacturing Handoff")
                    .font(Typography.heading)
                HStack {
                    Image(systemName: "shippingbox")
                        .foregroundStyle(ColorTokens.secondaryText)
                    Text(handoff.fileName)
                        .font(Typography.body)
                    Spacer()
                    Text("\(handoff.evidenceCount) evidence")
                        .font(Typography.caption.monospacedDigit())
                        .foregroundStyle(ColorTokens.tertiaryText)
                }
                Text("Approval \(handoff.approvalRequestID.uuidString.prefix(8))")
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                if let linkedVerificationClaim = handoff.linkedVerificationClaim {
                    Text(linkedVerificationClaim)
                        .font(Typography.caption.monospaced())
                        .foregroundStyle(ColorTokens.tertiaryText)
                }
                Text(handoff.projectReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(handoff.revisionReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(handoff.schematicReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(handoff.sheetReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(handoff.componentReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(handoff.netReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(handoff.bomReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(handoff.pcbReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(handoff.footprintReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
                Text(handoff.objectReference)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
            .accessibilityElement(children: .combine)
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
            if let governedExportURL = summary.governedExportURL {
                ShareLink(item: governedExportURL) {
                    Text("Share Files")
                }
                .buttonStyle(.bordered)
                .accessibilityHint("Opens share sheet with generated files")
            } else {
                Button("Share Files", action: onShare)
                    .buttonStyle(.bordered)
                    .accessibilityHint("Opens share sheet with generated files")
            }
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
