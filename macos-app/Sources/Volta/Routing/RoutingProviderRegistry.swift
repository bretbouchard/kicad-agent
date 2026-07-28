//
//  RoutingProviderRegistry.swift
//  Volta
//
//  Phase 253 Task 1 — Routing Provider Registry
//
//  Runtime registry for PCB auto-routing providers. Mirrors the
//  ComponentProviderRegistry pattern: ObservableObject + @unchecked
//  Sendable + NSLock for mutation + main-queue hop for @Published
//  updates. Providers register at app launch; the registry hands out
//  routes by name and filters availability for the UI.
//
//  Swift 6.2 note: NSLock.lock()/unlock() are unavailable from async
//  contexts. We snapshot state synchronously, do the async work, then
//  perform a single locked mutation after — same pattern as
//  ComponentProviderRegistry.probeAvailability().
//

import Foundation
import OSLog
import VoltaPCBCore

/// Runtime registry for routing providers. Providers register at app
/// launch; the UI looks up the active provider by name from Settings.
final class RoutingProviderRegistry: ObservableObject, @unchecked Sendable {
    /// All registered routing providers.
    @Published private(set) var providers: [any RoutingProvider] = []

    /// Cached availability probe results.
    private var availabilityCache: [String: ProviderAvailability] = [:]
    /// Synchronous name set for atomic dedup — source of truth for registration.
    /// `providers` is the UI-facing mirror, updated via DispatchQueue.main.async.
    private var registeredNames: Set<String> = []
    private let cacheLock = NSLock()

    init() {}

    /// Register a provider. Dedup by name — same-named providers are idempotent.
    func register(_ provider: any RoutingProvider) {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        guard !registeredNames.contains(provider.name) else {
            Logger.models.info("RoutingProviderRegistry: skipping duplicate '\(provider.name)'")
            return
        }
        registeredNames.insert(provider.name)
        DispatchQueue.main.async { [weak self] in
            self?.providers.append(provider)
        }
    }

    /// Unregister a provider by name.
    func unregister(name: String) {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        registeredNames.remove(name)
        availabilityCache.removeValue(forKey: name)
        DispatchQueue.main.async { [weak self] in
            self?.providers.removeAll { $0.name == name }
        }
    }

    /// Lookup a provider by name. Returns nil if not registered.
    func provider(named name: String) -> (any RoutingProvider)? {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        return providers.first { $0.name == name }
    }

    /// Probe availability of all providers concurrently with a 10-second timeout each.
    func probeAvailability() async {
        let snapshot: [any RoutingProvider] = {
            cacheLock.lock()
            defer { cacheLock.unlock() }
            return self.providers
        }()
        let updates = await withTaskGroup(of: (String, ProviderAvailability)?.self) { group in
            for provider in snapshot {
                group.addTask { [weak self] in
                    let avail = await self?.withTimeout(seconds: 10) {
                        await provider.availability
                    } ?? .unavailable(reason: "Availability check timed out")
                    return (provider.name, avail)
                }
            }
            var collected: [(String, ProviderAvailability)] = []
            for await pair in group {
                if let pair { collected.append(pair) }
            }
            return collected
        }
        applyAvailabilityUpdates(updates)
    }

    /// Synchronous cache mutation helper. See probeAvailability() comment.
    private func applyAvailabilityUpdates(_ updates: [(String, ProviderAvailability)]) {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        for (name, avail) in updates {
            availabilityCache[name] = avail
        }
    }

    /// Synchronous read of last-probed availability.
    func lastKnownAvailability(for name: String) -> ProviderAvailability? {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        return availabilityCache[name]
    }

    /// All providers whose last probe returned .available.
    var availableProviders: [any RoutingProvider] {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        return providers.filter { availabilityCache[$0.name]?.isAvailable ?? false }
    }

    // MARK: - Helpers

    private func withTimeout<T: Sendable>(seconds: TimeInterval, operation: @escaping @Sendable () async -> T) async -> T? {
        await withTaskGroup(of: T?.self) { group in
            group.addTask { await operation() }
            group.addTask {
                try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                return nil
            }
            let first = await group.next()
            group.cancelAll()
            return first ?? nil
        }
    }
}