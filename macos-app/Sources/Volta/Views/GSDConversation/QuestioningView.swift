//
//  QuestioningView.swift
//  Volta
//
//  Phase 173 — GSD Conversation Engine
//
//  GSD-01: Questioning phase — clarifying questions to elicit intent.
//

import SwiftUI

/// Questioning phase view — gather clarifying answers to derive a spec.
struct QuestioningView: View {
    @Binding var spec: ProjectSpec
    let onAdvanceToSpec: () -> Void
    let onUseDefaults: () -> Void

    @State private var circuitType: String = ""
    @State private var keyRequirements: String = ""
    @State private var budgetNotes: String = ""
    @State private var validationError: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                header

                questionField(
                    label: "What type of circuit?",
                    placeholder: "e.g., distortion pedal, sensor logger, LED driver",
                    text: $circuitType
                )
                questionField(
                    label: "Key requirements?",
                    placeholder: "e.g., 9V battery, mono output, true bypass",
                    text: $keyRequirements,
                    multiline: true
                )
                questionField(
                    label: "Budget / constraints?",
                    placeholder: "e.g., under $30, fits 50×50mm, low power",
                    text: $budgetNotes,
                    multiline: true
                )

                if let validationError {
                    Text(validationError)
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.destructive)
                        .accessibilityLabel("Validation error")
                }

                actionRow
            }
            .padding(Spacing.lg)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Questioning phase")
        .accessibilityHint("Answer clarifying questions to define project")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text("Let's clarify your design")
                .font(Typography.title)
                .accessibilityAddTraits(.isHeader)
            Text("Answer what you can. We'll fill gaps with defaults.")
                .font(Typography.body)
                .foregroundStyle(ColorTokens.secondaryText)
        }
    }

    private func questionField(label: String, placeholder: String, text: Binding<String>, multiline: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(label)
                .font(Typography.heading)
            Group {
                if multiline {
                    TextField(placeholder, text: text, axis: .vertical)
                        .lineLimit(2...4)
                } else {
                    TextField(placeholder, text: text)
                }
            }
            .textFieldStyle(.roundedBorder)
        }
    }

    private var actionRow: some View {
        HStack {
            Button("Use defaults", action: onUseDefaults)
                .buttonStyle(.bordered)
                .accessibilityHint("Skips questioning with default values")
            Spacer()
            Button("Generate Spec", action: advanceWithValidation)
                .buttonStyle(.borderedProminent)
                .accessibilityHint("Generates a project spec from your answers")
        }
    }

    private func advanceWithValidation() {
        // T-173-02: validate field lengths.
        let fields = [circuitType, keyRequirements, budgetNotes]
        if fields.contains(where: { !SpecValidator.isWithinLength($0) }) {
            validationError = "One of your answers exceeds \(SpecValidator.maxFieldLength) characters. Please shorten."
            return
        }
        // Compose spec from answers (sanitized — T-173-02).
        let title = circuitType.isEmpty ? "Untitled Project" : SpecValidator.sanitize(circuitType)
        let goal = SpecValidator.sanitize(keyRequirements.isEmpty ? "Design a circuit per user intent." : keyRequirements)
        spec = ProjectSpec(
            title: title,
            goalStatement: goal,
            requirements: [goal],
            successCriteria: ["KiCad project exports without errors."],
            constraints: ProjectConstraints(otherNotes: SpecValidator.sanitize(budgetNotes))
        )
        validationError = nil
        onAdvanceToSpec()
    }
}
