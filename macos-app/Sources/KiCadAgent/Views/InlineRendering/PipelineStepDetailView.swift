//
//  PipelineStepDetailView.swift
//  KiCadAgent
//
//  Phase 172 — Inline Rendering
//
//  Drill-down view for a single pipeline step. Shows intent, ops called,
//  verification results, duration, and linked requirement.
//
//  PIPE-03: tap any pipeline step to drill into detail.
//

import SwiftUI

/// Detail view for one pipeline step (post-tap drill-down).
struct PipelineStepDetailView: View {
    let step: PipelineStep
    let detail: StepDetail

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.md) {
                header
                Divider().opacity(0.3)
                section(title: "Intent") {
                    Text(detail.intent)
                        .font(Typography.body)
                }
                if !detail.opsCalled.isEmpty {
                    section(title: "Operations Called") {
                        opsList
                    }
                }
                section(title: "Verification") {
                    verificationSummary
                }
                section(title: "Duration") {
                    Text(formatDuration(ms: detail.durationMs))
                        .font(Typography.mono)
                }
                if let requirementId = detail.requirementId {
                    section(title: "Linked Requirement") {
                        Label(requirementId, systemImage: "checkmark.seal")
                            .font(Typography.body)
                            .foregroundStyle(ColorTokens.secondaryText)
                    }
                }
            }
            .padding(Spacing.lg)
        }
        .frame(minWidth: 480, minHeight: 360)
    }

    private var header: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: step.systemImage)
                .font(.system(size: 28))
                .foregroundStyle(detail.status.color)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(step.label)
                    .font(Typography.title)
                    .accessibilityAddTraits(.isHeader)
                Text(detail.status.rawValue.capitalized)
                    .font(Typography.caption)
                    .foregroundStyle(detail.status.color)
            }
            Spacer()
        }
    }

    private var opsList: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            ForEach(detail.opsCalled, id: \.self) { op in
                HStack(spacing: Spacing.xs) {
                    Image(systemName: "terminal")
                        .foregroundStyle(ColorTokens.tertiaryText)
                        .accessibilityHidden(true)
                    Text(op)
                        .font(Typography.mono)
                        .foregroundStyle(ColorTokens.secondaryText)
                }
            }
        }
    }

    private var verificationSummary: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            HStack {
                Label("\(detail.passedChecks) passed", systemImage: "checkmark.circle")
                    .foregroundStyle(ColorTokens.success)
                Spacer()
                if detail.warningCount > 0 {
                    Label("\(detail.warningCount) warnings", systemImage: "exclamationmark.triangle")
                        .foregroundStyle(ColorTokens.warning)
                }
                if detail.errorCount > 0 {
                    Label("\(detail.errorCount) errors", systemImage: "xmark.octagon")
                        .foregroundStyle(ColorTokens.destructive)
                }
            }
            .font(Typography.caption.weight(.medium))
            if !detail.verificationNotes.isEmpty {
                Text(detail.verificationNotes)
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
        }
    }

    private func section<Content: View>(title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(title)
                .font(Typography.heading)
            content()
        }
    }

    private func formatDuration(ms: Int) -> String {
        if ms < 1000 { return "\(ms)ms" }
        let seconds = Double(ms) / 1000.0
        if seconds < 60 { return String(format: "%.2fs", seconds) }
        let minutes = Int(seconds) / 60
        let remSeconds = Int(seconds) % 60
        return "\(minutes)m \(remSeconds)s"
    }
}

/// Detail payload for a pipeline step.
///
/// ponytail: value type. Cheap to pass around, value semantics.
struct StepDetail: Sendable, Equatable {
    let status: StepStatus
    let intent: String
    let opsCalled: [String]
    let durationMs: Int
    let passedChecks: Int
    let warningCount: Int
    let errorCount: Int
    let verificationNotes: String
    let requirementId: String?

    init(
        status: StepStatus,
        intent: String,
        opsCalled: [String] = [],
        durationMs: Int = 0,
        passedChecks: Int = 0,
        warningCount: Int = 0,
        errorCount: Int = 0,
        verificationNotes: String = "",
        requirementId: String? = nil
    ) {
        self.status = status
        self.intent = intent
        self.opsCalled = opsCalled
        self.durationMs = durationMs
        self.passedChecks = passedChecks
        self.warningCount = warningCount
        self.errorCount = errorCount
        self.verificationNotes = verificationNotes
        self.requirementId = requirementId
    }
}
