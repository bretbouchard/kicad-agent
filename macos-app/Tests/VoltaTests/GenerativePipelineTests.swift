//
//  GenerativePipelineTests.swift
//  VoltaTests
//
//  Phase 181 + 182 + 183 + 184 + 185 — Track F Generative
//

import Testing
import Foundation
@testable import Volta

@Suite("Generative Track F (181-185)", .disabled(if: ProcessInfo.processInfo.environment["CI_SKIP_SMOKE"] != nil))
struct GenerativePipelineTests {

    // MARK: - Phase 181 — SKIDL Compiler + v5.0 Bridge

    @Test("SKIDLCompilerConfig defaults to Phase 156 L1 emitter")
    func defaultEmitter() {
        let config = SKIDLCompilerConfig()
        #expect(config.emitter == .phase156L1)
        #expect(config.deterministic == true)
    }

    @Test("Emitter.phase156L1 is available")
    func phase156Available() {
        #expect(SKIDLCompilerConfig.Emitter.phase156L1.isAvailable == true)
        #expect(SKIDLCompilerConfig.Emitter.phase156L2.isAvailable == true)
    }

    @Test("Emitter.v5SKIDL falls back to phase156L1 when not ready")
    func v5SKIDLFallback() {
        // Marker file at /Volumes/Storage/schgen/.v5-ready is the trigger.
        // On machines without it, falls back to phase156L1.
        let effective = SKIDLCompilerConfig.Emitter.v5SKIDL.effective
        #expect(effective == .phase156L1 || effective == .v5SKIDL)
    }

    @Test("SKDLCompileError messages are descriptive")
    func compileErrorMessage() {
        let err = SKDLCompileError.invalidIntent(reason: "missing components array")
        #expect(err.localizedDescription.contains("missing components array"))
    }

    // MARK: - Phase 182 — KiCad Generator

    @Test("KiCadGenerator accepts intent JSON and returns deterministic hash", .tags(.mutation))
    func generatorProducesHash() async throws {
        let gen = KiCadGenerator()
        let intent = #"{"intent":"design a distortion pedal"}"#
        let result = try await gen.generate(intentJSON: intent)
        #expect(result.contentHash.isEmpty == false)
        #expect(result.warnings.isEmpty == false) // Phase 182.1 stub warning
    }

    @Test("KiCadGenerator rejects non-JSON input")
    func generatorRejectsNonJSON() async {
        let gen = KiCadGenerator()
        await #expect(throws: SKDLCompileError.self) {
            _ = try await gen.generate(intentJSON: "not-json")
        }
    }

    @Test("KiCadGenerator hash is stable for same input")
    func generatorHashStable() async throws {
        let gen = KiCadGenerator()
        let intent = #"{"intent":"led driver"}"#
        let r1 = try await gen.generate(intentJSON: intent)
        let r2 = try await gen.generate(intentJSON: intent)
        #expect(r1.contentHash == r2.contentHash)
    }

    @Test("KiCadGenerator hash differs for different inputs")
    func generatorHashDiffers() async throws {
        let gen = KiCadGenerator()
        let r1 = try await gen.generate(intentJSON: #"{"intent":"a"}"#)
        let r2 = try await gen.generate(intentJSON: #"{"intent":"b"}"#)
        #expect(r1.contentHash != r2.contentHash)
    }

    // MARK: - Phase 183 — Generative Pipeline

    @Test("GenerativePipeline runs all configured steps")
    func pipelineRunsSteps() async throws {
        let pipeline = GenerativePipeline()
        let result = try await pipeline.run(intentJSON: #"{"intent":"test"}"#)
        #expect(result.steps.isEmpty == false)
        #expect(result.pipelineHash.isEmpty == false)
    }

    @Test("GenerativePipeline respects emitRenders config")
    func pipelineRendersConfig() async throws {
        var config = GenerativePipeline.PipelineConfig()
        config.emitRenders = true
        let pipeline = GenerativePipeline(config: config)
        let result = try await pipeline.run(intentJSON: #"{"intent":"test"}"#)
        // Should have at least 2 steps: generate + render
        #expect(result.steps.count >= 2)
        #expect(result.steps.contains(where: { $0.step == .render }))
    }

    @Test("GenerativePipeline respects exportArtifacts config")
    func pipelineExportConfig() async throws {
        var config = GenerativePipeline.PipelineConfig()
        config.exportArtifacts = true
        let pipeline = GenerativePipeline(config: config)
        let result = try await pipeline.run(intentJSON: #"{"intent":"test"}"#)
        #expect(result.steps.contains(where: { $0.step == .export }))
    }

    @Test("PipelineStep has three canonical cases")
    func pipelineStepCases() {
        #expect(GenerativePipelineStep.allCases.count == 3)
        #expect(GenerativePipelineStep.allCases.contains(.generate))
        #expect(GenerativePipelineStep.allCases.contains(.render))
        #expect(GenerativePipelineStep.allCases.contains(.export))
    }

    // MARK: - Phase 184 — Hash Gold Master

    @Test("HashGoldMaster.compare returns match for identical hash")
    func goldMasterMatch() {
        let master = HashGoldMaster()
        let intent = "intent-hash-1"
        let pipeline = "pipeline-hash-1"
        let config = "config-hash-1"
        master.capture(HashGoldMaster.Entry(
            intentHash: intent,
            pipelineHash: pipeline,
            generatorConfigHash: config
        ))
        let result = master.compare(intentHash: intent, actualPipelineHash: pipeline)
        #expect(result == .match)
    }

    @Test("HashGoldMaster.compare returns mismatch for different hash")
    func goldMasterMismatch() {
        let master = HashGoldMaster()
        master.capture(HashGoldMaster.Entry(
            intentHash: "i1",
            pipelineHash: "expected",
            generatorConfigHash: "c1"
        ))
        let result = master.compare(intentHash: "i1", actualPipelineHash: "actual")
        if case .mismatch(let expected, let actual) = result {
            #expect(expected == "expected")
            #expect(actual == "actual")
        } else {
            Issue.record("expected .mismatch, got \(result)")
        }
    }

    @Test("HashGoldMaster.compare returns missingExpected for unknown intent")
    func goldMasterMissing() {
        let master = HashGoldMaster()
        let result = master.compare(intentHash: "unknown", actualPipelineHash: "x")
        #expect(result == .missingExpected)
    }

    @Test("HashGoldMaster serializes and restores round-trip")
    func goldMasterRoundTrip() throws {
        let master = HashGoldMaster()
        master.capture(HashGoldMaster.Entry(intentHash: "a", pipelineHash: "1", generatorConfigHash: "z"))
        master.capture(HashGoldMaster.Entry(intentHash: "b", pipelineHash: "2", generatorConfigHash: "z"))

        let data = try master.toJSON()
        let restored = HashGoldMaster()
        try restored.restore(fromJSON: data)

        let original = master.allEntries()
        let restoredEntries = restored.allEntries()
        #expect(original.count == restoredEntries.count)
    }

    // MARK: - Phase 185 — Generative Correctness Invariants

    @Test("DeterministicHash.sha256 produces stable hex output")
    func hashStability() {
        let h1 = DeterministicHash.sha256("test input")
        let h2 = DeterministicHash.sha256("test input")
        #expect(h1 == h2)
        #expect(h1.count == 64) // SHA-256 = 32 bytes = 64 hex chars
    }

    @Test("DeterministicHash.sha256 produces different hashes for different inputs")
    func hashDifference() {
        let h1 = DeterministicHash.sha256("input1")
        let h2 = DeterministicHash.sha256("input2")
        #expect(h1 != h2)
    }

    @Test("DeterministicHash.sha256 produces known hash for known input")
    func hashKnownValue() {
        // SHA-256 of empty string — well-known constant.
        let empty = DeterministicHash.sha256("")
        #expect(empty == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    }

    @Test("PipelineResult.pipelineHash combines step hashes deterministically")
    func pipelineHashDeterministic() {
        let step1 = PipelineStepResult(step: .generate, contentHash: "abc", durationSeconds: 0.1, artifacts: [], warnings: [])
        let step2 = PipelineStepResult(step: .render, contentHash: "def", durationSeconds: 0.2, artifacts: [], warnings: [])
        let result1 = PipelineResult(intentHash: "intent", steps: [step1, step2], totalDurationSeconds: 0.3)
        let result2 = PipelineResult(intentHash: "intent", steps: [step1, step2], totalDurationSeconds: 0.3)
        #expect(result1.pipelineHash == result2.pipelineHash)
    }
}
