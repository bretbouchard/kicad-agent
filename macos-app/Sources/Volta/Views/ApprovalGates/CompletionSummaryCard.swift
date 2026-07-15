//
//  CompletionSummaryCard.swift
//  Volta
//
//  Phase 174 — Approval Gates UI
//
//  Compact completion summary card shown when a phase ships. Wraps
//  VerifyView's summary into a smaller widget for sidebar / dashboard use.
//
//  GSD-08: completion summary accessible after dismissal.
//

import SwiftUI

/// Compact completion card — sidebar/dashboard widget.
struct CompletionSummaryCard: View {
    let summary: CompletionSummary
    let onOpen: () -> Void

    var body: some View {
        Button(action: onOpen) {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                HStack {
                    Image(systemName: "checkmark.seal.fill")
                        .foregroundStyle(ColorTokens.success)
                    Text(summary.phaseName)
                        .font(Typography.heading)
                    Spacer()
                }
                HStack(spacing: Spacing.lg) {
                    statItem(label: "Exports", value: "\(summary.exports.count)")
                    statItem(label: "Decisions", value: "\(summary.decisionsCount)")
                    statItem(label: "Duration", value: summary.formattedDuration)
                }
            }
            .padding(Spacing.md)
            .liquidGlassPanel(corner: CornerRadius.standard)
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Phase \(summary.phaseName) complete — \(summary.exports.count) exports, \(summary.decisionsCount) decisions, \(summary.formattedDuration)")
        .accessibilityHint("Tap to view full summary")
    }

    private func statItem(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(value)
                .font(Typography.heading.monospacedDigit())
            Text(label)
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.tertiaryText)
        }
    }
}
