//
//  SpecView.swift
//  Volta
//
//  Phase 173 — GSD Conversation Engine
//
//  GSD-02: Spec phase — editable project specification card.
//

import SwiftUI

/// Spec phase view — editable, expandable project spec card.
struct SpecView: View {
    @Binding var spec: ProjectSpec
    let onApprove: () -> Void
    let onBack: () -> Void

    @State private var isExpanded: Bool = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                DisclosureGroup(isExpanded: $isExpanded) {
                    specContent
                        .padding(.top, Spacing.md)
                } label: {
                    Label("Project Spec", systemImage: "doc.text.magnifyingglass")
                        .font(Typography.title)
                        .accessibilityAddTraits(.isHeader)
                }
                .liquidGlassPanel()

                actionRow
            }
            .padding(Spacing.lg)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Project specification")
        .accessibilityHint("Edit project requirements and constraints")
    }

    private var specContent: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            titledField("Title", text: $spec.title)
            titledFieldMultiline("Goal Statement", text: $spec.goalStatement)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("Requirements")
                    .font(Typography.heading)
                ForEach(spec.requirements.indices, id: \.self) { idx in
                    TextField("Requirement \(idx + 1)", text: Binding(
                        get: { spec.requirements[idx] },
                        set: { newVal in
                            if SpecValidator.isWithinLength(newVal) {
                                spec.requirements[idx] = SpecValidator.sanitize(newVal)
                            }
                        }
                    ))
                    .textFieldStyle(.roundedBorder)
                }
            }

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("Success Criteria")
                    .font(Typography.heading)
                ForEach(spec.successCriteria.indices, id: \.self) { idx in
                    TextField("Criterion \(idx + 1)", text: Binding(
                        get: { spec.successCriteria[idx] },
                        set: { newVal in
                            if SpecValidator.isWithinLength(newVal) {
                                spec.successCriteria[idx] = SpecValidator.sanitize(newVal)
                            }
                        }
                    ))
                    .textFieldStyle(.roundedBorder)
                }
            }

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("Constraints")
                    .font(Typography.heading)
                HStack {
                    titledField("Budget ($)", text: Binding(
                        get: { spec.constraints.budgetUSD ?? "" },
                        set: { spec.constraints.budgetUSD = $0.isEmpty ? nil : $0 }
                    ))
                    titledField("Size (mm)", text: Binding(
                        get: { spec.constraints.sizeMM ?? "" },
                        set: { spec.constraints.sizeMM = $0.isEmpty ? nil : $0 }
                    ))
                }
                titledField("Power (V)", text: Binding(
                    get: { spec.constraints.powerV ?? "" },
                    set: { spec.constraints.powerV = $0.isEmpty ? nil : $0 }
                ))
            }
        }
    }

    private func titledField(_ title: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(title).font(Typography.caption).foregroundStyle(ColorTokens.secondaryText)
            TextField(title, text: text)
                .textFieldStyle(.roundedBorder)
        }
    }

    private func titledFieldMultiline(_ title: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(title).font(Typography.caption).foregroundStyle(ColorTokens.secondaryText)
            TextField(title, text: text, axis: .vertical)
                .lineLimit(2...5)
                .textFieldStyle(.roundedBorder)
        }
    }

    private var actionRow: some View {
        HStack {
            Button("Back to Questioning", action: onBack)
                .buttonStyle(.bordered)
            Spacer()
            Button("Approve Spec", action: onApprove)
                .buttonStyle(.borderedProminent)
                .accessibilityHint("Saves spec and advances to roadmap generation")
        }
    }
}
