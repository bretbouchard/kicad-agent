#if os(macOS)

import Testing
import Foundation
@testable import Volta

@MainActor
@Suite("GSA Platform Host")
struct GSAPlatformHostTests {
    private let governedContext = GSAPlatformHost.GovernedProjectContext(
        projectID: UUID(uuidString: "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA")!,
        projectName: "Flight Controller",
        conversationID: UUID(uuidString: "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB")!,
        revision: 7
    )

    @Test("Live configuration includes stable storage and temporary file roots")
    func liveConfigurationShape() {
        let config = GSAPlatformHostConfiguration.live()

        #expect(config.storageDirectory.path.contains("Application Support"))
        #expect(config.storageDirectory.path.contains("VoltaPCB/gsa-platform"))
        #expect(config.artifactRoot.path.contains("release-artifacts"))
        #expect(config.allowedFileRoots.contains(config.storageDirectory))
        #expect(config.allowedFileRoots.contains(config.artifactRoot))
        #expect(config.allowedFileRoots.contains(FileManager.default.temporaryDirectory))
    }

    @Test("Boot creates a live platform and diagnostics snapshot")
    func bootReady() async throws {
        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-gsa-host-\(UUID().uuidString)", isDirectory: true)
        let config = GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: storageDirectory.appendingPathComponent("artifacts", isDirectory: true),
            allowedFileRoots: [
                storageDirectory,
                storageDirectory.appendingPathComponent("artifacts", isDirectory: true),
                FileManager.default.temporaryDirectory
            ],
            allowedExecutables: []
        )
        let host = GSAPlatformHost(configuration: config)
        defer { try? FileManager.default.removeItem(at: storageDirectory) }

        host.boot()

        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while host.state == .booting, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }

        #expect(host.state == .ready)
        #expect(host.platform != nil)
        #expect(host.diagnostics != nil)
        #expect(host.diagnosticsExport() != nil)
    }

    @Test("Governed board release export writes artifact and evidence")
    func governedBoardReleaseExport() async throws {
        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-gsa-release-\(UUID().uuidString)", isDirectory: true)
        let artifactRoot = storageDirectory.appendingPathComponent("artifacts", isDirectory: true)
        let config = GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [storageDirectory, artifactRoot],
            allowedExecutables: []
        )
        let host = GSAPlatformHost(configuration: config)
        defer { try? FileManager.default.removeItem(at: storageDirectory) }

        host.boot()
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while host.state == .booting, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }

        let result = try await host.runGovernedBoardReleaseExport(context: governedContext)
        #expect(FileManager.default.fileExists(atPath: result.artifactPath))
        #expect(result.artifactPath.contains("volta-board-release.zip"))
        #expect(result.projectReference.hasPrefix("project:"))
        #expect(result.revisionReference.hasPrefix("revision:"))
        #expect(result.schematicReference.hasPrefix("schematic:"))
        #expect(result.sheetReference.hasPrefix("sheet:"))
        #expect(result.componentReference.hasPrefix("component:"))
        #expect(result.netReference.hasPrefix("net:"))
        #expect(result.bomReference.hasPrefix("bom:"))
        #expect(result.pcbReference.hasPrefix("pcb:"))
        #expect(result.footprintReference.hasPrefix("footprint:"))
        #expect(result.liveEvidenceCount > 0)
        #expect(host.lastBoardRelease == result)
    }

    @Test("Denied and expired board release exports remain governed")
    func deniedAndExpiredBoardReleaseExport() async throws {
        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-gsa-denials-\(UUID().uuidString)", isDirectory: true)
        let artifactRoot = storageDirectory.appendingPathComponent("artifacts", isDirectory: true)
        let config = GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [storageDirectory, artifactRoot],
            allowedExecutables: []
        )
        let host = GSAPlatformHost(configuration: config)
        defer { try? FileManager.default.removeItem(at: storageDirectory) }

        host.boot()
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while host.state == .booting, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }

        let deniedID = try await host.runDeniedBoardReleaseExport()
        let expiredID = try await host.runExpiredBoardReleaseExport()

        #expect(host.lastDeniedApprovalID == deniedID)
        #expect(host.lastExpiredApprovalID == expiredID)
    }

    @Test("Governed board release maps into a completion summary")
    func governedBoardReleaseSummary() async throws {
        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-gsa-summary-\(UUID().uuidString)", isDirectory: true)
        let artifactRoot = storageDirectory.appendingPathComponent("artifacts", isDirectory: true)
        let config = GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [storageDirectory, artifactRoot],
            allowedExecutables: []
        )
        let host = GSAPlatformHost(configuration: config)
        defer { try? FileManager.default.removeItem(at: storageDirectory) }

        host.boot()
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while host.state == .booting, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }

        _ = try await host.recordVerificationEvidence(
            checkType: "ERC",
            filePath: "/tmp/demo.kicad_sch",
            passed: true,
            warningCount: 0,
            errorCount: 0,
            failures: [],
            context: governedContext
        )
        let release = try await host.runGovernedBoardReleaseExport(context: governedContext)
        let handoff = try await host.runGovernedManufacturingHandoff(context: governedContext)
        let summary = GovernedReleaseSummaryBuilder.build(
            from: release,
            manufacturingHandoff: handoff,
            verification: host.lastVerificationEvidence,
            totalDurationSeconds: 2
        )

        #expect(summary.phaseName == "Board Release Export")
        #expect(summary.exports.count == 2)
        #expect(summary.exports.first?.fileName == "volta-board-release.zip")
        #expect(summary.exports.last?.fileName == "volta-board-handoff.zip")
        #expect(release.objectReference.hasPrefix("object:"))
        #expect(release.projectReference.hasPrefix("project:"))
        #expect(release.revisionReference.hasPrefix("revision:"))
        #expect(release.schematicReference.hasPrefix("schematic:"))
        #expect(release.sheetReference.hasPrefix("sheet:"))
        #expect(release.componentReference.hasPrefix("component:"))
        #expect(release.netReference.hasPrefix("net:"))
        #expect(release.bomReference.hasPrefix("bom:"))
        #expect(release.pcbReference.hasPrefix("pcb:"))
        #expect(release.footprintReference.hasPrefix("footprint:"))
        #expect(summary.governedExport?.approvalRequestID == release.approvalRequestID)
        #expect(summary.governedExport?.evidenceCount == release.liveEvidenceCount)
        #expect(summary.governedExport?.projectReference == release.projectReference)
        #expect(summary.governedExport?.revisionReference == release.revisionReference)
        #expect(summary.governedExport?.schematicReference == release.schematicReference)
        #expect(summary.governedExport?.sheetReference == release.sheetReference)
        #expect(summary.governedExport?.componentReference == release.componentReference)
        #expect(summary.governedExport?.netReference == release.netReference)
        #expect(summary.governedExport?.bomReference == release.bomReference)
        #expect(summary.governedExport?.pcbReference == release.pcbReference)
        #expect(summary.governedExport?.footprintReference == release.footprintReference)
        #expect(summary.governedExport?.objectReference == release.objectReference)
        #expect(summary.governedManufacturingHandoff?.approvalRequestID == handoff.approvalRequestID)
        #expect(summary.governedManufacturingHandoff?.projectReference == release.projectReference)
        #expect(summary.governedManufacturingHandoff?.revisionReference == release.revisionReference)
        #expect(summary.governedManufacturingHandoff?.schematicReference == release.schematicReference)
        #expect(summary.governedManufacturingHandoff?.sheetReference == release.sheetReference)
        #expect(summary.governedManufacturingHandoff?.componentReference == release.componentReference)
        #expect(summary.governedManufacturingHandoff?.netReference == release.netReference)
        #expect(summary.governedManufacturingHandoff?.bomReference == release.bomReference)
        #expect(summary.governedManufacturingHandoff?.pcbReference == release.pcbReference)
        #expect(summary.governedManufacturingHandoff?.footprintReference == release.footprintReference)
        #expect(summary.governedManufacturingHandoff?.objectReference == release.objectReference)
        #expect(summary.governedManufacturingHandoff?.linkedVerificationClaim == host.lastVerificationEvidence?.claim)
        #expect(summary.governedExportURL?.lastPathComponent == "volta-board-release.zip")
        #expect(summary.governedVerification?.claim == host.lastVerificationEvidence?.claim)
        #expect(summary.governedVerification?.projectReference == release.projectReference)
        #expect(summary.governedVerification?.revisionReference == release.revisionReference)
        #expect(summary.governedVerification?.schematicReference == release.schematicReference)
        #expect(summary.governedVerification?.sheetReference == release.sheetReference)
        #expect(summary.governedVerification?.componentReference == release.componentReference)
        #expect(summary.governedVerification?.netReference == release.netReference)
        #expect(summary.governedVerification?.bomReference == release.bomReference)
        #expect(summary.governedVerification?.pcbReference == release.pcbReference)
        #expect(summary.governedVerification?.footprintReference == release.footprintReference)
        #expect(summary.governedVerification?.verificationArtifactReference == host.lastVerificationEvidence?.verificationArtifactReference)
        #expect(summary.governedVerification?.objectReference == release.objectReference)
        #expect(summary.governedVerification?.gateSatisfied == true)
    }

    @Test("Governed manufacturing handoff stays on the shared board-release object")
    func governedManufacturingHandoff() async throws {
        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-gsa-handoff-\(UUID().uuidString)", isDirectory: true)
        let artifactRoot = storageDirectory.appendingPathComponent("artifacts", isDirectory: true)
        let config = GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [storageDirectory, artifactRoot],
            allowedExecutables: []
        )
        let host = GSAPlatformHost(configuration: config)
        defer { try? FileManager.default.removeItem(at: storageDirectory) }

        host.boot()
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while host.state == .booting, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }

        _ = try await host.recordVerificationEvidence(
            checkType: "DRC",
            filePath: "/tmp/demo.kicad_pcb",
            passed: true,
            warningCount: 0,
            errorCount: 0,
            failures: [],
            context: governedContext
        )
        let release = try await host.runGovernedBoardReleaseExport(context: governedContext)
        let handoff = try await host.runGovernedManufacturingHandoff(context: governedContext)

        #expect(FileManager.default.fileExists(atPath: handoff.artifactPath))
        #expect(handoff.artifactPath.contains("volta-board-handoff.zip"))
        #expect(handoff.projectReference == release.projectReference)
        #expect(handoff.revisionReference == release.revisionReference)
        #expect(handoff.schematicReference == release.schematicReference)
        #expect(handoff.sheetReference == release.sheetReference)
        #expect(handoff.componentReference == release.componentReference)
        #expect(handoff.netReference == release.netReference)
        #expect(handoff.bomReference == release.bomReference)
        #expect(handoff.pcbReference == release.pcbReference)
        #expect(handoff.footprintReference == release.footprintReference)
        #expect(handoff.objectReference == release.objectReference)
        #expect(handoff.linkedVerificationClaim == host.lastVerificationEvidence?.claim)
        #expect(host.lastManufacturingHandoff == handoff)
    }

    @Test("Verification evidence records into the governed platform")
    func verificationEvidenceRecording() async throws {
        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-gsa-verification-\(UUID().uuidString)", isDirectory: true)
        let artifactRoot = storageDirectory.appendingPathComponent("artifacts", isDirectory: true)
        let config = GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [storageDirectory, artifactRoot],
            allowedExecutables: []
        )
        let host = GSAPlatformHost(configuration: config)
        defer { try? FileManager.default.removeItem(at: storageDirectory) }

        host.boot()
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while host.state == .booting, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }

        let result = try await host.recordVerificationEvidence(
            checkType: "ERC",
            filePath: "/tmp/demo.kicad_sch",
            passed: true,
            warningCount: 1,
            errorCount: 0,
            failures: [],
            context: governedContext
        )

        #expect(result.projectReference.hasPrefix("project:"))
        #expect(result.revisionReference.hasPrefix("revision:"))
        #expect(result.schematicReference.hasPrefix("schematic:"))
        #expect(result.sheetReference.hasPrefix("sheet:"))
        #expect(result.componentReference.hasPrefix("component:"))
        #expect(result.netReference.hasPrefix("net:"))
        #expect(result.bomReference.hasPrefix("bom:"))
        #expect(result.pcbReference.hasPrefix("pcb:"))
        #expect(result.footprintReference.hasPrefix("footprint:"))
        #expect(result.verificationArtifactReference.hasPrefix("verification-artifact:"))
        #expect(result.objectReference.hasPrefix("object:"))
        #expect(result.claim.contains("volta.erc.verification:"))
        #expect(result.passed == true)
        #expect(result.gateSatisfied == true)
        #expect(result.liveEvidenceCount > 0)
        #expect(result.historianChainCount > 0)
        #expect(host.lastVerificationEvidence == result)
    }

    @Test("Governed provider assembly check records external provider evidence")
    func governedProviderAssemblyCheck() async throws {
        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-gsa-provider-\(UUID().uuidString)", isDirectory: true)
        let artifactRoot = storageDirectory.appendingPathComponent("artifacts", isDirectory: true)
        let config = GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [storageDirectory, artifactRoot],
            allowedExecutables: []
        )
        let host = GSAPlatformHost(configuration: config)
        defer { try? FileManager.default.removeItem(at: storageDirectory) }

        host.boot()
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while host.state == .booting, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }

        let availability = AssemblyAvailability(
            lcscPartNumber: "C2040",
            assemblyType: "basic",
            inStock: true,
            assemblyFee: nil,
            deliveryTime: "3-5 days"
        )
        let result = try await host.recordProviderAssemblyCheck(
            providerName: "jlcpcb",
            subjectIdentifier: "C2040",
            availability: availability,
            context: governedContext
        )

        #expect(result.projectReference.hasPrefix("project:"))
        #expect(result.revisionReference.hasPrefix("revision:"))
        #expect(result.pcbReference.hasPrefix("pcb:"))
        #expect(result.objectReference.hasPrefix("object:"))
        #expect(result.providerReference == "provider:jlcpcb")
        #expect(result.claim.contains("volta.jlcpcb.assembly-check.c2040:"))
        #expect(result.providerName == "jlcpcb")
        #expect(result.subjectIdentifier == "C2040")
        #expect(result.passed == true)
        #expect(result.liveEvidenceCount > 0)
        #expect(result.historianChainCount > 0)
        #expect(host.lastProviderCheck == result)
    }

    @Test("Governed compliance check records component compliance evidence")
    func governedComplianceCheck() async throws {
        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-gsa-compliance-\(UUID().uuidString)", isDirectory: true)
        let artifactRoot = storageDirectory.appendingPathComponent("artifacts", isDirectory: true)
        let config = GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [storageDirectory, artifactRoot],
            allowedExecutables: []
        )
        let host = GSAPlatformHost(configuration: config)
        defer { try? FileManager.default.removeItem(at: storageDirectory) }

        host.boot()
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while host.state == .booting, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }

        let result = try await host.recordComplianceCheck(
            providerName: "local-compliance",
            subjectIdentifier: "STM32F411RET6",
            lifecycleStatus: .active,
            rohsStatus: .compliant,
            riskAssessment: RiskAssessment(
                riskLevel: .low,
                score: 10,
                factors: ["active lifecycle"],
                confidence: 1.0
            ),
            context: governedContext
        )

        #expect(result.projectReference.hasPrefix("project:"))
        #expect(result.revisionReference.hasPrefix("revision:"))
        #expect(result.componentReference.hasPrefix("component:"))
        #expect(result.objectReference.hasPrefix("object:"))
        #expect(result.providerReference == "provider:local-compliance")
        #expect(result.claim.contains("volta.local-compliance.compliance-check.stm32f411ret6:"))
        #expect(result.lifecycleStatus == "active")
        #expect(result.rohsStatus == "compliant")
        #expect(result.riskLevel == "low")
        #expect(result.riskScore == 10)
        #expect(result.passed == true)
        #expect(result.liveEvidenceCount > 0)
        #expect(result.historianChainCount > 0)
        #expect(host.lastComplianceCheck == result)
    }

    @Test("Governed KiCad import records source evidence and traceability")
    func governedImportedDesign() async throws {
        let storageDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-gsa-import-\(UUID().uuidString)", isDirectory: true)
        let artifactRoot = storageDirectory.appendingPathComponent("artifacts", isDirectory: true)
        let config = GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [storageDirectory, artifactRoot],
            allowedExecutables: []
        )
        let host = GSAPlatformHost(configuration: config)
        defer { try? FileManager.default.removeItem(at: storageDirectory) }

        host.boot()
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while host.state == .booting, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }

        let importedFile = storageDirectory.appendingPathComponent("demo-board.kicad_pcb")
        try Data("(kicad_pcb)".utf8).write(to: importedFile)

        let result = try await host.recordImportedDesign(
            fileURL: importedFile,
            context: governedContext
        )

        #expect(result.projectReference.hasPrefix("project:"))
        #expect(result.revisionReference.hasPrefix("revision:"))
        #expect(result.schematicReference.hasPrefix("schematic:"))
        #expect(result.pcbReference.hasPrefix("pcb:"))
        #expect(result.objectReference.hasPrefix("object:"))
        #expect(result.sourceReference == "import-source:demo-board.kicad_pcb")
        #expect(result.importedFilePath == importedFile.path)
        #expect(result.importedFileType == "kicad_pcb")
        #expect(result.claim.contains("volta.import.kicad_pcb:"))
        #expect(result.liveEvidenceCount > 0)
        #expect(result.historianChainCount > 0)
        #expect(host.lastImportedDesign == result)
    }

}

#endif
