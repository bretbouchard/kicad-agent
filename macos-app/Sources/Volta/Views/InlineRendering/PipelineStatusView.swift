//
//  PipelineStatusView.swift
//  Volta
//
//  Phase 172 — Inline Rendering
//
//  Horizontal step bar visualizing pipeline progress. Six canonical steps
//  (design → schematic → ERC → PCB → DRC → export) with status icons,
//  connecting progress lines, and tap-to-drill.
//
//  PIPE-01/02/03: pipeline visualization requirements.
//  A11Y-03: labeled steps.
//

import SwiftUI

/// Live pipeline status bar — 6 canonical steps with status + duration.
struct PipelineStatusView: View {
    /// Per-step status. Defaults to all `.pending`.
    let statuses: [PipelineStep: StepStatus]
    /// Per-step duration in milliseconds (only present after `.verified`).
    let durationsMs: [PipelineStep: Int]
    /// Optional callback when user taps a step.
    let onStepTap: ((PipelineStep) -> Void)?

    init(
        statuses: [PipelineStep: StepStatus] = [:],
        durationsMs: [PipelineStep: Int] = [:],
        onStepTap: ((PipelineStep) -> Void)? = nil
    ) {
        self.statuses = statuses
        self.durationsMs = durationsMs
        self.onStepTap = onStepTap
    }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .center, spacing: 0) {
                ForEach(Array(PipelineStep.allCases.enumerated()), id: \.element.id) { idx, step in
                    stepNode(step)
                    if idx < PipelineStep.allCases.count - 1 {
                        connector(from: step, to: PipelineStep.allCases[idx + 1])
                    }
                }
            }
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, Spacing.xs)
        }
        .liquidGlassToolbar()
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Pipeline status")
        .accessibilityHint("Six-step hardware design pipeline. Tap any step for details.")
    }

    /// Single step node — circle + icon + label + duration.
    private func stepNode(_ step: PipelineStep) -> some View {
        let status = statuses[step] ?? .pending
        let duration = durationsMs[step]

        return VStack(spacing: Spacing.xxs) {
            ZStack {
                Circle()
                    .fill(status.color.opacity(0.18))
                    .frame(width: 36, height: 36)
                if status == .running {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Image(systemName: status.systemImage)
                        .foregroundStyle(status.color)
                        .font(.system(size: 14, weight: .semibold))
                        .accessibilityHidden(true)
                }
            }
            Text(step.label)
                .font(Typography.caption.weight(.medium))
                .foregroundStyle(ColorTokens.secondaryText)
            if let duration, status == .verified {
                Text(formatDuration(ms: duration))
                    .font(Typography.caption.monospacedDigit())
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
        }
        .frame(width: 86)
        .padding(.vertical, Spacing.xxs)
        .contentShape(Rectangle())
        .onTapGesture { onStepTap?(step) }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(step.label) — \(statusLabel(status, duration: duration))")
        .accessibilityHint(status == .failed ? "Tap to retry this step" : "Tap for step details")
    }

    /// Connector line between adjacent steps. Color reflects transition status.
    private func connector(from: PipelineStep, to: PipelineStep) -> some View {
        let fromStatus = statuses[from] ?? .pending
        let toStatus = statuses[to] ?? .pending

        let color: Color = {
            if fromStatus == .verified && (toStatus == .verified || toStatus == .running) {
                return ColorTokens.success
            }
            if fromStatus == .verified && toStatus == .pending {
                return ColorTokens.success.opacity(0.5)
            }
            if fromStatus == .failed || toStatus == .failed {
                return ColorTokens.destructive.opacity(0.5)
            }
            return ColorTokens.tertiaryText.opacity(0.4)
        }()

        return Rectangle()
            .fill(color)
            .frame(width: 28, height: 2)
            .padding(.bottom, Spacing.lg)
            .accessibilityHidden(true)
    }

    private func formatDuration(ms: Int) -> String {
        if ms < 1000 { return "\(ms)ms" }
        let seconds = Double(ms) / 1000.0
        if seconds < 60 { return String(format: "%.1fs", seconds) }
        let minutes = Int(seconds) / 60
        let remSeconds = Int(seconds) % 60
        return "\(minutes)m \(remSeconds)s"
    }

    private func statusLabel(_ status: StepStatus, duration: Int?) -> String {
        switch status {
        case .pending: return "pending"
        case .running: return "running"
        case .verified: return duration.map { "verified in \(formatDuration(ms: $0))" } ?? "verified"
        case .failed: return "failed"
        }
    }
}
