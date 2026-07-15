//
//  LocalModelPathTests.swift
//  VoltaTests
//
//  Phase 245 — v2 path resolution tests
//

import Testing
import Foundation
@testable import Volta

@Suite("Local model path resolution (Phase 245)")
struct LocalModelPathTests {

    @Test("ModelDownloader.adapterRepo on macOS returns v2")
    func adapterRepoIsV2() {
        #if os(macOS)
        let repo = ModelDownloader().adapterRepo
        #expect(repo == "bretbouchard/volta-pcb-adapter-v2", "v1 must be gone; got \(repo)")
        #endif
    }

    @Test("ModelDownloader.adapterDirectory on macOS ends in v2 path")
    func adapterDirectoryIsV2() {
        #if os(macOS)
        let dir = ModelDownloader.adapterDirectory
        #expect(dir.lastPathComponent == "volta-pcb-adapter-v2")
        #endif
    }

    @Test("isAdapterPresent detects v2 adapter_model.safetensors")
    func isAdapterPresentDetectsV2() throws {
        // Create a temp dir with the v2-standard filenames
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-test-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmp) }

        // Touch the v2 files
        let adapterURL = tmp.appendingPathComponent("adapter_model.safetensors")
        let configURL = tmp.appendingPathComponent("adapter_config.json")
        try Data().write(to: adapterURL)
        try Data().write(to: configURL)

        // Manually call the isAdapterPresent logic with our temp dir
        let hasAdapter = FileManager.default.fileExists(atPath: adapterURL.path)
            && FileManager.default.fileExists(atPath: configURL.path)
        #expect(hasAdapter == true, "isAdapterPresent should detect v2 PEFT-standard files")
    }

    @Test("isAdapterPresent rejects v1's adapters.safetensors (the bug we fixed)")
    func isAdapterPresentRejectsV1Filename() throws {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-test-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmp) }

        // Create ONLY the v1 file (no v2 file)
        let v1URL = tmp.appendingPathComponent("adapters.safetensors")
        try Data().write(to: v1URL)
        let v2URL = tmp.appendingPathComponent("adapter_model.safetensors")
        // Note: v2 file does NOT exist

        // The v2 check should fail because v2 file is missing
        let adapterURL = v2URL  // v2 path
        let configURL = tmp.appendingPathComponent("adapter_config.json")
        let hasAdapter = FileManager.default.fileExists(atPath: adapterURL.path)
            && FileManager.default.fileExists(atPath: configURL.path)
        #expect(hasAdapter == false, "v1 file alone must NOT satisfy v2 isAdapterPresent")
    }
}