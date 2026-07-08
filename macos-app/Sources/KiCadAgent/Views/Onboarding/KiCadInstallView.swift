//
//  KiCadInstallView.swift
//  KiCadAgent
//
//  Phase 163 — KiCad CLI Integration
//
//  Onboarding sheet shown when KiCad is not installed or wrong version.
//  Per APP-04 augmentation: "App cannot start main workflow without KiCad;
//  shows dedicated onboarding screen with one-tap install link."
//
//  Three states:
//    - .notInstalled: prompt user to download + install KiCad 10+
//    - .wrongVersion(found:): tell user to upgrade from < 10
//    - .ready: not shown — main workflow proceeds
//
//  Buttons:
//    - "Download KiCad" → opens https://www.kicad.org/download/macos/
//    - "I've installed KiCad — check again" → re-runs detect()
//    - "Quit" → exits the app (no way to proceed without KiCad)
//

import SwiftUI
import OSLog

/// SwiftUI sheet shown when KiCad CLI is not detected or wrong version.
///
/// Used by AppRootView as a `.sheet` modifier. Receives a binding to the
/// detector so it can trigger re-detection and observe status changes.
struct KiCadInstallView: View {
    /// Detector shared with AppRootView. Drives the onboarding state.
    @Bindable var detector: KiCadCLIDetector

    /// Closure called when user clicks "Quit".
    let onQuit: () -> Void

    /// Closure called when KiCad is detected and onboarding should dismiss.
    /// In practice the parent view dismisses via sheet binding when status
    /// becomes `.ready`; this closure lets the parent perform any cleanup.
    let onReady: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var isRechecking = false

    var body: some View {
        VStack(spacing: Spacing.lg) {
            headerIcon
            titleSection
            bodyExplanation
            Divider().opacity(0.2)
            actionButtons
            if let lastChecked = detector.lastCheckedAt {
                Text("Last checked \(lastChecked.formatted(.relative(presentation: .named)))")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
                    .accessibilityLabel("Last checked \(lastChecked.formatted(.relative(presentation: .named)))")
            }
        }
        .padding(Spacing.xl)
        .frame(maxWidth: 560, minHeight: 480)
        .background(Color(nsColor: .windowBackgroundColor))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("KiCad install required")
        .onChange(of: detector.status) { _, newStatus in
            // Auto-dismiss when kicad-cli becomes ready.
            if newStatus.isReady {
                onReady()
                dismiss()
            }
        }
    }

    // MARK: - Header

    private var headerIcon: some View {
        Image(systemName: statusIconName)
            .font(.system(size: 64, weight: .light))
            .foregroundStyle(ColorTokens.action)
            .accessibilityHidden(true)
    }

    private var statusIconName: String {
        switch detector.status {
        case .notInstalled: return "exclamationmark.triangle"
        case .wrongVersion: return "arrow.up.circle"
        case .ready: return "checkmark.circle.fill"
        }
    }

    // MARK: - Title

    private var titleSection: some View {
        VStack(spacing: Spacing.sm) {
            Text(titleText)
                .font(Typography.hero)
                .multilineTextAlignment(.center)
                .accessibilityAddTraits(.isHeader)
            Text(subtitleText)
                .font(Typography.body)
                .foregroundStyle(ColorTokens.secondaryText)
                .multilineTextAlignment(.center)
        }
    }

    private var titleText: String {
        switch detector.status {
        case .notInstalled: return "KiCad 10+ Required"
        case .wrongVersion(let v): return "KiCad \(v) is too old"
        case .ready: return "KiCad Ready"
        }
    }

    private var subtitleText: String {
        switch detector.status {
        case .notInstalled:
            return "KiCad Agent needs the external KiCad CLI to run ERC, DRC, render PCBs, and export manufacturing files. KiCad is not bundled (GPLv3)."
        case .wrongVersion(let v):
            return "KiCad Agent needs KiCad 10 or newer. You have \(v). Please upgrade from kicad.org."
        case .ready:
            return "KiCad is installed and ready."
        }
    }

    // MARK: - Explanation

    private var bodyExplanation: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            ExplanationRow(
                icon: "checkmark.shield",
                text: "KiCad Agent never bundles KiCad — your install belongs to you."
            )
            ExplanationRow(
                icon: "wrench.and.screwdriver",
                text: "Once KiCad is installed, click 'Check again' — we'll detect it automatically."
            )
            ExplanationRow(
                icon: "hand.raised.slash",
                text: "Without KiCad, the app cannot validate schematics or export PCBs."
            )
        }
        .padding(Spacing.md)
        .background(ColorTokens.secondaryText.opacity(0.08), in: RoundedRectangle(cornerRadius: CornerRadius.standard, style: .continuous))
    }

    // MARK: - Actions

    private var actionButtons: some View {
        VStack(spacing: Spacing.sm) {
            Button(action: openDownloadPage) {
                Label("Download KiCad from kicad.org", systemImage: "arrow.down.circle.fill")
                    .font(Typography.heading)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Spacing.sm)
            }
            .buttonStyle(.borderedProminent)
            .accessibilityLabel("Download KiCad from kicad.org")
            .accessibilityHint("Opens the official KiCad download page in your default browser")

            Button {
                Task { await recheckNow() }
            } label: {
                if isRechecking {
                    HStack(spacing: Spacing.xs) {
                        ProgressView()
                            .controlSize(.small)
                        Text("Checking…")
                    }
                } else {
                    Label("I've installed KiCad — check again", systemImage: "arrow.clockwise")
                }
            }
            .buttonStyle(.bordered)
            .disabled(isRechecking)
            .accessibilityLabel("Re-check KiCad install")
            .accessibilityHint("Re-runs detection. Auto-detects KiCad on success.")

            Button(role: .destructive, action: onQuit) {
                Text("Quit KiCad Agent")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.plain)
            .foregroundStyle(ColorTokens.destructive)
            .accessibilityLabel("Quit KiCad Agent")
            .accessibilityHint("Exits the app. You cannot proceed without KiCad.")
        }
    }

    // MARK: - Actions

    private func openDownloadPage() {
        Logger.ui.info("Onboarding: opening KiCad download page")
        NSWorkspace.shared.open(KiCadCLIDetector.downloadURL)
    }

    private func recheckNow() async {
        guard !isRechecking else { return }
        isRechecking = true
        defer { isRechecking = false }
        // Kick off a fresh detect. If user just installed, this finds it.
        await detector.detect()
        // If still not installed, optionally start the auto-poll for 30s
        // so the user doesn't have to keep clicking "check again".
        if !detector.status.isReady {
            Logger.ui.info("Onboarding: starting auto-poll for 30s after manual recheck")
            Task {
                let result = await detector.autoDetectAfterInstall(
                    interval: .seconds(3),
                    timeout: .seconds(30)
                )
                Logger.ui.info("Onboarding: auto-poll finished — \(result.debugDescription, privacy: .public)")
            }
        }
    }
}

// MARK: - Subviews

/// Single row in the explanation panel.
private struct ExplanationRow: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: icon)
                .font(Typography.body)
                .foregroundStyle(ColorTokens.action)
                .frame(width: 24, alignment: .center)
                .accessibilityHidden(true)
            Text(text)
                .font(Typography.body)
                .foregroundStyle(ColorTokens.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(text)
    }
}

#if DEBUG
#Preview("Not Installed") {
    let detector = KiCadCLIDetector(runner: StubRunner.notInstalled)
    return KiCadInstallView(
        detector: detector,
        onQuit: {},
        onReady: {}
    )
}

#Preview("Wrong Version") {
    let detector = KiCadCLIDetector(runner: StubRunner.wrongVersion)
    return KiCadInstallView(
        detector: detector,
        onQuit: {},
        onReady: {}
    )
}

#Preview("Ready") {
    let detector = KiCadCLIDetector(runner: StubRunner.ready)
    return KiCadInstallView(
        detector: detector,
        onQuit: {},
        onReady: {}
    )
}

/// Preview-only stub runner that returns a canned status without going async.
private final class StubRunner: ProcessRunner, @unchecked Sendable {
    let cannedStatus: KiCadInstallStatus

    init(cannedStatus: KiCadInstallStatus) {
        self.cannedStatus = cannedStatus
    }

    func run(executable: String, arguments: [String]) async throws -> ProcessResult {
        throw KiCadDetectorError.spawnFailed(reason: "stub")
    }

    static let notInstalled = StubRunner(cannedStatus: .notInstalled)
    static let wrongVersion = StubRunner(cannedStatus: .wrongVersion(found: "9.0.2"))
    static let ready = StubRunner(cannedStatus: .ready(path: "/usr/local/bin/kicad-cli", version: "10.0.3"))
}
#endif
