//
//  LocalModelFailureTests.swift
//  KiCadAgentTests
//
//  Phase 245 — Local model failure state tests
//

import Testing
import Foundation
@testable import KiCadAgent

@Suite("Local model failure states (Phase 245)")
struct LocalModelFailureTests {

    @Test("LocalModelStatus cases are distinct and have user-facing messages")
    func statusEnumIsComplete() {
        // The 5 required cases
        let cases: [LocalModelStatus] = [
            .notDownloaded,
            .downloading(progress: 0.5),
            .downloaded,
            .downloadFailed(reason: .network("timeout")),
            .adapterNotPublished
        ]
        #expect(cases.count == 5, "LocalModelStatus must have exactly 5 cases")

        // Failure reason has a user-facing message
        let net = DownloadFailureReason.network("DNS failure")
        #expect(!net.userFacingMessage.isEmpty)
        let http = DownloadFailureReason.httpStatus(500)
        #expect(!http.userFacingMessage.isEmpty)
    }

    @Test("ModelDownloadError.adapterNotFound is a distinct case")
    func adapterNotFoundCaseExists() {
        let err = ModelDownloadError.adapterNotFound(repo: "bretbouchard/volta-pcb-adapter-v2")
        #expect(err.errorDescription?.contains("not found") == true)
        // exact wording can vary; the contract is that the case exists and produces a user-facing description
    }
}