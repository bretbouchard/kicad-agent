//
//  RoadmapView.swift
//  Volta
//
//  Phase 173 — GSD Conversation Engine
//
//  GSD-03: Roadmap phase — timeline visualization of phases.
//

import SwiftUI

/// Roadmap phase view — timeline of phases with approve / refine actions.
struct RoadmapView: View {
    @Binding var roadmap: ProjectRoadmap
    let onApprove: () -> Void
    let onRefine: () -> Void

    @State private var selectedPhaseId: UUID?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                Text("Project Roadmap")
                    .font(Typography.title)
                    .accessibilityAddTraits(.isHeader)

                timeline

                if let selectedId = selectedPhaseId, let phase = roadmap.phases.first(where: { $0.id == selectedId }) {
                    phaseDetailSheet(phase)
                }

                actionRow
            }
            .padding(Spacing.lg)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Project roadmap")
        .accessibilityHint("Tap any phase for details, approve to begin execution")
    }

    private var timeline: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: 0) {
                ForEach(Array(roadmap.phases.enumerated()), id: \.element.id) { idx, phase in
                    phaseNode(phase)
                    if idx < roadmap.phases.count - 1 {
                        Rectangle()
                            .fill(ColorTokens.tertiaryText.opacity(0.4))
                            .frame(width: 32, height: 2)
                            .padding(.top, Spacing.lg)
                            .accessibilityHidden(true)
                    }
                }
            }
            .padding(.vertical, Spacing.md)
        }
        .liquidGlassPanel()
    }

    private func phaseNode(_ phase: RoadmapPhase) -> some View {
        VStack(spacing: Spacing.xs) {
            ZStack {
                Circle()
                    .fill(ColorTokens.action.opacity(0.18))
                    .frame(width: 44, height: 44)
                Image(systemName: "circle.fill")
                    .foregroundStyle(ColorTokens.action)
                    .font(.system(size: 12))
            }
            Text(phase.name)
                .font(Typography.caption.weight(.medium))
                .multilineTextAlignment(.center)
                .frame(width: 100)
            Text(phase.estimatedDurationLabel)
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.tertiaryText)
        }
        .frame(width: 110)
        .padding(.vertical, Spacing.xs)
        .contentShape(Rectangle())
        .onTapGesture { selectedPhaseId = phase.id }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(phase.name) phase — estimated \(phase.estimatedDurationLabel)")
        .accessibilityHint("Tap for details")
    }

    private func phaseDetailSheet(_ phase: RoadmapPhase) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack {
                Text(phase.name)
                    .font(Typography.title)
                Spacer()
                Button("Close") { selectedPhaseId = nil }
            }

            Text("Goal")
                .font(Typography.heading)
            Text(phase.goal)
                .font(Typography.body)

            if !phase.requirements.isEmpty {
                Text("Requirements")
                    .font(Typography.heading)
                ForEach(phase.requirements.indices, id: \.self) { idx in
                    Label(phase.requirements[idx], systemImage: "checkmark")
                        .font(Typography.body)
                }
            }

            if !phase.successCriteria.isEmpty {
                Text("Success Criteria")
                    .font(Typography.heading)
                ForEach(phase.successCriteria.indices, id: \.self) { idx in
                    Label(phase.successCriteria[idx], systemImage: "star")
                        .font(Typography.body)
                }
            }

            Text("Estimated Duration: \(phase.estimatedDurationLabel)")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.tertiaryText)
        }
        .padding(Spacing.lg)
        .liquidGlassPanel()
        .transition(.opacity)
    }

    private var actionRow: some View {
        HStack {
            Button("Refine Roadmap", action: onRefine)
                .buttonStyle(.bordered)
                .accessibilityHint("Regenerates roadmap via LLM")
            Spacer()
            Button("Approve Roadmap", action: onApprove)
                .buttonStyle(.borderedProminent)
                .accessibilityHint("Saves roadmap and begins execution")
        }
    }
}
