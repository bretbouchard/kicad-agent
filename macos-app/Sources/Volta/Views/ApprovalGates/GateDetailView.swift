//
//  GateDetailView.swift
//  Volta
//
//  Phase 174 — Approval Gates UI
//
//  Drill-down sheet for a single approval gate. Shows full context including
//  intent, op, verification, requirement, and offers the four-state
//  resolution taxonomy (bureaucracy §7) when rejecting.
//

import SwiftUI

/// Full detail sheet for an approval gate.
struct GateDetailView: View {
    let gate: GateContext
    let onResolve: (GateResolution) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var selectedDecision: GateDecision = .implemented
    @State private var rejectReason: String = ""

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().opacity(0.3)
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.lg) {
                    contextSection
                    if gate.type == .escalation {
                        escalationSection
                    }
                    decisionSection
                }
                .padding(Spacing.lg)
            }
            Divider().opacity(0.3)
            actionBar
        }
        .frame(minWidth: 560, minHeight: 480)
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(gate.type.label)
                    .font(Typography.title)
                    .accessibilityAddTraits(.isHeader)
                Text("Gate detail — decide with full context")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.secondaryText)
            }
            Spacer()
            Button("Close") { dismiss() }
        }
        .padding(Spacing.md)
    }

    private var contextSection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Text("Context").font(Typography.heading)
            LabeledRow(label: "Intent", value: gate.intent)
            LabeledRow(label: "Operation", value: gate.operation, mono: true)
            if let result = gate.verificationResult {
                VerificationRow(result: result)
            }
            if let reqId = gate.requirementId {
                LabeledRow(label: "Requirement", value: reqId, mono: true)
            }
            LabeledRow(label: "Triggered", value: gate.timestamp.formatted(date: .abbreviated, time: .standard))
        }
    }

    private var escalationSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text("Escalation").font(Typography.heading)
            if let tier = gate.escalationTier {
                Text("This is a Tier \(tier) escalation. Higher tiers indicate repeated failures or scope drift.")
                    .font(Typography.body)
                    .foregroundStyle(ColorTokens.secondaryText)
            }
        }
        .padding(Spacing.md)
        .background(ColorTokens.destructive.opacity(0.08), in: RoundedRectangle(cornerRadius: CornerRadius.standard))
    }

    private var decisionSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text("If rejecting, choose a resolution state").font(Typography.heading)
            Text("Per bureaucracy §7 — no silent dismissals.")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.tertiaryText)
            Picker("Decision", selection: $selectedDecision) {
                ForEach([GateDecision.implemented, .addedAsPhase, .superseded, .deferred], id: \.self) { decision in
                    Text(decision.label).tag(decision)
                }
            }
            .pickerStyle(.radioGroup)

            if selectedDecision != .implemented {
                TextField("Reason / target phase", text: $rejectReason, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(2...4)
            }
        }
    }

    private var actionBar: some View {
        HStack {
            Button("Cancel", role: .destructive) { dismiss() }
                .buttonStyle(.bordered)
            Spacer()
            if selectedDecision == .implemented {
                Button("Approve") {
                    onResolve(.approve(decision: .implemented))
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
            } else {
                Button("Submit Rejection") {
                    onResolve(.reject(reason: "\(selectedDecision.label): \(rejectReason)"))
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .tint(ColorTokens.destructive)
            }
        }
        .padding(Spacing.md)
    }
}
