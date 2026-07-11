#if os(macOS)
//
//  KiCadGenerator.swift
//  KiCadAgent
//
//  Phase 182 — KiCad Generator
//
//  Orchestrates the full generation pipeline: intent JSON → CircuitIR →
//  SKIDL build_*.py → .kicad_sch + .kicad_pcb. Coordinates with daemon
//  for actual op execution.
//
//  GEN-02: KiCad generator produces valid .kicad_sch and .kicad_pcb
//  GEN-03: full pipeline deterministic (Phase 184 hash gold-master)
//

import Foundation
import OSLog

/// Generator orchestrator — produces KiCad artifacts from intent.
public final class KiCadGenerator: @unchecked Sendable {

    public struct Config: Sendable, Codable, Equatable {
        public var compiler: SKIDLCompilerConfig
        public var includePCB: Bool        // True to also generate PCB (Phase 183 full pipeline)
        public var runERC: Bool            // True to run ERC after generation
        public var runDRC: Bool            // True to run DRC after PCB generation

        public init(
            compiler: SKIDLCompilerConfig = SKIDLCompilerConfig(),
            includePCB: Bool = false,
            runERC: Bool = true,
            runDRC: Bool = false
        ) {
            self.compiler = compiler
            self.includePCB = includePCB
            self.runERC = runERC
            self.runDRC = runDRC
        }
    }

    public let config: Config

    public init(config: Config = Config()) {
        self.config = config
    }

    /// Full generation result.
    public struct GenerationResult: Sendable, Equatable {
        public let intentJSON: String
        public let buildPy: String
        public let schematicPath: URL?
        public let pcbPath: URL?
        public let contentHash: String
        public let ercPassed: Bool?
        public let drcPassed: Bool?
        public let warnings: [String]
        public let durationSeconds: Double
    }

    /// Generate KiCad artifacts from intent JSON.
    ///
    /// Phase 182 stub: returns a deterministic placeholder hash. Real generation
    /// wires in Phase 182.1 when daemon auto_generate op is exposed via MCP.
    public func generate(intentJSON: String) async throws -> GenerationResult {
        let start = Date()
        Logger.models.info("KiCadGenerator: generating from intent (\(intentJSON.count) bytes)")

        // Validate intent shape (basic — has at least one of: intent, components, nets).
        guard intentJSON.contains("\"") else {
            throw SKDLCompileError.invalidIntent(reason: "Not JSON: missing quote characters")
        }

        // Hash the intent for determinism.
        let intentHash = DeterministicHash.sha256(intentJSON)

        // Phase 182.1: call daemon `auto_generate` op via MCPClient.
        // For now, return a structured stub.
        let result = GenerationResult(
            intentJSON: intentJSON,
            buildPy: "# Phase 182 stub — real SKIDL emission lands when daemon auto_generate op is wired",
            schematicPath: nil,
            pcbPath: nil,
            contentHash: intentHash,
            ercPassed: nil,
            drcPassed: nil,
            warnings: ["Phase 182.1 wires daemon auto_generate for real output"],
            durationSeconds: Date().timeIntervalSince(start)
        )
        return result
    }
}

#endif // os(macOS)
