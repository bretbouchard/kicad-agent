//
//  OnboardingFlowView.swift
//  Volta
//
//  Phase 242 — First-run Onboarding
//
//  3-step guided tour for first-time users:
//
//    1. Welcome + pick a starter (LED blinker, ESP32, op-amp preamp)
//    2. Run a chat (chat compose bar pre-fills with the starter's prompt)
//    3. View result + Open in KiCad
//
//  The flow is purely presentational — it doesn't create the
//  project, doesn't talk to the model, and doesn't open KiCad.
//  The parent (AppRootView) provides closures for each side-effect:
//    - onPickStarter: create a Project + open it
//    - onComplete:   mark OnboardingState.completed
//    - onSkip:       mark OnboardingState.dismissed
//
//  State persists across launches via OnboardingState (SwiftData).
//
//  UX rules (per stupid-proof verification):
//    - Skip button is always visible (top-right, doesn't compete
//      with primary CTA).
//    - "Back" is only available after step 1. Step 1 is the entry,
//      no back.
//    - TabView with .page style gives native macOS paging + dot
//      indicator at the bottom.
//

import SwiftUI
import OSLog

/// The 3-step onboarding flow.
struct OnboardingFlowView: View {
    /// Called when the user picks a starter on step 1. The parent
    /// creates the project and switches to it. The starter's prompt
    /// is passed in for the chat compose bar to pre-fill.
    let onPickStarter: (OnboardingStarter) -> Void

    /// Called when the user completes the tour (step 3 "Done").
    let onComplete: () -> Void

    /// Called when the user taps Skip (any step).
    let onSkip: () -> Void

    @State private var currentStep: Int = 0
    @State private var pickedStarter: OnboardingStarter?

    var body: some View {
        VStack(spacing: 0) {
            headerBar
            content
            pageDots
            primaryActionBar
        }
        .frame(maxWidth: 720, maxHeight: 560)
        .background(Color(nsColor: .windowBackgroundColor))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Welcome tour")
    }

    // MARK: - Header

    private var headerBar: some View {
        HStack {
            Text(stepTitle)
                .font(Typography.heading)
                .foregroundStyle(ColorTokens.secondaryText)
            Spacer()
            Button("Skip", action: handleSkip)
                .buttonStyle(.plain)
                .foregroundStyle(ColorTokens.secondaryText)
                .accessibilityLabel("Skip welcome tour")
                .accessibilityHint("Dismisses the tour and lands you on the empty workspace")
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.top, Spacing.md)
        .padding(.bottom, Spacing.sm)
    }

    private var stepTitle: String {
        switch currentStep {
        case 0: return "Step 1 of 3"
        case 1: return "Step 2 of 3"
        case 2: return "Step 3 of 3"
        default: return ""
        }
    }

    // MARK: - Content

    /// Manually render only the active step. We don't use TabView
    /// `.page(indexDisplayMode:)` because that's iOS-only — on macOS
    /// we swap the whole content view, animated.
    @ViewBuilder
    private var content: some View {
        Group {
            switch currentStep {
            case 0: welcomeStep
            case 1: chatStep
            default: resultStep
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .transition(.opacity.combined(with: .move(edge: .trailing)))
        .animation(.easeInOut(duration: 0.2), value: currentStep)
    }

    // MARK: - Step 1: Welcome + pick starter

    private var welcomeStep: some View {
        VStack(spacing: Spacing.lg) {
            VStack(spacing: Spacing.sm) {
                Image(systemName: "hand.wave.fill")
                    .font(.system(size: 56, weight: .light))
                    .foregroundStyle(ColorTokens.action)
                    .accessibilityHidden(true)
                Text("Welcome to KiCad Agent")
                    .font(Typography.hero)
                    .multilineTextAlignment(.center)
                Text("Design real circuit boards by chatting with a local LLM that knows KiCad. Pick a starter to see the end-to-end flow in under a minute.")
                    .font(Typography.body)
                    .foregroundStyle(ColorTokens.secondaryText)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, Spacing.lg)
            }

            VStack(spacing: Spacing.xs) {
                ForEach(OnboardingStarter.all) { starter in
                    starterRow(starter)
                }
            }
            .padding(.horizontal, Spacing.lg)
        }
        .padding(.vertical, Spacing.md)
    }

    @ViewBuilder
    private func starterRow(_ starter: OnboardingStarter) -> some View {
        let isPicked = pickedStarter?.id == starter.id
        Button {
            pickedStarter = starter
        } label: {
            HStack(spacing: Spacing.sm) {
                Image(systemName: starter.iconSystemName)
                    .font(.system(size: 22))
                    .foregroundStyle(isPicked ? ColorTokens.action : ColorTokens.secondaryText)
                    .frame(width: 36)
                VStack(alignment: .leading, spacing: 2) {
                    Text(starter.name)
                        .font(Typography.heading)
                    Text(starter.blurb)
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.secondaryText)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                }
                Spacer()
                Image(systemName: isPicked ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(isPicked ? ColorTokens.action : ColorTokens.tertiaryText)
            }
            .padding(Spacing.sm)
            .background(
                RoundedRectangle(cornerRadius: CornerRadius.standard, style: .continuous)
                    .fill(isPicked
                          ? ColorTokens.action.opacity(0.10)
                          : ColorTokens.secondaryText.opacity(0.04))
            )
            .overlay(
                RoundedRectangle(cornerRadius: CornerRadius.standard, style: .continuous)
                    .strokeBorder(isPicked ? ColorTokens.action : Color.clear, lineWidth: 1.5)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(starter.name) starter")
        .accessibilityHint(starter.blurb)
        .accessibilityAddTraits(isPicked ? [.isButton, .isSelected] : .isButton)
    }

    // MARK: - Step 2: Run a chat

    private var chatStep: some View {
        VStack(spacing: Spacing.lg) {
            VStack(spacing: Spacing.sm) {
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 48, weight: .light))
                    .foregroundStyle(ColorTokens.action)
                    .accessibilityHidden(true)
                Text("Send your first chat")
                    .font(Typography.hero)
                Text("Hit return in the chat box to send the prompt we just filled in. The model will respond token-by-token; the schematic and PCB appear inline as the design firms up.")
                    .font(Typography.body)
                    .foregroundStyle(ColorTokens.secondaryText)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, Spacing.lg)
            }

            if let pickedStarter {
                promptPreview(pickedStarter.prompt)
            }

            VStack(alignment: .leading, spacing: Spacing.xs) {
                TipRow(icon: "wand.and.stars",
                       text: "Edit the prompt if you want — anything that sounds like a hardware intent works.")
                TipRow(icon: "photo.fill.on.rectangle.fill",
                       text: "Drop a reference schematic or photo into the chat with Cmd+V or the paperclip.")
                TipRow(icon: "bolt.fill",
                       text: "First response takes ~5–10s while the model warms up. Subsequent turns are faster.")
            }
            .padding(.horizontal, Spacing.lg)
        }
        .padding(.vertical, Spacing.md)
    }

    private func promptPreview(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text("Pre-filled prompt")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.tertiaryText)
            Text(text)
                .font(Typography.body)
                .padding(Spacing.sm)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: CornerRadius.small, style: .continuous)
                        .fill(ColorTokens.secondaryText.opacity(0.06))
                )
        }
        .padding(.horizontal, Spacing.lg)
    }

    // MARK: - Step 3: View result

    private var resultStep: some View {
        VStack(spacing: Spacing.lg) {
            VStack(spacing: Spacing.sm) {
                Image(systemName: "checkmark.seal.fill")
                    .font(.system(size: 48, weight: .light))
                    .foregroundStyle(ColorTokens.action)
                    .accessibilityHidden(true)
                Text("You're ready")
                    .font(Typography.hero)
                Text("When the response is in, you'll see an inline schematic and PCB render. Hit \"Open in KiCad\" to launch the desktop app and continue editing with full KiCad power.")
                    .font(Typography.body)
                    .foregroundStyle(ColorTokens.secondaryText)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, Spacing.lg)
            }

            VStack(alignment: .leading, spacing: Spacing.xs) {
                TipRow(icon: "rectangle.stack.fill",
                       text: "Projects live in the sidebar — name them, switch between them, export when you're done.")
                TipRow(icon: "questionmark.circle.fill",
                       text: "Stuck? Type any question; the model sees your project and can answer in context.")
                TipRow(icon: "sparkles",
                       text: "Want to skip the tour next time? \"Skip\" persists — no nag.")
            }
            .padding(.horizontal, Spacing.lg)
        }
        .padding(.vertical, Spacing.md)
    }

    // MARK: - Dots

    private var pageDots: some View {
        HStack(spacing: Spacing.xs) {
            ForEach(0..<3, id: \.self) { idx in
                Circle()
                    .fill(idx == currentStep ? ColorTokens.action : ColorTokens.tertiaryText)
                    .frame(width: 8, height: 8)
                    .accessibilityHidden(true)
            }
        }
        .padding(.vertical, Spacing.sm)
        .accessibilityElement()
        .accessibilityLabel("Step \(currentStep + 1) of 3")
    }

    // MARK: - Primary action bar

    @ViewBuilder
    private var primaryActionBar: some View {
        HStack(spacing: Spacing.sm) {
            if currentStep > 0 {
                Button {
                    currentStep -= 1
                } label: {
                    Label("Back", systemImage: "chevron.left")
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("Previous step")
            }
            Spacer()
            primaryActionButton
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.bottom, Spacing.lg)
    }

    @ViewBuilder
    private var primaryActionButton: some View {
        switch currentStep {
        case 0:
            Button {
                handleContinueFromWelcome()
            } label: {
                Label("Continue", systemImage: "chevron.right")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.borderedProminent)
            .disabled(pickedStarter == nil)
            .accessibilityLabel("Continue to chat step")
            .accessibilityHint(pickedStarter == nil
                ? "Pick a starter first"
                : "Continues with \(pickedStarter?.name ?? "starter")")
        case 1:
            Button {
                currentStep = 2
            } label: {
                Label("Got it", systemImage: "checkmark")
            }
            .buttonStyle(.borderedProminent)
            .accessibilityLabel("Continue to result step")
        default:
            Button {
                handleDone()
            } label: {
                Label("Start designing", systemImage: "arrow.right.circle.fill")
            }
            .buttonStyle(.borderedProminent)
            .accessibilityLabel("Start designing with \(pickedStarter?.name ?? "your project")")
        }
    }

    // MARK: - Actions

    private func handleContinueFromWelcome() {
        guard let pickedStarter else { return }
        onPickStarter(pickedStarter)
        currentStep = 1
    }

    private func handleDone() {
        onComplete()
    }

    private func handleSkip() {
        onSkip()
    }
}

// MARK: - Subviews

/// Single bullet row in the tip list (steps 2 and 3).
private struct TipRow: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.xs) {
            Image(systemName: icon)
                .font(.system(size: 14))
                .foregroundStyle(ColorTokens.action)
                .frame(width: 22, alignment: .center)
                .accessibilityHidden(true)
            Text(text)
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(text)
    }
}

#if DEBUG
#Preview("Onboarding Step 1") {
    OnboardingFlowView(
        onPickStarter: { _ in },
        onComplete: {},
        onSkip: {}
    )
}
#endif
