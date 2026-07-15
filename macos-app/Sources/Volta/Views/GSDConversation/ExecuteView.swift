//
//  ExecuteView.swift
//  Volta
//
//  Phase 173 — GSD Conversation Engine
//
//  GSD-04: Execute phase — live pipeline progress + pause/cancel.
//

import SwiftUI

/// Execute phase view — embeds PipelineStatusView with control row.
struct ExecuteView: View {
    let statuses: [PipelineStep: StepStatus]
    let durationsMs: [PipelineStep: Int]
    let currentOperationDescription: String?
    let onPause: () -> Void
    let onCancel: () -> Void
    let onRetry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.lg) {
            HStack {
                Text("Executing")
                    .font(Typography.title)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                ProgressView()
                    .controlSize(.small)
            }

            if let desc = currentOperationDescription {
                Text(desc)
                    .font(Typography.body)
                    .foregroundStyle(ColorTokens.secondaryText)
            }

            PipelineStatusView(statuses: statuses, durationsMs: durationsMs)

            if statuses.values.contains(.failed) {
                failureBanner
            }

            controlRow
        }
        .padding(Spacing.lg)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Execution progress")
        .accessibilityHint("View operation progress, pause or cancel execution")
    }

    private var failureBanner: some View {
        VStack(spacing: Spacing.sm) {
            Image(systemName: "exclamationmark.octagon.fill")
                .font(.system(size: 28))
                .foregroundStyle(ColorTokens.destructive)
            Text("A step failed. Retry to trigger Obdurate escalation.")
                .font(Typography.body)
                .multilineTextAlignment(.center)
            Button("Retry failed step", action: onRetry)
                .buttonStyle(.borderedProminent)
                .accessibilityHint("Triggers Obdurate T2→T3 escalation after 3 retries")
        }
        .frame(maxWidth: .infinity)
        .padding()
        .liquidGlassPanel()
    }

    private var controlRow: some View {
        HStack {
            Button("Pause", action: onPause)
                .buttonStyle(.bordered)
                .accessibilityHint("Pauses execution after current op completes")
            Spacer()
            Button("Cancel", role: .destructive, action: onCancel)
                .buttonStyle(.bordered)
                .accessibilityHint("Cancels execution with confirmation dialog")
        }
    }
}
