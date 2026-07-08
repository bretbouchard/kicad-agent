//
//  ProviderRoutingSettingsView.swift
//  KiCadAgent
//
//  Phase 165 — Provider Router
//
//  Settings UI for the task-aware, cost-aware, privacy-aware router.
//  Surfaces three things:
//    1. Privacy Mode toggle + per-task-type preferred-provider pickers (MOD-10)
//    2. Cost ledger summary: today / this week / all-time + per-provider
//       breakdown (MOD-12)
//    3. "Reset to defaults" button + cost-warning-threshold slider (T-165-03)
//
//  Designed to live inside a parent Settings scene (Phase 203 wires the
//  tab). Phase 165 exercises it via #Preview + a smoke test.
//
//  Per A11Y-05/A11Y-06: every control carries accessibilityLabel/Hint.
//  Per APP-07: respects system appearance + Dynamic Type (Semantic fonts).
//

import SwiftUI
import OSLog

/// SwiftUI view for the Provider Routing settings section.
///
/// Holds a strong reference to the `KiCadModelRouter` (which owns the
/// ledger) and mutates `router.preferences` directly — the router is an
/// ObservableObject so SwiftUI re-renders on every change.
struct ProviderRoutingSettingsView: View {
    @ObservedObject var router: KiCadModelRouter
    @State private var showResetConfirm: Bool = false
    @State private var showClearLedgerConfirm: Bool = false

    var body: some View {
        Form {
            privacyModeSection
            perTaskPreferencesSection
            costTrackingSection
            actionsSection
        }
        .formStyle(.grouped)
        .alert("Reset preferences?", isPresented: $showResetConfirm) {
            Button("Reset", role: .destructive) {
                router.resetPreferences()
                Logger.ui.info("Provider routing preferences reset by user")
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("All provider preferences and the privacy-mode toggle return to their defaults. Ledger entries are preserved.")
        }
        .alert("Clear cost ledger?", isPresented: $showClearLedgerConfirm) {
            Button("Clear", role: .destructive) {
                router.ledger.clear()
                Logger.ui.info("Cost ledger cleared by user")
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("All token-usage history will be deleted. This cannot be undone.")
        }
    }

    // MARK: - Privacy Mode

    private var privacyModeSection: some View {
        Section {
            Toggle(isOn: Binding(
                get: { router.preferences.privacyMode },
                set: { newValue in
                    router.preferences.privacyMode = newValue
                    router.persistPreferences()
                    Logger.ui.info("Privacy mode \(newValue ? "ON" : "OFF")")
                }
            )) {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text("Privacy Mode (local-only)")
                        .font(Typography.body)
                    Text("Forces every task to a local provider. Cloud calls are blocked even when API keys are configured.")
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.secondaryText)
                }
            }
            .accessibilityLabel("Privacy mode local-only toggle")
            .accessibilityHint("When on, all model calls run on Apple Intelligence or local MLX. No cloud calls.")
        } header: {
            Text("Privacy")
        }
    }

    // MARK: - Per-task preferences

    private var perTaskPreferencesSection: some View {
        Section {
            // Only the four user-visible categories per MOD-10.
            ForEach(
                [KCTaskType.quickReply, .complexReasoning, .vision, .privacySensitive],
                id: \.self
            ) { taskType in
                taskPreferenceRow(for: taskType)
            }
        } header: {
            Text("Preferred Model per Task Type")
        } footer: {
            Text("Pick a model for each category. Unavailable models fall back to Apple Intelligence with a one-time notification. Privacy-Sensitive is always locked to local.")
                .font(Typography.caption)
        }
    }

    @ViewBuilder
    private func taskPreferenceRow(for taskType: KCTaskType) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            HStack {
                Text(taskType.displayName)
                    .font(Typography.body)
                Spacer()
                kindBadge(for: currentPreference(for: taskType))
            }
            Text(taskType.roleDescription)
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.secondaryText)

            Picker("", selection: Binding(
                get: { currentPreference(for: taskType) },
                set: { newValue in
                    setPreference(newValue, for: taskType)
                }
            )) {
                ForEach(availablePreferenceKinds(for: taskType), id: \.self) { kind in
                    Text(kind.displayName).tag(kind)
                }
            }
            .pickerStyle(.menu)
            .labelsHidden()
            .disabled(taskType == .privacySensitive || router.preferences.privacyMode)
            .accessibilityLabel("Preferred provider for \(taskType.displayName)")
            .accessibilityHint("Selects which provider the router uses for \(taskType.displayName.lowercased()).")
        }
        .padding(.vertical, Spacing.xxs)
    }

    /// Returns the available provider kinds for the picker. Privacy-sensitive
    /// tasks only show local providers (per MOD-02: never cloud).
    private func availablePreferenceKinds(for taskType: KCTaskType) -> [KCProviderKind] {
        let registered = Array(router.providers.keys).sorted { $0.rawValue < $1.rawValue }
        if taskType == .privacySensitive {
            // Local-only — MOD-02 hard rule.
            return registered.filter { $0.isLocal }
        }
        // Everyone available in the registry, plus apple/MLX always shown.
        // ponytail: picker shows what's registered; unavailable selection
        // still triggers fallback notification at route time.
        return registered
    }

    private func currentPreference(for taskType: KCTaskType) -> KCProviderKind {
        router.preferences.preferredProviderPerTask[taskType] ?? .appleLocal
    }

    private func setPreference(_ kind: KCProviderKind, for taskType: KCTaskType) {
        router.preferences.preferredProviderPerTask[taskType] = kind
        router.persistPreferences()
        Logger.ui.info("Provider for \(taskType.rawValue) set to \(kind.rawValue)")
    }

    // MARK: - Kind badge

    @ViewBuilder
    private func kindBadge(for kind: KCProviderKind) -> some View {
        let (label, color) = badgeContent(for: kind)
        Text(label)
            .font(Typography.caption.weight(.medium))
            .foregroundStyle(color)
            .padding(.horizontal, Spacing.xs)
            .padding(.vertical, Spacing.xxs)
            .background(color.opacity(0.1), in: Capsule())
            .accessibilityLabel(label)
    }

    private func badgeContent(for kind: KCProviderKind) -> (String, Color) {
        if kind.isLocal {
            return ("Local · Free", ColorTokens.success)
        }
        return ("Cloud", ColorTokens.action)
    }

    // MARK: - Cost tracking

    private var costTrackingSection: some View {
        Section {
            summaryRow(router.ledger.today)
            summaryRow(router.ledger.thisWeek)
            summaryRow(router.ledger.allTime)

            if !router.ledger.allTime.perProvider.isEmpty {
                Divider()
                Text("Per Provider")
                    .font(Typography.caption.weight(.semibold))
                    .foregroundStyle(ColorTokens.secondaryText)
                ForEach(router.ledger.allTime.perProvider, id: \.providerKind) { totals in
                    perProviderRow(totals)
                }
            }

            if router.ledger.lastEntryExceededThreshold {
                runawaySpendBanner
            }
        } header: {
            Text("Cost Tracking")
        } footer: {
            Text("Cost estimates are computed from each provider's published price-per-token rates. Local providers (Apple Intelligence, MLX) are always free.")
                .font(Typography.caption)
        }
    }

    private func summaryRow(_ summary: KCCostSummary) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(summary.rangeName)
                .font(Typography.body)
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(formattedCost(summary.totalCostUSD))
                    .font(Typography.body.monospacedDigit())
                Text("\(summary.callCount) calls · \(formattedTokens(summary.inputTokens + summary.outputTokens)) tokens")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(summary.rangeName): \(formattedCost(summary.totalCostUSD)) across \(summary.callCount) calls")
    }

    private func perProviderRow(_ totals: KCProviderTotals) -> some View {
        HStack {
            Text(totals.providerKind.displayName)
                .font(Typography.body)
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(formattedCost(totals.totalCostUSD))
                    .font(Typography.body.monospacedDigit())
                Text("\(totals.callCount) calls")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.tertiaryText)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(totals.providerKind.displayName): \(formattedCost(totals.totalCostUSD)) across \(totals.callCount) calls")
    }

    private var runawaySpendBanner: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(ColorTokens.destructive)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("High-cost message detected")
                    .font(Typography.body.weight(.medium))
                Text("A single message exceeded your warning threshold of \(formattedCost(router.preferences.costWarningThresholdUSD)). Consider switching to a local provider for similar tasks.")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.secondaryText)
                Button("Dismiss") {
                    router.ledger.acknowledgeWarning()
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(Spacing.sm)
        .background(ColorTokens.destructive.opacity(0.1), in: RoundedRectangle(cornerRadius: CornerRadius.standard, style: .continuous))
    }

    // MARK: - Actions

    private var actionsSection: some View {
        Section {
            Button(role: .destructive) {
                showResetConfirm = true
            } label: {
                Label("Reset preferences to defaults", systemImage: "arrow.counterclockwise")
            }
            .accessibilityHint("Returns all per-task provider selections and the privacy toggle to defaults.")

            Button(role: .destructive) {
                showClearLedgerConfirm = true
            } label: {
                Label("Clear cost ledger", systemImage: "trash")
            }
            .accessibilityHint("Deletes all token-usage history. Cannot be undone.")
        }
    }

    // MARK: - Formatting helpers

    private func formattedCost(_ value: Decimal) -> String {
        // Decimal → user-facing USD. Use NSDecimalNumber + NumberFormatter so
        // we get correct rounding + currency symbol.
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        let decimalNumber = NSDecimalNumber(decimal: value)
        return formatter.string(from: decimalNumber) ?? "$\(value)"
    }

    private func formattedTokens(_ count: Int) -> String {
        if count >= 1_000_000 {
            return String(format: "%.1fM", Double(count) / 1_000_000)
        }
        if count >= 1_000 {
            return String(format: "%.1fK", Double(count) / 1_000)
        }
        return "\(count)"
    }
}

// MARK: - Previews

#if DEBUG
@MainActor
private func previewRouter(entries: [KCCostEntry] = []) -> KiCadModelRouter {
    let ledger = KCCostLedger()
    for entry in entries { ledger.append(entry) }
    let router = KiCadModelRouter(
        providers: [.appleLocal: AppleLocalProvider()],
        ledger: ledger
    )
    return router
}

#Preview("Default — empty ledger") {
    ProviderRoutingSettingsView(router: previewRouter())
        .frame(width: 600, height: 700)
}

#Preview("With cost history") {
    let entries: [KCCostEntry] = [
        KCCostEntry(providerKind: .appleLocal, taskType: .quickReply, inputTokens: 120, outputTokens: 40, costUSD: 0),
        KCCostEntry(providerKind: .mlxLocal, taskType: .complexReasoning, inputTokens: 580, outputTokens: 920, costUSD: 0),
        KCCostEntry(providerKind: .openAI, taskType: .complexReasoning, inputTokens: 1200, outputTokens: 800, costUSD: 0.084),
        KCCostEntry(providerKind: .openAI, taskType: .vision, inputTokens: 2400, outputTokens: 600, costUSD: 0.108)
    ]
    return ProviderRoutingSettingsView(router: previewRouter(entries: entries))
        .frame(width: 600, height: 700)
}

#Preview("Privacy mode on") {
    let router = previewRouter()
    router.preferences.privacyMode = true
    return ProviderRoutingSettingsView(router: router)
        .frame(width: 600, height: 700)
}
#endif
