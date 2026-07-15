//
//  GenerativePipeline.swift
//  Volta
//
//  Phase 183 — Generative Pipeline
//
//  Full pipeline: intent JSON → CircuitIR → SKIDL → KiCad → renders → exports.
//  Every step is hash-deterministic so identical input → identical output
//  (Phase 184 hash gold-master tests).
//
//  GEN-03: generative pipeline is deterministic
//  GEN-04: hash gold-master regression detection
//  GEN-05: generative correctness invariants
//

import Foundation
import OSLog

/// Full generative pipeline orchestrator.
public final class GenerativePipeline: @unchecked Sendable {

    public struct PipelineConfig: Sendable, Codable, Equatable {
        public var generator: KiCadGenerator.Config
        public var captureSnapshots: Bool       // True to snapshot every step
        public var emitRenders: Bool            // True to produce SVG + PNG
        public var exportArtifacts: Bool        // True to produce Gerbers + BOM

        public init(
            generator: KiCadGenerator.Config = KiCadGenerator.Config(),
            captureSnapshots: Bool = true,
            emitRenders: Bool = true,
            exportArtifacts: Bool = false
        ) {
            self.generator = generator
            self.captureSnapshots = captureSnapshots
            self.emitRenders = emitRenders
            self.exportArtifacts = exportArtifacts
        }
    }

    public let config: PipelineConfig
    private let generator: KiCadGenerator

    public init(config: PipelineConfig = PipelineConfig()) {
        self.config = config
        self.generator = KiCadGenerator(config: config.generator)
    }

    /// Run the full pipeline. Returns a step-by-step manifest for audit.
    public func run(intentJSON: String) async throws -> PipelineResult {
        var steps: [PipelineStepResult] = []

        // Step 1: Generate (compile SKIDL + produce schematic).
        let genStart = Date()
        let genResult = try await generator.generate(intentJSON: intentJSON)
        steps.append(PipelineStepResult(
            step: .generate,
            contentHash: genResult.contentHash,
            durationSeconds: Date().timeIntervalSince(genStart),
            artifacts: stepArtifacts(genResult),
            warnings: genResult.warnings
        ))

        // Step 2 (Phase 183.1): emit renders if configured.
        if config.emitRenders {
            let renderStart = Date()
            steps.append(PipelineStepResult(
                step: .render,
                contentHash: DeterministicHash.sha256("render-stub-\(genResult.contentHash)"),
                durationSeconds: Date().timeIntervalSince(renderStart),
                artifacts: [],
                warnings: ["Phase 183.1 wires render_schematic_svg via daemon"]
            ))
        }

        // Step 3 (Phase 183.2): export artifacts if configured.
        if config.exportArtifacts {
            let exportStart = Date()
            steps.append(PipelineStepResult(
                step: .export,
                contentHash: DeterministicHash.sha256("export-stub-\(genResult.contentHash)"),
                durationSeconds: Date().timeIntervalSince(exportStart),
                artifacts: [],
                warnings: ["Phase 183.2 wires Gerber/BOM export"]
            ))
        }

        let totalDuration = steps.reduce(0) { $0 + $1.durationSeconds }
        return PipelineResult(
            intentHash: DeterministicHash.sha256(intentJSON),
            steps: steps,
            totalDurationSeconds: totalDuration
        )
    }

    private func stepArtifacts(_ genResult: KiCadGenerator.GenerationResult) -> [String] {
        var arts: [String] = ["build_*.py"]
        if genResult.schematicPath != nil { arts.append(".kicad_sch") }
        if genResult.pcbPath != nil { arts.append(".kicad_pcb") }
        return arts
    }
}

/// Result of running the full pipeline.
public struct PipelineResult: Sendable, Equatable {
    public let intentHash: String
    public let steps: [PipelineStepResult]
    public let totalDurationSeconds: Double

    /// Combined hash of all step content hashes — used as the pipeline's
    /// gold-master fingerprint.
    public var pipelineHash: String {
        let combined = steps.map(\.contentHash).joined(separator: "|")
        return DeterministicHash.sha256(combined)
    }
}

/// One step in the pipeline result.
public struct PipelineStepResult: Sendable, Equatable, Identifiable {
    public let id = UUID()
    public let step: GenerativePipelineStep
    public let contentHash: String
    public let durationSeconds: Double
    public let artifacts: [String]
    public let warnings: [String]
}

/// Canonical generative pipeline steps (renamed to avoid collision with
/// InlineRendering PipelineStep).
public enum GenerativePipelineStep: String, Sendable, Codable, CaseIterable {
    case generate    // SKIDL compilation
    case render      // SVG schematic + PNG PCB
    case export      // Gerbers, drill, BOM
}
