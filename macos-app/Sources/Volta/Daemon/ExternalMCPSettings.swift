//
//  ExternalMCPSettings.swift
//  Volta
//
//  Phase 163 — KiCad CLI Integration
//
//  DAEM-07: User can opt-in to external HTTP MCP server (for Claude Code,
//  Cursor, scripts) via Settings toggle (default off).
//
//  DAEM-08: External HTTP MCP requires auth token (regenerable, shown via
//  QR for pairing). Suspicious usage patterns (10x failed auth) auto-revoke
//  token + notify user.
//
//  Persisted to UserDefaults so the user's choice survives app relaunch.
//  Token lives in macOS Keychain (DAEM-08 token theft mitigation T-163-06).
//

import Foundation
import OSLog

/// Persisted user preferences for the external HTTP MCP server.
///
/// Default state: OFF (DAEM-07). User must explicitly toggle on.
@MainActor
@Observable
final class ExternalMCPSettings {
    /// User-visible enable flag. Persisted to UserDefaults.
    /// Default: false (opt-in per DAEM-07).
    var isEnabled: Bool {
        get { UserDefaults.standard.bool(forKey: Self.enabledKey) }
        set {
            UserDefaults.standard.set(newValue, forKey: Self.enabledKey)
            Logger.kicad.info("External MCP enabled=\(newValue, privacy: .public)")
        }
    }

    /// HTTP port the daemon binds to when enabled. Default 8080.
    /// ponytail: stored as Int; we don't need a custom Port type for v1.
    var port: Int {
        get {
            let stored = UserDefaults.standard.integer(forKey: Self.portKey)
            return stored == 0 ? Self.defaultPort : stored
        }
        set { UserDefaults.standard.set(newValue, forKey: Self.portKey) }
    }

    /// Number of consecutive failed auth attempts.
    /// DAEM-08: at 10+, token is auto-revoked.
    /// Reset to 0 on successful auth or token regen.
    private(set) var failedAuthCount: Int = 0

    /// True when failedAuthCount has crossed the auto-revoke threshold.
    /// UI surfaces a notification banner when this becomes true.
    private(set) var wasAutoRevoked: Bool = false

    /// Reset failedAuthCount / wasAutoRevoked after user dismisses notification.
    func clearAutoRevokeNotification() {
        wasAutoRevoked = false
    }

    /// Increment failed-auth counter. Auto-revokes at threshold (DAEM-08).
    /// Called by the daemon messenger when it sees a 401 from the HTTP server.
    func recordFailedAuth() {
        failedAuthCount += 1
        Logger.kicad.warning("External MCP failed auth #\(self.failedAuthCount)")
        if failedAuthCount >= Self.autoRevokeThreshold {
            Logger.kicad.error("External MCP auto-revoke threshold reached — token disabled")
            // Revoke: rotate the token AND disable the server.
            regenerateToken()
            isEnabled = false
            wasAutoRevoked = true
        }
    }

    /// Reset counter on successful auth.
    func recordSuccessfulAuth() {
        if failedAuthCount > 0 {
            Logger.kicad.info("External MCP auth recovered after \(self.failedAuthCount) failures")
        }
        failedAuthCount = 0
    }

    // MARK: - Token management

    /// Current auth token. Generated on first access. Stored in Keychain.
    /// Returns nil if Keychain access fails (rare; app should handle gracefully).
    var authToken: String? {
        KeychainHelper.shared.read(service: Self.tokenService, account: Self.tokenAccount)
    }

    /// Generate a new random 32-byte URL-safe base64 token. Replaces the old one.
    /// Returns the new token so the UI can display it / generate a QR code.
    @discardableResult
    func regenerateToken() -> String? {
        var bytes = [UInt8](repeating: 0, count: 32)
        let status = SecRandomCopyBytes(kSecRandomDefault, 32, &bytes)
        guard status == errSecSuccess else {
            Logger.kicad.error("Token generation failed — SecRandomCopyBytes status=\(status)")
            return nil
        }
        let token = Data(bytes).base64URLEncodedString()
        let ok = KeychainHelper.shared.write(
            service: Self.tokenService,
            account: Self.tokenAccount,
            value: token
        )
        guard ok else {
            Logger.kicad.error("Token generation failed — Keychain write failed")
            return nil
        }
        // Reset failure counter — new token invalidates prior brute-force attempts.
        failedAuthCount = 0
        Logger.kicad.info("External MCP token regenerated")
        return token
    }

    /// Ensure a token exists. Called on app launch.
    /// If no token exists, generate one (but keep isEnabled = false until user opts in).
    func ensureTokenExists() {
        if authToken == nil {
            _ = regenerateToken()
        }
    }

    // MARK: - Constants

    static let defaultPort = 8080
    static let autoRevokeThreshold = 10

    private static let enabledKey = "external_mcp.enabled"
    private static let portKey = "external_mcp.port"
    private static let tokenService = "com.kicadagent.app.external_mcp"
    private static let tokenAccount = "auth_token"
}

// MARK: - Base64URL

extension Data {
    /// RFC 4648 base64url encoding (URL-safe). Tokens go in HTTP headers and
    /// QR codes — standard base64's `+`/`/`/`=` are problematic.
    func base64URLEncodedString() -> String {
        let standard = base64EncodedString()
        return standard
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

// MARK: - Keychain helper

/// Thin wrapper over macOS Keychain. Used for storing the auth token so it
/// survives app relaunch and is protected by the user's login keychain.
/// ponytail: one tiny class, not a framework.
final class KeychainHelper: @unchecked Sendable {
    static let shared = KeychainHelper()
    private init() {}

    @discardableResult
    func write(service: String, account: String, value: String) -> Bool {
        guard let data = value.data(using: .utf8) else { return false }
        // Delete existing first — Keychain otherwise appends.
        let deleteQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(deleteQuery as CFDictionary)

        let addQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: data,
            // Don't sync via iCloud Keychain for the auth token — it's
            // device-scoped. (User can re-pair on each device.)
            kSecAttrSynchronizable as String: kCFBooleanFalse as Any,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        let status = SecItemAdd(addQuery as CFDictionary, nil)
        return status == errSecSuccess
    }

    func read(service: String, account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    @discardableResult
    func delete(service: String, account: String) -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        let status = SecItemDelete(query as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }
}
