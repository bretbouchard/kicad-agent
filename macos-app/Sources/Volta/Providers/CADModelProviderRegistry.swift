//
//  CADModelProviderRegistry.swift
//  Volta
//
//  Phase 1 / Task 1 — Provider Registries
//
//  Runtime registry for CAD model providers (footprints, symbols, 3D models).
//  Same pattern as ComponentProviderRegistry — ObservableObject +
//  @unchecked Sendable + NSLock + main-queue hop for @Published.
//
//  Distinct from ComponentProviderRegistry: CAD providers also expose
//  getCADModels(lcscPartNumber:) for the high-fidelity download path
//  (selected part → fetch footprint + symbol + 3D). Search returns
//  UnifiedComponents with cadModels populated; getModels returns refs only.
//
//  Swift 6.2 note: NSLock.lock()/unlock() are unavailable from async
//  contexts. We accumulate TaskGroup outputs in a local then perform a
//  single synchronous locked mutation after the group completes.
//

import Foundation
import OSLog
import VoltaPCBCore

/// Runtime registry for CAD model providers (footprints, symbols, 3D models).
/// Same pattern as ComponentProviderRegistry.
final class CADModelProviderRegistry: ObservableObject, @unchecked Sendable {
    @Published private(set) var providers: [any CADModelProvider] = []

    private var availabilityCache: [String: ProviderAvailability] = [:]
    private var registeredNames: Set<String> = []
    private let cacheLock = NSLock()

    init() {}

    func register(_ provider: any CADModelProvider) {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        guard !registeredNames.contains(provider.name) else {
            Logger.models.info("CADModelProviderRegistry: skipping duplicate '\(provider.name)'")
            return
        }
        registeredNames.insert(provider.name)
        DispatchQueue.main.async { [weak self] in
            self?.providers.append(provider)
        }
    }

    func unregister(name: String) {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        registeredNames.remove(name)
        availabilityCache.removeValue(forKey: name)
        DispatchQueue.main.async { [weak self] in
            self?.providers.removeAll { $0.name == name }
        }
    }

    /// Search all CAD providers in parallel. Returns merged UnifiedComponents.
    func searchAll(keyword: String) async -> [UnifiedComponent] {
        let snapshot: [any CADModelProvider] = {
            cacheLock.lock()
            defer { cacheLock.unlock() }
            return self.providers
        }()
        return await withTaskGroup(of: [UnifiedComponent]?.self) { group in
            for provider in snapshot {
                group.addTask {
                    do {
                        return try await provider.searchCADModels(keyword: keyword)
                    } catch {
                        Logger.models.error("CADModelProvider \(provider.name) search failed: \(error.localizedDescription)")
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

    /// Get CAD models from all providers for a specific LCSC part number.
    func getModels(lcscPartNumber: String) async -> [CADModelRef] {
        let snapshot: [any CADModelProvider] = {
            cacheLock.lock()
            defer { cacheLock.unlock() }
            return self.providers
        }()
        return await withTaskGroup(of: [CADModelRef]?.self) { group in
            for provider in snapshot {
                group.addTask {
                    do {
                        return try await provider.getCADModels(lcscPartNumber: lcscPartNumber)
                    } catch {
                        Logger.models.error("CADModelProvider \(provider.name) getModels failed: \(error.localizedDescription)")
                        return nil
                    }
                }
            }
            var results: [CADModelRef] = []
            for await result in group {
                if let result { results.append(contentsOf: result) }
            }
            return results
        }
    }

    func probeAvailability() async {
        let snapshot: [any CADModelProvider] = {
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

    func lastKnownAvailability(for name: String) -> ProviderAvailability? {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        return availabilityCache[name]
    }

    var availableProviders: [any CADModelProvider] {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        return providers.filter { availabilityCache[$0.name]?.isAvailable ?? false }
    }

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
