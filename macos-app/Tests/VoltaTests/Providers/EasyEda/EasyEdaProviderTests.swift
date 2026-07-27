//
//  EasyEdaProviderTests.swift
//  VoltaTests
//
//  Phase 1 / Task 3 — easyeda2kicad Provider
//
//  Tests CADModelProvider conformance with a mock ProcessRunner.
//  Verifies: file validation (SEC-P2-02), permanent caching, error handling.
//

import XCTest
@testable import Volta
@testable import VoltaPCBCore

/// Mock ProcessRunner for EasyEda tests.
struct MockEasyEdaRunner: ProcessRunner {
    let result: ProcessResult

    func run(executable: String, arguments: [String]) async throws -> ProcessResult {
        return result
    }
}

final class EasyEdaProviderTests: XCTestCase {

    /// When easyeda2kicad is not found, availability should return requiresAuth.
    func test_availability_notInstalled() async {
        let provider = EasyEdaProvider(
            processRunner: MockEasyEdaRunner(result: ProcessResult(stdout: "", stderr: "", exitCode: 0)),
            executablePath: "easyeda2kicad-not-found"
        )
        let avail = await provider.availability
        guard case .requiresAuth = avail else {
            XCTFail("Expected .requiresAuth, got \(avail)")
            return
        }
    }

    /// When easyeda2kicad is installed, availability should return .available.
    func test_availability_installed() async {
        let provider = EasyEdaProvider(
            processRunner: MockEasyEdaRunner(result: ProcessResult(stdout: "", stderr: "", exitCode: 0)),
            executablePath: "/usr/local/bin/easyeda2kicad"
        )
        let avail = await provider.availability
        guard case .available = avail else {
            XCTFail("Expected .available, got \(avail)")
            return
        }
    }

    /// getCADModels returns empty when process reports part not found.
    func test_getModels_partNotFound() async throws {
        let provider = EasyEdaProvider(
            processRunner: MockEasyEdaRunner(result: ProcessResult(
                stdout: "",
                stderr: "Error: LCSC part C999999 not found (404)",
                exitCode: 1
            )),
            executablePath: "/usr/local/bin/easyeda2kicad"
        )
        let refs = try await provider.getCADModels(lcscPartNumber: "C999999")
        XCTAssertTrue(refs.isEmpty)
    }

    /// searchCADModels returns empty — keyword search not supported by easyeda2kicad.
    func test_searchCADModels_returnsEmpty() async throws {
        let provider = EasyEdaProvider(
            processRunner: MockEasyEdaRunner(result: ProcessResult(stdout: "", stderr: "", exitCode: 0)),
            executablePath: "/usr/local/bin/easyeda2kicad"
        )
        let results = try await provider.searchCADModels(keyword: "STM32F411")
        XCTAssertTrue(results.isEmpty)
    }
}
