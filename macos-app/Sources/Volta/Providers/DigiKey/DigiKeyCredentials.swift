//
//  DigiKeyCredentials.swift
//  Volta
//
//  Phase 1 / Task 2 — Digi-Key V4 Provider
//
//  Loads Digi-Key OAuth2 Client ID + Client Secret from macOS Keychain
//  via the generic credential API (ARCH-P1-04). Digi-Key requires TWO
//  secrets, so the existing KCProviderKind single-key API doesn't fit.
//
//  Fallback: environment variables for development without Keychain access.
//

import Foundation
import OSLog

/// Digi-Key OAuth2 credentials (Client ID + Client Secret).
struct DigiKeyCredentials: Sendable {
    let clientID: String
    let clientSecret: String

    /// Keychain account identifiers for the two Digi-Key secrets.
    static let clientIDAccount = "digikey.client_id"
    static let clientSecretAccount = "digikey.client_secret"

    /// Load credentials from Keychain, falling back to env vars for dev.
    /// Returns nil if neither Keychain nor env vars have both values.
    static func load(from keychain: KeychainManager) -> DigiKeyCredentials? {
        // Try Keychain first.
        // try? flattens optional return — id/secret bind as String, not String?
        if let id = try? keychain.loadCredential(account: clientIDAccount),
           let secret = try? keychain.loadCredential(account: clientSecretAccount),
           !id.isEmpty, !secret.isEmpty {
            return DigiKeyCredentials(clientID: id, clientSecret: secret)
        }

        // Fallback: environment variables (development without Keychain).
        let env = ProcessInfo.processInfo.environment
        if let id = env["DIGIKEY_CLIENT_ID"],
           let secret = env["DIGIKEY_CLIENT_SECRET"],
           !id.isEmpty, !secret.isEmpty {
            Logger.models.info("DigiKey: loaded credentials from env vars (dev mode)")
            return DigiKeyCredentials(clientID: id, clientSecret: secret)
        }

        return nil
    }
}
