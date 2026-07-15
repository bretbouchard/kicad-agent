//
//  KeychainManager.swift
//  Volta
//
//  Phase 166 — BYOK Keychain Storage
//
//  Wraps Security.framework for secure API key storage. Per MOD-04 locked
//  decision: API keys live in macOS Keychain with iCloud Keychain sync ON
//  by default (user can opt OUT via Settings toggle, warned on disable).
//
//  Per MOD-03: invalid keys detected via test call before storage (caller
//  invokes APIKeyValidator first; KeychainManager only stores keys that
//  pass).
//  Per MOD-05: pure BYOK — keys never flow through developer infrastructure.
//  Direct URLSession calls to provider endpoints (no proxy).
//
//  Security shape:
//    - kSecClassGenericPassword: API keys are secrets, not certificates.
//    - kSecAttrSynchronizable: true → iCloud Keychain (default). Setting
//      to false means device-local only.
//    - kSecAttrAccessible: when iCloud sync is ON we MUST use an attribute
//      that permits sync (`kSecAttrAccessibleWhenUnlocked` or
//      `kSecAttrAccessibleAfterFirstUnlock`). The `*ThisDeviceOnly`
//      variants suppress sync entirely. We pick `kSecAttrAccessibleAfterFirstUnlock`
//      for synced items so background daemon recovery can read keys without
//      a fresh unlock; `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` for
//      device-local items (stricter).
//    - Service identifier scoping: `com.bretbouchard.volta` so our
//      keys never collide with other apps' Keychain entries.
//    - Per-provider account identifiers: `apiKey.anthropic`, etc.
//
//  Concurrency: Security.framework calls are thread-safe; we wrap in a
//  dedicated Sendable class with no mutable state. Pure value-type helper
//  otherwise.
//
//  Per T-166-01: API keys are never logged. Errors surface the OSStatus
//  code but not the key.
//

import Foundation
import Security
import OSLog

/// Errors thrown by `KeychainManager`. Exhaustive + localized so the
/// Settings UI can render actionable messages per MOD-03.
enum KeychainError: Error, LocalizedError, Sendable, Equatable {
    /// OSStatus from Security.framework didn't map to a known case.
    case osStatus(OSStatus)
    /// Tried to read a key that isn't in the Keychain.
    case notFound
    /// Caller passed an empty key. MOD-03: keys must be non-empty.
    case emptyKey
    /// Key failed provider-specific format validation (sk-..., sk-ant-...).
    case invalidFormat(reason: String)
    /// Decode failure (Keychain returned non-UTF8 data).
    case invalidEncoding

    var errorDescription: String? {
        switch self {
        case .osStatus(let status):
            return "Keychain operation failed (OSStatus \(status))."
        case .notFound:
            return "No API key found for this provider."
        case .emptyKey:
            return "API key cannot be empty."
        case .invalidFormat(let reason):
            return "API key format invalid: \(reason)"
        case .invalidEncoding:
            return "Stored API key was not valid UTF-8 text."
        }
    }

    static func == (lhs: KeychainError, rhs: KeychainError) -> Bool {
        switch (lhs, rhs) {
        case (.osStatus(let a), .osStatus(let b)): return a == b
        case (.notFound, .notFound): return true
        case (.emptyKey, .emptyKey): return true
        case (.invalidFormat(let a), .invalidFormat(let b)): return a == b
        case (.invalidEncoding, .invalidEncoding): return true
        default: return false
        }
    }
}

/// Keychain storage for BYOK API keys. MOD-04: iCloud Keychain sync ON
/// by default (opt-out).
///
/// One instance per app — `Sendable` and stateless aside from the
/// configurable sync preference. The Settings UI toggles
/// `iCloudSyncEnabled` (persisted via UserDefaults); the manager reads it
/// on every store to decide the synchronizable + accessible attributes.
///
/// Test isolation: the `service` initializer parameter lets tests use a
/// distinct service identifier (`com.bretbouchard.volta.tests`)
/// so they never pollute the real keychain. CI also sets
/// `KICAD_AGENT_TEST_KEYCHAIN=1` to engage the in-memory fallback when
/// Security.framework can't be reached (CI sandboxes).
///
/// In-memory fallback: when Security.framework returns errSecMissingEntitlement
/// (-34018) — common in Swift Package Manager test sandboxes without code
/// signing — the manager transparently falls back to a process-local
/// dictionary. This is for tests + dev only; production builds (signed with
/// the Keychain entitlement) use the real Keychain. The fallback is logged
/// at .info level so it's visible but not noisy.
final class KeychainManager: @unchecked Sendable {
    /// Production service identifier. Scoped to this app — no collisions.
    static let defaultService = "com.bretbouchard.volta"

    /// UserDefaults key for the iCloud-sync opt-out flag.
    /// Per MOD-04: defaults to true (ON). Settings UI flips to false.
    static let iCloudSyncDefaultsKey = "com.bretbouchard.volta.byok.icloud-sync"

    /// Service identifier used in Keychain queries.
    let service: String

    /// When true, the manager uses the in-memory store instead of
    /// Security.framework. Activated by (1) `KICAD_AGENT_TEST_KEYCHAIN=1`
    /// env var, (2) a service identifier containing `.tests.`, or (3) when
    /// a real Keychain call returns errSecMissingEntitlement.
    private let useInMemory: Bool

    /// Process-local store for test environments. Keyed by service + account.
    /// ponytail: static because SecItemAdd is global — even across instances
    /// of different service identifiers the global entitlement failure
    /// persists. We use per-instance service as the namespace.
    nonisolated(unsafe) private static var memoryStore: [String: String] = [:]
    private static let memoryLock = NSLock()

    /// When true, newly stored keys participate in iCloud Keychain sync.
    /// Existing items are migrated when this flag changes (per MOD-04:
    /// toggling in Settings re-stores all known keys with the new flag).
    var iCloudSyncEnabled: Bool {
        get {
            // ponytail: register default so first-launch returns `true`.
            let defaults = UserDefaults.standard
            if defaults.object(forKey: Self.iCloudSyncDefaultsKey) == nil {
                return true
            }
            return defaults.bool(forKey: Self.iCloudSyncDefaultsKey)
        }
        set {
            UserDefaults.standard.set(newValue, forKey: Self.iCloudSyncDefaultsKey)
            Logger.models.info("BYOK iCloud Keychain sync \(newValue ? "ON" : "OFF")")
        }
    }

    /// ponytail: test inject overrides the service and forces in-memory
    /// storage when `useInMemoryTests` is true (CI sandbox escape).
    init(service: String = KeychainManager.defaultService) {
        self.service = service
        // Activate in-memory mode when:
        // 1. Env var explicitly set (CI pipelines)
        // 2. Service identifier contains ".tests." or ".preview."
        let envSet = ProcessInfo.processInfo.environment["KICAD_AGENT_TEST_KEYCHAIN"] == "1"
        let serviceIsTestOnly = service.contains(".tests.") || service.contains(".preview.")
        self.useInMemory = envSet || serviceIsTestOnly
    }

    /// ponytail: in-memory store key — namespaced by service + account.
    private func memoryKey(for provider: KCProviderKind) -> String {
        "\(service)::\(Self.accountIdentifier(for: provider))"
    }

    // MARK: - Store / Load / Delete

    /// Store (or update) an API key for a provider.
    ///
    /// Per MOD-03: caller must validate the key via `APIKeyValidator`
    /// before storing — this method only checks format.
    /// Per MOD-04: respects `iCloudSyncEnabled` for the new item.
    func storeAPIKey(_ key: String, for provider: KCProviderKind) throws {
        guard !key.isEmpty else { throw KeychainError.emptyKey }
        try Self.validateFormat(key, for: provider)

        if useInMemory {
            Self.memoryLock.lock()
            defer { Self.memoryLock.unlock() }
            Self.memoryStore[memoryKey(for: provider)] = key
            return
        }

        let data = Data(key.utf8)
        let accessible = iCloudSyncEnabled
            ? kSecAttrAccessibleAfterFirstUnlock
            : kSecAttrAccessibleWhenUnlockedThisDeviceOnly

        // Delete any existing item first (SecItemUpdate across sync flag is
        // flaky in older macOS; delete+add is the battle-tested pattern).
        try? deleteAPIKey(for: provider)

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: Self.accountIdentifier(for: provider),
            kSecAttrAccessible as String: accessible,
            kSecAttrSynchronizable as String: iCloudSyncEnabled ? kCFBooleanTrue! : kCFBooleanFalse!,
            kSecValueData as String: data
        ]

        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            // errSecMissingEntitlement (-34018): common in SPM test sandboxes
            // without code signing. Fall back to in-memory so the app/tests
            // keep working. Logged at .info so production builds stay quiet.
            if status == errSecMissingEntitlement {
                Logger.models.info("BYOK: Keychain entitlement missing — falling back to in-memory store")
                Self.memoryLock.lock()
                defer { Self.memoryLock.unlock() }
                Self.memoryStore[memoryKey(for: provider)] = key
                return
            }
            Logger.models.error("Keychain SecItemAdd failed: OSStatus \(status)")
            throw KeychainError.osStatus(status)
        }
        let synced = iCloudSyncEnabled
        Logger.models.info("BYOK key stored for provider=\(provider.rawValue) iCloud=\(synced)")
    }

    /// Load an API key for a provider. Returns nil if no key is stored
    /// (rather than throwing `notFound`) so the common "no key configured"
    /// path stays in normal flow.
    func loadAPIKey(for provider: KCProviderKind) throws -> String? {
        if useInMemory {
            Self.memoryLock.lock()
            defer { Self.memoryLock.unlock() }
            return Self.memoryStore[memoryKey(for: provider)]
        }

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: Self.accountIdentifier(for: provider),
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecReturnData as String: kCFBooleanTrue!,
            // Match items regardless of sync flag — both device-local and
            // iCloud items are valid reads.
            kSecAttrSynchronizable as String: kSecAttrSynchronizableAny
        ]

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound { return nil }
        if status == errSecMissingEntitlement {
            // Sandbox/test fallback — return from in-memory.
            Self.memoryLock.lock()
            defer { Self.memoryLock.unlock() }
            return Self.memoryStore[memoryKey(for: provider)]
        }
        guard status == errSecSuccess else {
            Logger.models.error("Keychain SecItemCopyMatching failed: OSStatus \(status)")
            throw KeychainError.osStatus(status)
        }
        guard let data = item as? Data else {
            throw KeychainError.invalidEncoding
        }
        guard let key = String(data: data, encoding: .utf8) else {
            throw KeychainError.invalidEncoding
        }
        return key
    }

    /// Delete the API key for a provider. Idempotent — no-op if missing.
    func deleteAPIKey(for provider: KCProviderKind) throws {
        if useInMemory {
            Self.memoryLock.lock()
            defer { Self.memoryLock.unlock() }
            Self.memoryStore.removeValue(forKey: memoryKey(for: provider))
            return
        }

        // Delete across BOTH sync states (a key stored while sync was ON
        // then OFF, or vice versa). Two queries avoids the synchronizable
        // "Any" wildcard which behaves inconsistently across macOS versions.
        var didDeleteFromMemory = false
        for synchronizable in [kCFBooleanTrue!, kCFBooleanFalse!] {
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecAttrAccount as String: Self.accountIdentifier(for: provider),
                kSecAttrSynchronizable as String: synchronizable
            ]
            let status = SecItemDelete(query as CFDictionary)
            // errSecItemNotFound is fine — we're deleting "if exists".
            // errSecMissingEntitlement falls back to in-memory delete.
            if status == errSecMissingEntitlement && !didDeleteFromMemory {
                Self.memoryLock.lock()
                defer { Self.memoryLock.unlock() }
                Self.memoryStore.removeValue(forKey: memoryKey(for: provider))
                didDeleteFromMemory = true
                continue
            }
            if status != errSecSuccess && status != errSecItemNotFound {
                Logger.models.error("Keychain SecItemDelete failed: OSStatus \(status)")
                throw KeychainError.osStatus(status)
            }
        }
        Logger.models.info("BYOK key deleted for provider=\(provider.rawValue)")
    }

    /// Migrate all stored keys when the user toggles iCloud sync.
    /// Loads every known provider's key, deletes it, re-stores with the
    /// current sync flag. Per MOD-04: called from Settings when the user
    /// flips the iCloud toggle.
    func applyICloudSyncSettingToAllKeys() {
        for provider in KCProviderKind.allCases where !provider.isLocal && provider != .mock {
            guard let key = try? loadAPIKey(for: provider), !key.isEmpty else { continue }
            try? storeAPIKey(key, for: provider)
        }
    }

    /// Returns the set of providers that currently have a key stored.
    /// Used by the Settings UI to render configured/missing status badges.
    func configuredProviders() -> [KCProviderKind] {
        var configured: [KCProviderKind] = []
        for provider in KCProviderKind.allCases where !provider.isLocal && provider != .mock {
            if (try? loadAPIKey(for: provider))?.isEmpty == false {
                configured.append(provider)
            }
        }
        return configured
    }

    // MARK: - Internal helpers

    /// Account identifier per provider. Namespaced so a single service
    /// identifier can hold keys for multiple providers.
    static func accountIdentifier(for provider: KCProviderKind) -> String {
        "apiKey.\(provider.rawValue)"
    }

    /// Lightweight provider-specific format validation. Catches obvious
    /// paste errors (trailing whitespace, wrong prefix) before storing.
    /// Per T-166-01 mitigation: refuses obviously malformed keys.
    static func validateFormat(_ key: String, for provider: KCProviderKind) throws {
        // No provider-local key for local providers.
        if provider.isLocal {
            throw KeychainError.invalidFormat(reason: "\(provider.displayName) does not use an API key.")
        }
        // Strip whitespace before validation — catches copy-paste artifacts.
        let trimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed != key {
            throw KeychainError.invalidFormat(reason: "Key contains leading or trailing whitespace.")
        }
        // Provider-specific prefix hints (advisory; providers issue other
        // formats too but the common ones match these prefixes).
        let prefixHints: [KCProviderKind: [String]] = [
            .openAI: ["sk-"],
            .anthropic: ["sk-ant-"],
            .gemini: ["AIza"],
            .groq: ["gsk_"],
            .xai: ["xai-"],
            .together: ["tg-", "together_"]
        ]
        if let prefixes = prefixHints[provider] {
            // Only enforce when the key doesn't look like an obvious test
            // placeholder ("test-", "fake-"). Tests + dev environments
            // bypass prefix checks by using the `fake-` prefix.
            if !prefixes.contains(where: { key.hasPrefix($0) }) && !key.hasPrefix("test-") && !key.hasPrefix("fake-") {
                throw KeychainError.invalidFormat(
                    reason: "\(provider.displayName) keys usually start with \(prefixes.joined(separator: " or ")). Got: \(key.prefix(8))…"
                )
            }
        }
        // ollama is local — no key needed.
        if provider == .ollama {
            throw KeychainError.invalidFormat(reason: "Ollama runs locally — no API key needed.")
        }
    }
}
