//
//  ComponentProviderSettingsView.swift
//  Volta
//
//  Phase 3.5 — BYOC Settings UI
//
//  SwiftUI Settings UI for component data provider API keys.
//  Mirrors the BYOKSettingsView pattern but for component sources:
//    - Digi-Key V4 (Client ID + Client Secret — OAuth2)
//    - Mouser Search API (API Key — header-based)
//    - Nexar/Octopart (Client ID + Client Secret — OAuth2)
//    - JLCPCB Assembly API (API Key — header-based)
//
//  Local sources that need no credentials (EasyEDA, jlcparts) are
//  shown with status info but no key fields.
//
//  Keys are stored in macOS Keychain via KeychainManager generic credentials.
//

import SwiftUI
import OSLog

/// SwiftUI settings view for component data provider credentials.
///
/// Each provider gets a row with:
///   - Provider name + status badge
///   - SecureField(s) for credential input
///   - Save / Remove buttons
///   - Registration link hint
struct ComponentProviderSettingsView: View {
    private let keychain = KeychainManager()

    // Per-provider editable fields
    @State private var digikeyClientID: String = ""
    @State private var digikeyClientSecret: String = ""
    @State private var mouserAPIKey: String = ""
    @State private var nexarClientID: String = ""
    @State private var nexarClientSecret: String = ""
    @State private var jlcpcbAPIKey: String = ""

    // Status messages
    @State private var statusMessage: String = ""

    var body: some View {
        Form {
            infoSection
            digikeySection
            mouserSection
            nexarSection
            jlcpcbSection
            localSourcesSection
        }
        .formStyle(.grouped)
        .onAppear { reloadFromKeychain() }
    }

    // MARK: - Info

    private var infoSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 4) {
                Text("Bring Your Own Components")
                    .font(.headline)
                Text("Each provider has its own free tier. Add keys for the distributors you use — Volta never proxies or sees your keys. All stored in macOS Keychain.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Digi-Key (OAuth2: Client ID + Secret)

    private var digikeySection: some View {
        Section {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Digi-Key V4")
                        .fontWeight(.medium)
                    Spacer()
                    statusBadge(
                        configured: isDigikeyConfigured,
                        hint: "Pricing, stock, specs, datasheets"
                    )
                }

                SecureField("Client ID", text: $digikeyClientID)
                    .textFieldStyle(.roundedBorder)
                SecureField("Client Secret", text: $digikeyClientSecret)
                    .textFieldStyle(.roundedBorder)

                HStack {
                    Link("Register at api.digikey.com",
                         destination: URL(string: "https://api-portal.digikey.com/")!)
                        .font(.caption)
                    Spacer()
                    Button("Save") { saveDigikey() }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                        .disabled(digikeyClientID.isEmpty || digikeyClientSecret.isEmpty)
                    if isDigikeyConfigured {
                        Button("Remove", role: .destructive) { removeDigikey() }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                    }
                }
            }
        } header: {
            Text("Digi-Key")
        }
    }

    // MARK: - Mouser (API Key)

    private var mouserSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Mouser Search API")
                        .fontWeight(.medium)
                    Spacer()
                    statusBadge(
                        configured: isMouserConfigured,
                        hint: "Backup pricing & stock (500 req/day free)"
                    )
                }

                SecureField("API Key", text: $mouserAPIKey)
                    .textFieldStyle(.roundedBorder)

                HStack {
                    Link("Register at mouser.com/api",
                         destination: URL(string: "https://www.mouser.com/api/")!)
                        .font(.caption)
                    Spacer()
                    Button("Save") { saveMouser() }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                        .disabled(mouserAPIKey.isEmpty)
                    if isMouserConfigured {
                        Button("Remove", role: .destructive) { removeMouser() }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                    }
                }
            }
        } header: {
            Text("Mouser")
        }
    }

    // MARK: - Nexar/Octopart (OAuth2: Client ID + Secret)

    private var nexarSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Octopart (Nexar)")
                        .fontWeight(.medium)
                    Spacer()
                    statusBadge(
                        configured: isNexarConfigured,
                        hint: "Multi-distributor aggregator (500 req/mo free)"
                    )
                }

                SecureField("Client ID", text: $nexarClientID)
                    .textFieldStyle(.roundedBorder)
                SecureField("Client Secret", text: $nexarClientSecret)
                    .textFieldStyle(.roundedBorder)

                HStack {
                    Link("Register at portal.nexar.com",
                         destination: URL(string: "https://portal.nexar.com/")!)
                        .font(.caption)
                    Spacer()
                    Button("Save") { saveNexar() }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                        .disabled(nexarClientID.isEmpty || nexarClientSecret.isEmpty)
                    if isNexarConfigured {
                        Button("Remove", role: .destructive) { removeNexar() }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                    }
                }
            }
        } header: {
            Text("Octopart / Nexar")
        }
    }

    // MARK: - JLCPCB (API Key)

    private var jlcpcbSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("JLCPCB Assembly")
                        .fontWeight(.medium)
                    Spacer()
                    statusBadge(
                        configured: isJlcpcbConfigured,
                        hint: "Assembly data + LCSC mapping (needs application)"
                    )
                }

                SecureField("API Key", text: $jlcpcbAPIKey)
                    .textFieldStyle(.roundedBorder)

                HStack {
                    Link("Apply at api.jlcpcb.com",
                         destination: URL(string: "https://api.jlcpcb.com/")!)
                        .font(.caption)
                    Spacer()
                    Button("Save") { saveJlcpcb() }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                        .disabled(jlcpcbAPIKey.isEmpty)
                    if isJlcpcbConfigured {
                        Button("Remove", role: .destructive) { removeJlcpcb() }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                    }
                }
            }
        } header: {
            Text("JLCPCB Assembly")
        }
    }

    // MARK: - Local Sources (No Keys Needed)

    private var localSourcesSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Text("EasyEDA / JLCPCB Search")
                        .fontWeight(.medium)
                }
                Text("No key needed — uses public API. Already working.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.vertical, 2)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Text("EasyEDA")
                        .fontWeight(.medium)
                }
                Text("No key needed — public web API for CAD models.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.vertical, 2)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    let dbExists = FileManager.default.fileExists(atPath: jlcpartsPath)
                    Image(systemName: dbExists ? "checkmark.circle.fill" : "exclamationmark.circle")
                        .foregroundStyle(dbExists ? .green : .orange)
                    Text("jlcparts Database")
                        .fontWeight(.medium)
                }
                if FileManager.default.fileExists(atPath: jlcpartsPath) {
                    Text("Database found at \(jlcpartsPath)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Database not found. Download from:")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Link("github.com/yaqwsx/jlcparts",
                             destination: URL(string: "https://github.com/yaqwsx/jlcparts")!)
                            .font(.caption)
                        Text("Place at: \(jlcpartsPath)")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
            .padding(.vertical, 2)
        } header: {
            Text("Local Sources (No Key Required)")
        }
    }

    // MARK: - Keychain Operations

    private func reloadFromKeychain() {
        digikeyClientID = (try? keychain.loadCredential(account: "digikey.client_id")) ?? ""
        digikeyClientSecret = (try? keychain.loadCredential(account: "digikey.client_secret")) ?? ""
        mouserAPIKey = (try? keychain.loadCredential(account: "mouser.api_key")) ?? ""
        nexarClientID = (try? keychain.loadCredential(account: "nexar.client_id")) ?? ""
        nexarClientSecret = (try? keychain.loadCredential(account: "nexar.client_secret")) ?? ""
        jlcpcbAPIKey = (try? keychain.loadCredential(account: "jlcpcb.api_key")) ?? ""
    }

    // Digi-Key
    private var isDigikeyConfigured: Bool {
        let id = (try? keychain.loadCredential(account: "digikey.client_id")) ?? ""
        return !id.isEmpty
    }
    private func saveDigikey() {
        try? keychain.storeCredential(digikeyClientID, account: "digikey.client_id")
        try? keychain.storeCredential(digikeyClientSecret, account: "digikey.client_secret")
        Logger.ui.info("BYOC: Digi-Key credentials saved")
    }
    private func removeDigikey() {
        try? keychain.deleteCredential(account: "digikey.client_id")
        try? keychain.deleteCredential(account: "digikey.client_secret")
        digikeyClientID = ""
        digikeyClientSecret = ""
        Logger.ui.info("BYOC: Digi-Key credentials removed")
    }

    // Mouser
    private var isMouserConfigured: Bool {
        let key = (try? keychain.loadCredential(account: "mouser.api_key")) ?? ""
        return !key.isEmpty
    }
    private func saveMouser() {
        try? keychain.storeCredential(mouserAPIKey, account: "mouser.api_key")
        Logger.ui.info("BYOC: Mouser API key saved")
    }
    private func removeMouser() {
        try? keychain.deleteCredential(account: "mouser.api_key")
        mouserAPIKey = ""
        Logger.ui.info("BYOC: Mouser API key removed")
    }

    // Nexar
    private var isNexarConfigured: Bool {
        let id = (try? keychain.loadCredential(account: "nexar.client_id")) ?? ""
        return !id.isEmpty
    }
    private func saveNexar() {
        try? keychain.storeCredential(nexarClientID, account: "nexar.client_id")
        try? keychain.storeCredential(nexarClientSecret, account: "nexar.client_secret")
        Logger.ui.info("BYOC: Nexar credentials saved")
    }
    private func removeNexar() {
        try? keychain.deleteCredential(account: "nexar.client_id")
        try? keychain.deleteCredential(account: "nexar.client_secret")
        nexarClientID = ""
        nexarClientSecret = ""
        Logger.ui.info("BYOC: Nexar credentials removed")
    }

    // JLCPCB
    private var isJlcpcbConfigured: Bool {
        let key = (try? keychain.loadCredential(account: "jlcpcb.api_key")) ?? ""
        return !key.isEmpty
    }
    private func saveJlcpcb() {
        try? keychain.storeCredential(jlcpcbAPIKey, account: "jlcpcb.api_key")
        Logger.ui.info("BYOC: JLCPCB API key saved")
    }
    private func removeJlcpcb() {
        try? keychain.deleteCredential(account: "jlcpcb.api_key")
        jlcpcbAPIKey = ""
        Logger.ui.info("BYOC: JLCPCB API key removed")
    }

    // MARK: - Helpers

    private var jlcpartsPath: String {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".volta/cache/jlcparts.sqlite").path
    }

    @ViewBuilder
    private func statusBadge(configured: Bool, hint: String) -> some View {
        HStack(spacing: 4) {
            Text(configured ? "Configured" : "Not set")
                .font(.caption2)
                .fontWeight(.medium)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background((configured ? Color.green : Color.gray).opacity(0.2))
                .foregroundStyle(configured ? .green : .secondary)
                .clipShape(Capsule())
        }
    }
}
