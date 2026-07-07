//
//  ChatPlaceholderView.swift
//  KiCadAgent
//
//  Phase 161 — App Shell Foundation
//
//  Empty state shown when no project is selected.
//  Hero card prompting user to start their first design.
//

import SwiftUI
import OSLog

/// Empty-state placeholder shown when no project exists or none is selected.
struct ChatPlaceholderView: View {
    /// Closure fired when user taps "Start your first design".
    let onStartFirstDesign: () -> Void

    var body: some View {
        VStack(spacing: Spacing.lg) {
            Spacer()
            heroIcon
            heroText
            ctaButton
            hints
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(Spacing.xxl)
        .background(Color(nsColor: .windowBackgroundColor))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("KiCad Agent — empty state")
    }

    private var heroIcon: some View {
        Image(systemName: "cpu")
            .font(.system(size: 64, weight: .light))
            .foregroundStyle(ColorTokens.action)
            .accessibilityHidden(true)
    }

    private var heroText: some View {
        VStack(spacing: Spacing.sm) {
            Text("Design hardware, conversationally.")
                .font(Typography.hero)
                .multilineTextAlignment(.center)
                .accessibilityAddTraits(.isHeader)
            Text("From idea to manufactured PCB. KiCad Agent guides every step — schematic, layout, DRC, exports.")
                .font(Typography.body)
                .foregroundStyle(ColorTokens.secondaryText)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 480)
        }
    }

    private var ctaButton: some View {
        Button(action: onStartFirstDesign) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "plus.circle.fill")
                Text("Start your first design")
            }
            .font(Typography.heading)
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.sm)
            .background(ColorTokens.action, in: RoundedRectangle(cornerRadius: CornerRadius.standard, style: .continuous))
            .foregroundStyle(.white)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Start your first design")
        .accessibilityHint("Creates a new project and opens the chat shell")
    }

    private var hints: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            ForEach(hintItems, id: \.self) { hint in
                HStack(spacing: Spacing.xs) {
                    Image(systemName: "sparkles")
                        .foregroundStyle(ColorTokens.action)
                        .accessibilityHidden(true)
                    Text(hint)
                        .font(Typography.body)
                        .foregroundStyle(ColorTokens.secondaryText)
                }
            }
        }
        .padding(.top, Spacing.lg)
    }

    /// ponytail: hints are static constants, not generated. SLC.
    private let hintItems: [String] = [
        "Design a distortion pedal for bass guitar",
        "Build an ESP32 breakout with USB-C power",
        "Create a 4-channel audio mixer with headphone amp",
        "Convert an existing .kicad_sch to a managed project"
    ]
}

#if DEBUG
#Preview("Chat Placeholder") {
    ChatPlaceholderView(onStartFirstDesign: {})
}
#endif
