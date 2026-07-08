//
//  TimeTravelView.swift
//  KiCadAgent
//
//  Phase 179 — Decision Timeline UI
//
//  Scrub slider for time-travel + snapshot preview. Lets the user jump
//  to any point in the conversation's history.
//
//  TT-03: scrub slider.
//  TT-04: compare two points (diff view).
//

import SwiftUI

/// Scrub slider + diff/restore UI.
struct TimeTravelView: View {
    let conversationId: UUID
    let timeRange: ClosedRange<Date>
    let onScrub: (Date) -> Void
    let onDiff: (Date, Date) -> Void
    let onRestore: (Date) -> Void

    @State private var scrubDate: Date
    @State private var diffAnchorDate: Date?
    @State private var showRestoreConfirm: Bool = false

    init(
        conversationId: UUID,
        timeRange: ClosedRange<Date>,
        onScrub: @escaping (Date) -> Void,
        onDiff: @escaping (Date, Date) -> Void,
        onRestore: @escaping (Date) -> Void
    ) {
        self.conversationId = conversationId
        self.timeRange = timeRange
        self.onScrub = onScrub
        self.onDiff = onDiff
        self.onRestore = onRestore
        self._scrubDate = State(initialValue: timeRange.upperBound)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.lg) {
            header
            scrubber
            diffActions
            restoreAction
        }
        .padding(Spacing.lg)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Time travel")
        .accessibilityHint("Scrub to any point in project history. Diff or restore from any timestamp.")
        .alert("Restore State?", isPresented: $showRestoreConfirm) {
            Button("Cancel", role: .cancel) {}
            Button("Restore", role: .destructive) {
                onRestore(scrubDate)
            }
        } message: {
            Text("This will create new ValueChange events that bring state back to \(scrubDate.formatted(date: .abbreviated, time: .shortened)). History is preserved.")
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text("Time Travel")
                .font(Typography.title)
                .accessibilityAddTraits(.isHeader)
            Text("Scrub through \(timeRange.lowerBound.formatted(date: .abbreviated, time: .omitted)) → \(timeRange.upperBound.formatted(date: .abbreviated, time: .omitted))")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.secondaryText)
        }
    }

    private var scrubber: some View {
        VStack(spacing: Spacing.xs) {
            HStack {
                Text(timeRange.lowerBound.formatted(.relative(presentation: .named)))
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
                Spacer()
                Text(scrubDate.formatted(date: .abbreviated, time: .standard))
                    .font(Typography.body.weight(.semibold))
                Spacer()
                Text("now")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
            Slider(value: sliderBinding, in: 0...1, label: { Text("Scrub") })
                .accessibilityLabel("Timeline scrub")
                .accessibilityValue(scrubDate.formatted(date: .abbreviated, time: .standard))
        }
        .padding(Spacing.md)
        .liquidGlassPanel()
    }

    private var diffActions: some View {
        HStack {
            Button("Set Diff Anchor") {
                diffAnchorDate = scrubDate
            }
            .buttonStyle(.bordered)
            .accessibilityHint("Marks this point as the 'from' for a diff comparison")
            Spacer()
            if let anchor = diffAnchorDate {
                Button("Diff \(anchor.formatted(date: .omitted, time: .shortened)) → Now") {
                    onDiff(anchor, scrubDate)
                }
                .buttonStyle(.borderedProminent)
            }
        }
    }

    private var restoreAction: some View {
        Button("Restore to Here", role: .destructive) {
            showRestoreConfirm = true
        }
        .buttonStyle(.bordered)
        .accessibilityHint("Restores conversation state to this point. History is preserved.")
    }

    /// Slider value 0.0 → 1.0 maps to timeRange.lowerBound → upperBound.
    private var sliderBinding: Binding<Double> {
        Binding(
            get: {
                let total = timeRange.upperBound.timeIntervalSince(timeRange.lowerBound)
                let elapsed = scrubDate.timeIntervalSince(timeRange.lowerBound)
                return total > 0 ? elapsed / total : 0
            },
            set: { newValue in
                let total = timeRange.upperBound.timeIntervalSince(timeRange.lowerBound)
                let elapsed = total * newValue
                scrubDate = timeRange.lowerBound.addingTimeInterval(elapsed)
                onScrub(scrubDate)
            }
        )
    }
}
