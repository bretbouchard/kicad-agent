//
//  HashGoldMaster.swift
//  KiCadAgent
//
//  Phase 184 — Hash Gold Master Tests
//
//  Gold-master regression detection. Hashes are deterministic for a given
//  input. If a future change alters the hash, the test fails and the change
//  must be reviewed.
//
//  GEN-04: hash gold-master regression detection.
//

import Foundation
import OSLog

/// Gold-master hash store — maps intent hash → pipeline hash.
public final class HashGoldMaster: @unchecked Sendable {

    /// One gold-master entry.
    public struct Entry: Sendable, Codable, Equatable {
        public let intentHash: String
        public let pipelineHash: String
        public let capturedAt: Date
        public let generatorConfigHash: String
        public let notes: String?

        public init(intentHash: String, pipelineHash: String, capturedAt: Date = .now, generatorConfigHash: String, notes: String? = nil) {
            self.intentHash = intentHash
            self.pipelineHash = pipelineHash
            self.capturedAt = capturedAt
            self.generatorConfigHash = generatorConfigHash
            self.notes = notes
        }
    }

    /// Comparison result for a single entry.
    public enum ComparisonResult: Sendable, Equatable {
        case match
        case mismatch(expected: String, actual: String)
        case missingExpected
        case unexpected
    }

    private var entries: [String: Entry] = [:]  // intentHash → Entry

    public init() {}

    /// Capture or update a gold-master entry.
    public func capture(_ entry: Entry) {
        entries[entry.intentHash] = entry
    }

    /// Compare an actual result against the gold master.
    public func compare(intentHash: String, actualPipelineHash: String) -> ComparisonResult {
        if let expected = entries[intentHash] {
            if expected.pipelineHash == actualPipelineHash {
                return .match
            }
            return .mismatch(expected: expected.pipelineHash, actual: actualPipelineHash)
        }
        return .missingExpected
    }

    /// All captured entries — for export / inspection.
    public func allEntries() -> [Entry] {
        Array(entries.values).sorted { $0.intentHash < $1.intentHash }
    }

    /// Serialize to JSON for persistence (Phase 184.1 ships disk-backed store).
    public func toJSON() throws -> Data {
        let ordered = allEntries()
        return try JSONEncoder().encode(ordered)
    }

    /// Restore from JSON.
    public func restore(fromJSON data: Data) throws {
        let decoded = try JSONDecoder().decode([Entry].self, from: data)
        entries.removeAll()
        for entry in decoded { entries[entry.intentHash] = entry }
    }
}
