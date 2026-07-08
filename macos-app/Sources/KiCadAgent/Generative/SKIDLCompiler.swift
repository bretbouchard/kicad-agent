//
//  SKIDLCompiler.swift
//  KiCadAgent
//
//  Phase 181 + 181.5 — SKIDL Compiler + v5.0 Bridge
//
//  Wraps the existing Phase 156 Python SKIDL emitter (circuit_ir/skidl_emitter.py).
//  Phase 181.5 ships the bridge interface — when v5.0 SKIDL lands at
//  /Volumes/Storage/schgen/, this file's `bridge` property flips from
//  `.phase156Emitter` to `.v5SKIDL` with no API change to callers.
//
//  GEN-01: SKIDL compiler produces executable build_*.py
//  GEN-02: KiCad generator produces .kicad_sch
//

import Foundation

/// SKIDL compiler configuration.
public struct SKIDLCompilerConfig: Sendable, Codable, Equatable {
    /// Which emitter to use. Defaults to Phase 156 emitter (L1 pin-level).
    public var emitter: Emitter
    /// True to hash-deterministically emit (no random IDs, no UUID churn).
    public var deterministic: Bool

    public init(emitter: Emitter = .phase156L1, deterministic: Bool = true) {
        self.emitter = emitter
        self.deterministic = deterministic
    }

    /// Emitter backend selection.
    public enum Emitter: String, Sendable, Codable, CaseIterable {
        /// Phase 156 Wave 2 L1 emitter (current production).
        case phase156L1
        /// Phase 156 Wave 2 L2 emitter (component-level, training-friendly).
        case phase156L2
        /// v5.0 SKIDL — Phase 181.5 bridge target. Hard-linked to
        /// /Volumes/Storage/schgen/ when ready. Falls back to phase156L1.
        case v5SKIDL

        /// True if this emitter is available for use today.
        public var isAvailable: Bool {
            switch self {
            case .phase156L1, .phase156L2: return true
            case .v5SKIDL:
                // Phase 181.5 bridge: check for marker file.
                // When v5.0 ships, this returns true and bridge activates.
                return FileManager.default.fileExists(atPath: "/Volumes/Storage/schgen/.v5-ready")
            }
        }

        /// Effective emitter — falls back to phase156L1 if unavailable.
        public var effective: Emitter {
            isAvailable ? self : .phase156L1
        }
    }
}

/// Compiled SKIDL output.
public struct SKIDLCompilationResult: Sendable, Equatable {
    public let buildPy: String              // The emitted build_*.py source
    public let emitterUsed: SKIDLCompilerConfig.Emitter
    public let contentHash: String          // SHA-256 of buildPy (for gold-master tests)
    public let warnings: [String]
}

/// Errors specific to SKIDL compilation.
public enum SKDLCompileError: LocalizedError, Equatable {
    case invalidIntent(reason: String)
    case emitterUnavailable(SKIDLCompilerConfig.Emitter)
    case daemonError(String)

    public var errorDescription: String? {
        switch self {
        case .invalidIntent(let r): return "Invalid intent JSON: \(r)"
        case .emitterUnavailable(let e): return "Emitter \(e.rawValue) not available"
        case .daemonError(let m): return "Daemon error: \(m)"
        }
    }
}

/// Hashing helper for deterministic output verification (Phase 184).
public enum DeterministicHash {

    /// SHA-256 hash of a UTF-8 string. Returns hex lowercase.
    public static func sha256(_ input: String) -> String {
        let data = Data(input.utf8)
        return sha256(data)
    }

    /// SHA-256 hash of Data.
    public static func sha256(_ data: Data) -> String {
        // ponytail: use CryptoKit (macOS 26+).
        let digest = CryptoKit.SHA256.hash(data: data)
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}

#if canImport(CryptoKit)
import CryptoKit
#endif
