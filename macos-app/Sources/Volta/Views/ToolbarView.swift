//
//  ToolbarView.swift
//  Volta
//
//  Phase 171 — Liquid Glass UI Shell
//
//  Extracted from LiquidGlassShell for reusability across scenes.
//  Renders the four canonical toolbar actions: New Project, New Window,
//  Share, Settings. Each has explicit accessibility labels/hints and
//  keyboard equivalents wired at the scene level.
//
//  Design:
//  - Generic over Project to avoid coupling to SwiftData types in previews
//  - Closures for actions — caller wires to modelContext / openWindow / sheets
//  - Reduce Motion aware (animation skipped when enabled)
//  - Reduce Transparency aware (toolbar material swapped to solid)
//
//  ponytail: closures, not ViewBuilder enums. Composable, testable.
//

import SwiftUI

/// Canonical toolbar for the KiCad Agent app shell.
///
/// Phase 171 — Liquid Glass UI Shell.
/// Satisfies APP-06 (multi-window) and A11Y-03 (labels/hints).
struct ToolbarView: View {
    let projectName: String
    let onNewProject: () -> Void
    let onNewWindow: () -> Void
    let onShare: () -> Void
    let onSettings: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    var body: some View {
        HStack(spacing: Spacing.sm) {
            leadingGroup
            Spacer()
            trailingGroup
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.xs)
        .background(reduceTransparency ? AnyView(Color(nsColor: .windowBackgroundColor)) : AnyView(Color.clear))
        .animation(reduceMotion ? nil : LiquidGlassAnimation.default, value: reduceTransparency)
    }

    /// Leading cluster — file/document actions.
    private var leadingGroup: some View {
        HStack(spacing: Spacing.xs) {
            ToolbarButton(
                label: "New Project",
                systemImage: "plus",
                action: onNewProject,
                accessibilityHint: "Creates a new project in this window"
            )
            ToolbarButton(
                label: "New Window",
                systemImage: "macwindow",
                action: onNewWindow,
                accessibilityHint: "Opens a new project window (cmd+N)"
            )
        }
    }

    /// Trailing cluster — share + settings.
    private var trailingGroup: some View {
        HStack(spacing: Spacing.xs) {
            ToolbarButton(
                label: "Share",
                systemImage: "square.and.arrow.up",
                action: onShare,
                accessibilityHint: "Opens the macOS share sheet for \(projectName)"
            )
            ToolbarButton(
                label: "Settings",
                systemImage: "gearshape",
                action: onSettings,
                accessibilityHint: "Opens provider settings, model configuration, and daemon options"
            )
        }
    }
}

/// Single toolbar button — consistent style + accessibility.
///
/// Phase 171 — Liquid Glass UI Shell (A11Y-03 enforcement).
struct ToolbarButton: View {
    let label: String
    let systemImage: String
    let action: () -> Void
    let accessibilityHint: String

    var body: some View {
        Button(action: action) {
            Label(label, systemImage: systemImage)
        }
        .buttonStyle(.borderless)
        .accessibilityLabel(label)
        .accessibilityHint(accessibilityHint)
        .accessibilityAddTraits(.isButton)
    }
}

/// Liquid Glass animation tokens — spring physics with sane defaults.
///
/// ponytail: One animation, well-tuned. Not a zoo of variants.
enum LiquidGlassAnimation {
    static let `default`: Animation = .spring(response: 0.3, dampingFraction: 0.7)
    static let gentle: Animation = .easeInOut(duration: 0.2)
}

#if DEBUG
#Preview("ToolbarView — Default") {
    ToolbarView(
        projectName: "Distortion Pedal",
        onNewProject: {},
        onNewWindow: {},
        onShare: {},
        onSettings: {}
    )
    .frame(width: 600)
}
#endif
