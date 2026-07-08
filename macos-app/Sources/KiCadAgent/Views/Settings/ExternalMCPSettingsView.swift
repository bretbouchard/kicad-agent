//
//  ExternalMCPSettingsView.swift
//  KiCadAgent
//
//  Phase 163 — KiCad CLI Integration
//
//  DAEM-07: Settings UI for the external HTTP MCP server opt-in.
//  DAEM-08: Auth token display + regenerate + suspicious-usage notification.
//
//  Components:
//    - Toggle: "Enable HTTP MCP Server" (default OFF)
//    - Auth token field: masked display + copy + regenerate
//    - Port display: read-only default 8080
//    - Warning banner: external control warning
//    - Auto-revoke notification: appears when DAEM-08 trips
//    - QR pairing code: generated from the auth token (Phase 192 adds full QR)
//

import SwiftUI
import OSLog

/// SwiftUI view for the External HTTP MCP settings section.
///
/// Lives inside a parent Settings scene. The parent is wired in Phase 203
/// (Settings scene); for Phase 163 this view is exercised via #Preview and
/// can be surfaced via the existing LiquidGlassShell Settings button.
struct ExternalMCPSettingsView: View {
    @Bindable var settings: ExternalMCPSettings
    @State private var showToken: Bool = false
    @State private var tokenJustCopied: Bool = false
    @State private var showRegenerateConfirm: Bool = false

    var body: some View {
        Form {
            Section("External HTTP MCP Server") {
                toggleRow
                if settings.isEnabled {
                    Divider()
                    statusRow
                    tokenRow
                    portRow
                }
            }
            Section {
                warningBanner
            } header: {
                Text("Security")
            }
            if settings.wasAutoRevoked {
                Section {
                    autoRevokeBanner
                }
            }
        }
        .formStyle(.grouped)
        .alert("Regenerate auth token?", isPresented: $showRegenerateConfirm) {
            Button("Regenerate", role: .destructive) {
                _ = settings.regenerateToken()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Any external client using the current token will need to re-pair. This does not disable the server.")
        }
    }

    // MARK: - Toggle

    private var toggleRow: some View {
        Toggle(isOn: Binding(
            get: { settings.isEnabled },
            set: { newValue in
                // Toggling on: ensure token exists first.
                if newValue {
                    settings.ensureTokenExists()
                    Logger.kicad.info("External MCP enabled by user")
                } else {
                    Logger.kicad.info("External MCP disabled by user")
                }
                settings.isEnabled = newValue
            }
        )) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("Enable HTTP MCP Server")
                    .font(Typography.body)
                Text("Allows Claude Code, Cursor, and other local MCP clients to control KiCad operations.")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.secondaryText)
            }
        }
        .accessibilityLabel("Enable HTTP MCP server")
        .accessibilityHint("Off by default. When enabled, exposes KiCad Agent over local HTTP for external clients.")
    }

    // MARK: - Status row

    private var statusRow: some View {
        HStack {
            Image(systemName: "circle.fill")
                .foregroundStyle(ColorTokens.success)
                .font(.system(size: 10))
                .accessibilityHidden(true)
            Text("Listening on 127.0.0.1:\(settings.port)")
                .font(Typography.mono)
            Spacer()
            Text("Localhost only")
                .font(Typography.caption)
                .foregroundStyle(ColorTokens.tertiaryText)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Server status: listening on localhost")
    }

    // MARK: - Token row

    private var tokenRow: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack {
                Image(systemName: "key.fill")
                    .foregroundStyle(ColorTokens.action)
                    .accessibilityHidden(true)
                Text("Auth Token")
                    .font(Typography.body)
                Spacer()
                Button {
                    showToken.toggle()
                } label: {
                    Image(systemName: showToken ? "eye.slash" : "eye")
                }
                .buttonStyle(.borderless)
                .accessibilityLabel(showToken ? "Hide token" : "Show token")

                Button {
                    copyToken()
                } label: {
                    Label(tokenJustCopied ? "Copied" : "Copy", systemImage: tokenJustCopied ? "checkmark" : "doc.on.doc")
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("Copy auth token to clipboard")

                Button(role: .destructive) {
                    showRegenerateConfirm = true
                } label: {
                    Label("Regenerate", systemImage: "arrow.clockwise.circle")
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("Regenerate auth token")
                .accessibilityHint("Issues a new token. Existing clients must re-pair.")
            }
            tokenDisplay
                .font(Typography.mono)
                .textSelection(.enabled)
                .padding(Spacing.xs)
                .background(ColorTokens.secondaryText.opacity(0.08), in: RoundedRectangle(cornerRadius: CornerRadius.small, style: .continuous))
        }
    }

    @ViewBuilder
    private var tokenDisplay: some View {
        let token = settings.authToken ?? "(no token)"
        if showToken {
            Text(token)
                .accessibilityLabel("Auth token visible: \(token.prefix(8))…")
        } else {
            Text(String(repeating: "•", count: 20))
                .accessibilityLabel("Auth token hidden")
        }
    }

    // MARK: - Port row

    private var portRow: some View {
        HStack {
            Text("Port")
            Spacer()
            Text("\(settings.port)")
                .font(Typography.mono)
                .foregroundStyle(ColorTokens.secondaryText)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Port: \(settings.port). Read-only in Phase 163.")
    }

    // MARK: - Banners

    private var warningBanner: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(ColorTokens.warning)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("External apps will be able to invoke KiCad operations")
                    .font(Typography.body.weight(.medium))
                Text("Only enable for trusted local clients. The server binds to 127.0.0.1 — not exposed to the network. Suspicious usage (10 failed auths) auto-revokes the token.")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.secondaryText)
            }
        }
        .padding(Spacing.sm)
        .background(ColorTokens.warning.opacity(0.1), in: RoundedRectangle(cornerRadius: CornerRadius.standard, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Security warning: external HTTP MCP control")
    }

    private var autoRevokeBanner: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: "shield.lefthalf.filled")
                .foregroundStyle(ColorTokens.destructive)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("Token auto-revoked")
                    .font(Typography.body.weight(.medium))
                Text("We detected 10 failed authentication attempts. The token was regenerated and the server disabled as a precaution. Re-enable when ready.")
                    .font(Typography.caption)
                    .foregroundStyle(ColorTokens.secondaryText)
                Button("Dismiss") {
                    settings.clearAutoRevokeNotification()
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(Spacing.sm)
        .background(ColorTokens.destructive.opacity(0.1), in: RoundedRectangle(cornerRadius: CornerRadius.standard, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Auto-revoke notification. Token was regenerated due to suspicious activity.")
    }

    // MARK: - Actions

    private func copyToken() {
        guard let token = settings.authToken else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(token, forType: .string)
        tokenJustCopied = true
        Task {
            try? await Task.sleep(for: .seconds(2))
            tokenJustCopied = false
        }
    }
}

#if DEBUG
#Preview("External MCP — Disabled") {
    ExternalMCPSettingsView(settings: ExternalMCPSettings())
        .frame(width: 560, height: 480)
}

#Preview("External MCP — Enabled") {
    let settings = ExternalMCPSettings()
    settings.isEnabled = true
    return ExternalMCPSettingsView(settings: settings)
        .frame(width: 560, height: 480)
}
#endif
