//
//  BYOKSettingsView.swift
//  Volta
//
//  Phase 166 — BYOK Keychain Storage
//
//  SwiftUI Settings UI for API key configuration. Per MOD-03:
//    - Per-provider row: name, status badge, key field, Validate + Remove
//    - Validate on Save: makes a real test call, refuses invalid keys
//    - Revoked keys (401/403) trigger a re-entry prompt
//
//  Per MOD-04:
//    - iCloud Keychain sync toggle (default ON)
//    - Toggle OFF shows a warning ("You'll lose keys on device swap")
//
//  Per MOD-05:
//    - All validation calls go DIRECT to the provider via URLSession
//
//  Designed to live inside a parent Settings scene (Phase 203 wires the
//  tab). This view ships #Preview + a smoke test for Phase 166 SLC.
//

import SwiftUI
import OSLog

/// SwiftUI view for the BYOK API key configuration section.
///
/// Holds its own `KeychainManager` (so the view survives router rebuilds)
/// and re-renders when keys change. Per MOD-03: invalid keys are rejected
/// on save via real provider test calls.
struct BYOKSettingsView: View {
    /// Per-provider editable key entry. Bound to SecureField.
    @State private var draftKeys: [KCProviderKind: String] = [:]

    /// Per-provider validation result.
    @State private var validationResults: [KCProviderKind: APIKeyValidationResult] = [:]

    /// Per-provider "validating now" spinner state.
    @State private var isValidating: Set<KCProviderKind> = []

    /// iCloud Keychain sync toggle (default ON).
    @AppStorage(KeychainManager.iCloudSyncDefaultsKey) private var iCloudSyncRaw: Bool = true

    /// Show the iCloud-disable warning sheet.
    @State private var showICloudDisableWarning: Bool = false

    /// Show the re-entry prompt for a revoked key.
    @State private var revokedKeyProvider: KCProviderKind?

    /// "Validate all keys" global progress.
    @State private var isBulkValidating: Bool = false

    /// KeychainManager — test-injectable so previews don't touch the real
    /// Keychain.
    let keychain: KeychainManager
    let validator: APIKeyValidator

    init(
        keychain: KeychainManager = KeychainManager(),
        validator: APIKeyValidator = APIKeyValidator()
    ) {
        self.keychain = keychain
        self.validator = validator
    }

    /// Cloud providers we surface in the UI (skip local-only and mock).
    private static let cloudProviders: [KCProviderKind] = [
        .openAI, .anthropic, .gemini, .groq, .xai, .together, .ollama
    ]

    var body: some View {
        Form {
            headerSection
            keysSection
            iCloudSection
            actionsSection
        }
        .formStyle(.grouped)
        .alert("Revoked key", isPresented: revokedKeyBinding) {
            Button("Re-enter") { revokedKeyProvider = nil }
            Button("Cancel", role: .cancel) { revokedKeyProvider = nil }
        } message: {
            if let kind = revokedKeyProvider {
                Text("Your \(kind.displayName) API key was rejected by the provider (HTTP 401/403). It may have been revoked or expired. Please re-enter a valid key.")
            }
        }
        .sheet(isPresented: $showICloudDisableWarning) {
            iCloudDisableWarningSheet(
                onContinue: {
                    iCloudSyncRaw = false
                    keychain.iCloudSyncEnabled = false
                    keychain.applyICloudSyncSettingToAllKeys()
                    showICloudDisableWarning = false
                },
                onCancel: {
                    // Revert toggle — keep sync ON.
                    iCloudSyncRaw = true
                    showICloudDisableWarning = false
                }
            )
        }
        .onAppear { reloadDrafts() }
    }

    // MARK: - Sections

    private var headerSection: some View {
        Section {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("Bring Your Own Key — cloud models with your keys, your cost.")
                    .font(Typography.body)
                Text("KiCad Agent never proxies API calls. Keys are stored in macOS Keychain (encrypted, optionally iCloud-synced).")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.secondaryText)
            }
        } header: {
            Text("Cloud API Keys")
        } footer: {
            Text("Get keys from: platform.openai.com · console.anthropic.com · aistudio.google.com · console.groq.com · x.ai · api.together.xyz")
                .font(Typography.caption)
        }
    }

    private var keysSection: some View {
        Section {
            ForEach(Self.cloudProviders, id: \.self) { kind in
                providerRow(for: kind)
            }
        } header: {
            Text("Providers")
        }
    }

    @ViewBuilder
    private func providerRow(for kind: KCProviderKind) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            HStack(spacing: Spacing.sm) {
                Text(kind.displayName)
                    .font(Typography.body.weight(.medium))
                Spacer()
                statusBadge(for: kind)
            }

            if kind == .ollama {
                // Ollama needs no key — show URL hint instead.
                Text("Local daemon at http://localhost:11434 — no API key required.")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.secondaryText)
            } else {
                SecureField("Paste \(kind.displayName) key", text: binding(for: kind))
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("\(kind.displayName) API key field")
                    .accessibilityHint("Paste your \(kind.displayName) key here. Format-checked on save.")

                HStack(spacing: Spacing.xs) {
                    Button("Save") {
                        Task { await saveKey(for: kind) }
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                    .disabled(draftKeys[kind]?.isEmpty ?? true)

                    Button("Test") {
                        Task { await validateKey(for: kind) }
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(draftKeys[kind]?.isEmpty ?? true)

                    if isValidating.contains(kind) {
                        ProgressView().controlSize(.small)
                    }

                    if let result = validationResults[kind] {
                        Text(result.userMessage)
                            .font(Typography.caption)
                            .foregroundStyle(resultColor(result))
                            .lineLimit(2)
                    }

                    if hasStoredKey(for: kind) {
                        Button("Remove", role: .destructive) {
                            removeKey(for: kind)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                }
            }
        }
        .padding(.vertical, Spacing.xxs)
    }

    private var iCloudSection: some View {
        Section {
            Toggle(isOn: Binding(
                get: { iCloudSyncRaw },
                set: { newValue in
                    if newValue == false {
                        // Per MOD-04: warn before disabling.
                        showICloudDisableWarning = true
                    } else {
                        iCloudSyncRaw = true
                        keychain.iCloudSyncEnabled = true
                        keychain.applyICloudSyncSettingToAllKeys()
                    }
                }
            )) {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text("Sync API keys via iCloud Keychain")
                        .font(Typography.body)
                    Text("Default ON — keys sync to your other Macs. Disabling means you'll lose keys on device swap.")
                        .font(Typography.caption)
                        .foregroundStyle(ColorTokens.secondaryText)
                }
            }
            .accessibilityLabel("iCloud Keychain sync toggle")
            .accessibilityHint("When ON, API keys sync across your Macs. Disabling shows a warning.")
        } header: {
            Text("iCloud Sync")
        }
    }

    private var actionsSection: some View {
        Section {
            Button {
                Task { await validateAll() }
            } label: {
                if isBulkValidating {
                    HStack {
                        ProgressView().controlSize(.small)
                        Text("Validating all keys…")
                    }
                } else {
                    Label("Validate all keys", systemImage: "checkmark.seal")
                }
            }
            .disabled(isBulkValidating || keychain.configuredProviders().isEmpty)
            .accessibilityHint("Runs a test call against each configured provider to verify keys still work.")
        }
    }

    // MARK: - Actions

    private func reloadDrafts() {
        for kind in Self.cloudProviders where kind != .ollama {
            if let stored = try? keychain.loadAPIKey(for: kind) {
                draftKeys[kind] = stored
            }
        }
    }

    private func saveKey(for kind: KCProviderKind) async {
        guard let key = draftKeys[kind], !key.isEmpty else { return }
        // Per MOD-03: validate via real call BEFORE storing.
        isValidating.insert(kind)
        defer { isValidating.remove(kind) }
        let result = await validator.validate(provider: kind, key: key)
        validationResults[kind] = result
        switch result {
        case .valid:
            do {
                try keychain.storeAPIKey(key, for: kind)
                Logger.ui.info("BYOK key saved for \(kind.rawValue) after validation passed")
            } catch {
                validationResults[kind] = .invalid(reason: error.localizedDescription)
            }
        case .invalid:
            // Per MOD-03: revoked/invalid key → trigger re-entry prompt.
            revokedKeyProvider = kind
        case .networkError:
            // Don't save — network issue. Let user retry.
            break
        }
    }

    private func validateKey(for kind: KCProviderKind) async {
        guard let key = draftKeys[kind], !key.isEmpty else { return }
        isValidating.insert(kind)
        defer { isValidating.remove(kind) }
        let result = await validator.validate(provider: kind, key: key)
        validationResults[kind] = result
        // If validating a stored key reveals it's revoked, prompt re-entry.
        if case .invalid = result, hasStoredKey(for: kind) {
            revokedKeyProvider = kind
        }
    }

    private func removeKey(for kind: KCProviderKind) {
        try? keychain.deleteAPIKey(for: kind)
        draftKeys[kind] = ""
        validationResults.removeValue(forKey: kind)
        Logger.ui.info("BYOK key removed for \(kind.rawValue)")
    }

    private func validateAll() async {
        isBulkValidating = true
        defer { isBulkValidating = false }
        for kind in keychain.configuredProviders() where kind != .ollama {
            guard let key = try? keychain.loadAPIKey(for: kind) else { continue }
            isValidating.insert(kind)
            let result = await validator.validate(provider: kind, key: key)
            validationResults[kind] = result
            isValidating.remove(kind)
            if case .invalid = result {
                revokedKeyProvider = kind
            }
        }
    }

    // MARK: - Helpers

    private func binding(for kind: KCProviderKind) -> Binding<String> {
        Binding(
            get: { draftKeys[kind] ?? "" },
            set: { draftKeys[kind] = $0 }
        )
    }

    private var revokedKeyBinding: Binding<Bool> {
        Binding(
            get: { revokedKeyProvider != nil },
            set: { newValue in if !newValue { revokedKeyProvider = nil } }
        )
    }

    private func hasStoredKey(for kind: KCProviderKind) -> Bool {
        (try? keychain.loadAPIKey(for: kind))?.isEmpty == false
    }

    @ViewBuilder
    private func statusBadge(for kind: KCProviderKind) -> some View {
        if kind == .ollama {
            Text("Local · Free")
                .font(Typography.caption.weight(.medium))
                .foregroundStyle(ColorTokens.success)
        } else if hasStoredKey(for: kind) {
            if let result = validationResults[kind] {
                switch result {
                case .valid:
                    badge("Configured", color: ColorTokens.success)
                case .invalid:
                    badge("Invalid", color: ColorTokens.destructive)
                case .networkError:
                    badge("Network issue", color: ColorTokens.warning)
                }
            } else {
                badge("Configured", color: ColorTokens.success)
            }
        } else {
            badge("Not set", color: ColorTokens.tertiaryText)
        }
    }

    @ViewBuilder
    private func badge(_ text: String, color: Color) -> some View {
        Text(text)
            .font(Typography.caption.weight(.medium))
            .foregroundStyle(color)
            .padding(.horizontal, Spacing.xs)
            .padding(.vertical, Spacing.xxs)
            .background(color.opacity(0.1), in: Capsule())
    }

    private func resultColor(_ result: APIKeyValidationResult) -> Color {
        switch result {
        case .valid: return ColorTokens.success
        case .invalid: return ColorTokens.destructive
        case .networkError: return ColorTokens.warning
        }
    }
}

// MARK: - iCloud disable warning sheet

private struct iCloudDisableWarningSheet: View {
    let onContinue: () -> Void
    let onCancel: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(ColorTokens.warning)
                    .font(.title2)
                Text("Disable iCloud Keychain sync?")
                    .font(Typography.body.weight(.semibold))
            }
            Text("You'll lose keys on device swap. Each Mac you own will need its own set of API keys added manually.")
                .font(Typography.body)
            Text("If you only use KiCad Agent on this Mac, disabling is fine. Keys remain in your local Keychain (encrypted at rest).")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.secondaryText)
            HStack {
                Button("Cancel", action: onCancel)
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button("Disable anyway", role: .destructive, action: onContinue)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding()
        .frame(width: 460)
    }
}

// MARK: - Previews

#if DEBUG
#Preview("Default — empty") {
    BYOKSettingsView()
        .frame(width: 700, height: 800)
}

#Preview("With test keychain") {
    // ponytail: test service identifier so the preview never touches the
    // user's real Keychain.
    let kc = KeychainManager(service: "com.bretbouchard.kicad-agent.preview")
    return BYOKSettingsView(keychain: kc)
        .frame(width: 700, height: 800)
}
#endif
