//
//  PreseedManager.swift
//  Volta
//
//  Phase 2 / Task 5 — Pre-Seeding
//
//  Background cache pre-seeder. Queries the MergeEngine for common parts
//  on first launch (or when triggered from settings). Runs at low priority,
//  doesn't block UI. Progress is observable via @Published.
//

import Foundation
import Combine
import OSLog
import VoltaPCBCore

/// Observable pre-seed manager — runs background queries for common parts.
final class PreseedManager: ObservableObject, @unchecked Sendable {
    /// Progress 0.0–1.0.
    @Published private(set) var progress: Double = 0

    /// Number of parts successfully cached.
    @Published private(set) var cached: Int = 0

    /// Number of parts that failed (not found or error).
    @Published private(set) var failed: Int = 0

    /// Whether pre-seeding is currently running.
    @Published private(set) var isRunning = false

    /// Whether pre-seeding has completed.
    @Published private(set) var isComplete = false

    private let mergeEngine: MergeEngine
    private let cacheManager: CacheManager?
    private var task: Task<Void, Never>?

    init(mergeEngine: MergeEngine, cacheManager: CacheManager? = nil) {
        self.mergeEngine = mergeEngine
        self.cacheManager = cacheManager
    }

    /// Start background pre-seeding. Safe to call multiple times — subsequent
    /// calls are ignored while running.
    func start(filter: @escaping (String) -> Bool = { _ in true }) {
        guard !isRunning else { return }
        guard !isComplete else {
            Logger.models.info("PreseedManager: already complete, skipping")
            return
        }

        let parts = SeedLists.all.filter(filter)
        let total = parts.count

        DispatchQueue.main.async { [weak self] in
            self?.isRunning = true
            self?.progress = 0
            self?.cached = 0
            self?.failed = 0
        }

        Logger.models.info("PreseedManager: starting with \(total) parts")

        task = Task.detached(priority: .background) { [weak self] in
            for (index, keyword) in parts.enumerated() {
                if Task.isCancelled { break }

                do {
                    let results = try await self?.mergeEngine.search(keyword: keyword) ?? []
                    if let cache = self?.cacheManager, let first = results.first {
                        try? cache.store(first, ttl: 24 * 3600)
                    }

                    await MainActor.run {
                        self?.cached += 1
                        self?.progress = Double(index + 1) / Double(total)
                    }
                } catch {
                    await MainActor.run {
                        self?.failed += 1
                        self?.progress = Double(index + 1) / Double(total)
                    }
                }

                // Small delay to avoid overwhelming providers
                try? await Task.sleep(nanoseconds: 200_000_000) // 0.2s
            }

            await MainActor.run {
                self?.isRunning = false
                self?.isComplete = true
            }

            Logger.models.info("PreseedManager: complete (\(self?.cached ?? 0) cached, \(self?.failed ?? 0) failed)")
        }
    }

    /// Start with a specific category (e.g., only MCUs).
    func start(category: SeedCategory) {
        switch category {
        case .mcus:
            start(filter: { SeedLists.mcus.contains($0) })
        case .powerICs:
            start(filter: { SeedLists.powerICs.contains($0) })
        case .connectors:
            start(filter: { SeedLists.connectors.contains($0) })
        case .passives:
            start(filter: { SeedLists.passives.contains($0) })
        case .commonICs:
            start(filter: { SeedLists.commonICs.contains($0) })
        case .all:
            start()
        }
    }

    /// Cancel pre-seeding.
    func cancel() {
        task?.cancel()
        DispatchQueue.main.async { [weak self] in
            self?.isRunning = false
        }
    }

    /// Reset state so pre-seeding can be re-run from Settings.
    func reset() {
        cancel()
        DispatchQueue.main.async { [weak self] in
            self?.progress = 0
            self?.cached = 0
            self?.failed = 0
            self?.isComplete = false
        }
    }
}

/// Seed categories for selective pre-seeding.
enum SeedCategory: String, CaseIterable {
    case mcus = "MCUs"
    case powerICs = "Power ICs"
    case connectors = "Connectors"
    case passives = "Passives"
    case commonICs = "Common ICs"
    case all = "All"
}
