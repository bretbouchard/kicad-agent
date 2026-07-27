//
//  ComponentProviderRegistry.swift
//  Volta
//
//  Phase 1 / Task 1 — Provider Registries
//
//  Runtime registry for component data providers (pricing, stock, specs).
//  Mirrors the ProviderRegistry pattern from the LLM provider stack:
//  ObservableObject + @unchecked Sendable + NSLock for mutation + main
//  queue hop for @Published updates.
//
//  Providers register at app launch; the registry fans out searches in
//  parallel via TaskGroup. One provider failing does NOT affect others —
//  errors are logged and skipped (DefensiveForeach pattern).
//
//  Swift 6.2 note: NSLock.lock()/unlock() are unavailable from async
//  contexts. We accumulate TaskGroup outputs in a local then perform a
//  single synchronous locked mutation after the group completes. This
//  matches the existing ProviderRegistry.availableProviders() pattern.
//

import Foundation
import OSLog
import VoltaPCBCore

/// Runtime registry for component data providers (pricing, stock, specs).
/// Mirrors the ProviderRegistry pattern from the LLM provider stack.
/// Providers register at app launch; the registry fans out searches in parallel.
final class ComponentProviderRegistry: ObservableObject, @unchecked Sendable {
    /// All registered component data providers.
    @Published private(set) var providers: [any ComponentDataProvider] = []

    /// Cached availability probe results.
    private var availabilityCache: [String: ProviderAvailability] = [:]
    /// Synchronous name set for atomic dedup — source of truth for registration.
    /// `providers` is the UI-facing mirror, updated via DispatchQueue.main.async.
    private var registeredNames: Set<String> = []
    private let cacheLock = NSLock()

    init() {}

    /// Register a provider. Dedup by name — same-named providers are idempotent.
    func register(_ provider: any ComponentDataProvider) {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        guard !registeredNames.contains(provider.name) else {
            Logger.models.info("ComponentProviderRegistry: skipping duplicate '\(provider.name)'")
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

    /// Search all registered providers in parallel. Returns merged results.
    /// One provider failing does NOT affect others — errors are logged and skipped.
    func searchAll(keyword: String) async -> [UnifiedComponent] {
        // Snapshot providers synchronously before going async — avoid
        // crossing actor boundaries with the @Published var.
        let snapshot: [any ComponentDataProvider] = {
            cacheLock.lock()
            defer { cacheLock.unlock() }
            return self.providers
        }()
        return await withTaskGroup(of: [UnifiedComponent]?.self) { group in
            for provider in snapshot {
                group.addTask {
                    do {
                        return try await provider.search(keyword: keyword)
                    } catch {
                        Logger.models.error("ComponentProvider \(provider.name) search failed: \(error.localizedDescription)")
                        return nil
                    }
                }
            }
            var results: [UnifiedComponent] = []
            for await result in group {
                if let result { results.append(contentsOf: result) }
            }
            return results
        }
    }

    /// Probe availability of all providers concurrently with a 10-second timeout each.
    func probeAvailability() async {
        let snapshot: [any ComponentDataProvider] = {
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
        // Single synchronous locked mutation via sync helper — calling
        // NSLock.lock() directly in an async function body is banned in
        // Swift 6.2; routing through a sync function is the sanctioned
        // pattern (matches ProviderRegistry.cacheAvailability).
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
    var availableProviders: [any ComponentDataProvider] {
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
            // group.next() returns T?? here — flatten with ??.
            let first = await group.next()
            group.cancelAll()
            return first ?? nil
        }
    }
}
