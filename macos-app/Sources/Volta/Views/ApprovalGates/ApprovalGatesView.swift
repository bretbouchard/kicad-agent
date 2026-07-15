//
//  ApprovalGatesView.swift
//  Volta
//
//  Phase 174 — Approval Gates UI
//
//  Surfaces Obdurate Runtime gates as user-facing prompts. Three actions:
//  approve / reject / show-me. Full context (intent, op, verification,
//  requirement linkage) available before deciding.
//
//  GSD-05/06/07.
//

import SwiftUI

/// Approval gate prompt — shown when Obdurate Runtime pauses for user input.
struct ApprovalGatesView: View {
    let gate: GateContext
    let onResolve: (GateResolution) -> Void

    @State private var showDetail: Bool = false
    @State private var rejectReason: String = ""
    @State private var showRejectSheet: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            header
            context
            actions
        }
        .padding(Spacing.lg)
        .liquidGlassPanel()
        .sheet(isPresented: $showDetail) {
            GateDetailView(gate: gate, onResolve: { resolution in
                onResolve(resolution)
                showDetail = false
            })
        }
        .sheet(isPresented: $showRejectSheet) {
            rejectSheet
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Approval gate — \(gate.type.label)")
        .accessibilityHint("Approve, reject, or drill into context before deciding")
    }

    private var header: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: gate.type.systemImage)
                .font(.system(size: 28))
                .foregroundStyle(severityColor)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(gate.type.label)
                    .font(Typography.title)
                    .accessibilityAddTraits(.isHeader)
                Text(gate.timestamp.formatted(date: .abbreviated, time: .standard))
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
            Spacer()
            if let tier = gate.escalationTier {
                EscalationBadge(tier: tier)
            }
        }
    }

    private var context: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            LabeledRow(label: "Intent", value: gate.intent)
            LabeledRow(label: "Operation", value: gate.operation, mono: true)
            if let result = gate.verificationResult {
                VerificationRow(result: result)
            }
            if let reqId = gate.requirementId {
                LabeledRow(label: "Requirement", value: reqId, mono: true)
            }
        }
    }

    private var actions: some View {
        HStack(spacing: Spacing.sm) {
            Button("Show me", action: { showDetail = true })
                .buttonStyle(.bordered)
                .accessibilityHint("Drill into full gate detail before deciding")
            Spacer()
            Button("Reject", role: .destructive, action: { showRejectSheet = true })
                .buttonStyle(.bordered)
                .accessibilityHint("Reject with reason")
            Button("Approve", action: { onResolve(.approve(decision: .implemented)) })
                .buttonStyle(.borderedProminent)
                .accessibilityHint("Approve and continue execution")
        }
    }

    private var rejectSheet: some View {
        VStack(spacing: Spacing.md) {
            Text("Reject gate")
                .font(Typography.title)
            TextField("Reason (optional)", text: $rejectReason, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...4)
            HStack {
                Button("Cancel") { showRejectSheet = false }
                Spacer()
                Button("Submit Rejection", role: .destructive) {
                    onResolve(.reject(reason: rejectReason))
                    showRejectSheet = false
                }
            }
        }
        .padding(Spacing.lg)
        .frame(minWidth: 420, minHeight: 240)
    }

    private var severityColor: Color {
        switch gate.type.severityColor {
        case "warning": return ColorTokens.warning
        case "destructive": return ColorTokens.destructive
        default: return Color.accentColor
        }
    }
}

/// Compact labeled value row.
struct LabeledRow: View {
    let label: String
    let value: String
    var mono: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(label)
                .font(Typography.caption.weight(.medium))
                .foregroundStyle(ColorTokens.secondaryText)
            Text(value)
                .font(mono ? Typography.mono : Typography.body)
                .foregroundStyle(Color.primary)
                .textSelection(.enabled)
        }
    }
}

/// Verification result summary row.
struct VerificationRow: View {
    let result: VerificationSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text("Verification")
                .font(Typography.caption.weight(.medium))
                .foregroundStyle(ColorTokens.secondaryText)
            HStack(spacing: Spacing.sm) {
                Label(result.passed ? "Passed" : "Failed",
                      systemImage: result.passed ? "checkmark.circle.fill" : "xmark.octagon.fill")
                    .foregroundStyle(result.passed ? ColorTokens.success : ColorTokens.destructive)
                if result.warningCount > 0 {
                    Label("\(result.warningCount) warnings", systemImage: "exclamationmark.triangle")
                        .foregroundStyle(ColorTokens.warning)
                }
                if result.errorCount > 0 {
                    Label("\(result.errorCount) errors", systemImage: "xmark.octagon")
                        .foregroundStyle(ColorTokens.destructive)
                }
            }
            .font(Typography.caption)
            if !result.notes.isEmpty {
                Text(result.notes)
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
        }
    }
}

/// Escalation tier badge (T1/T2/T3/T4).
struct EscalationBadge: View {
    let tier: Int

    var body: some View {
        VStack(spacing: 0) {
            Text("T\(tier)")
                .font(Typography.caption.weight(.bold))
                .foregroundStyle(.white)
            Text("ESCALATION")
                .font(.system(size: 8, weight: .bold))
                .foregroundStyle(.white.opacity(0.8))
        }
        .padding(.horizontal, Spacing.xs)
        .padding(.vertical, Spacing.xxs)
        .background(tierColor, in: RoundedRectangle(cornerRadius: CornerRadius.small, style: .continuous))
        .accessibilityLabel("Escalation tier \(tier)")
    }

    private var tierColor: Color {
        switch tier {
        case 1: return ColorTokens.warning
        case 2: return Color.orange
        case 3: return Color.red.opacity(0.85)
        default: return ColorTokens.destructive
        }
    }
}
