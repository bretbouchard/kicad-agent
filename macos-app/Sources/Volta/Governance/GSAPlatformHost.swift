#if os(macOS)

import Foundation
import OSLog
import Observation
import GSAPlatform
import GSAModeledWorld
import GSAObdurate
import GSAEvidence
import GSAHistorian

struct GSAPlatformHostConfiguration: Sendable {
    let storageDirectory: URL
    let artifactRoot: URL
    let allowedFileRoots: [URL]
    let allowedExecutables: [String]

    static func live(fileManager: FileManager = .default) -> GSAPlatformHostConfiguration {
        let appSupportBase = (try? fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )) ?? fileManager.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")

        let storageDirectory = appSupportBase
            .appendingPathComponent("VoltaPCB", isDirectory: true)
            .appendingPathComponent("gsa-platform", isDirectory: true)
        let artifactRoot = storageDirectory
            .appendingPathComponent("release-artifacts", isDirectory: true)
        let projectsRoot = appSupportBase
            .appendingPathComponent("VoltaPCB", isDirectory: true)
            .appendingPathComponent("projects", isDirectory: true)
        let currentDirectory = URL(fileURLWithPath: fileManager.currentDirectoryPath, isDirectory: true)

        var allowedExecutables: [String] = []
        if let daemonURL = ProcessManager.resolveDaemonURL() {
            allowedExecutables.append(daemonURL.path)
        }
        if let pythonURL = ProcessManager.resolvePythonURL() {
            allowedExecutables.append(pythonURL.path)
        }

        return GSAPlatformHostConfiguration(
            storageDirectory: storageDirectory,
            artifactRoot: artifactRoot,
            allowedFileRoots: [
                storageDirectory,
                artifactRoot,
                projectsRoot,
                fileManager.temporaryDirectory,
                currentDirectory,
            ],
            allowedExecutables: Array(Set(allowedExecutables)).sorted()
        )
    }
}

@MainActor
@Observable
final class GSAPlatformHost {
    struct GovernedProjectContext: Sendable, Equatable {
        let projectID: UUID
        let projectName: String
        let conversationID: UUID?
        let revision: Int

        init(
            projectID: UUID,
            projectName: String,
            conversationID: UUID? = nil,
            revision: Int = 1
        ) {
            self.projectID = projectID
            self.projectName = projectName
            self.conversationID = conversationID
            self.revision = revision
        }

        static let fallback = GovernedProjectContext(
            projectID: UUID(uuidString: "00000000-0000-0000-0000-000000000001")!,
            projectName: "Volta Board Release",
            conversationID: nil,
            revision: 1
        )
    }

    struct BoardReleaseFlowResult: Sendable, Equatable {
        let projectReference: String
        let revisionReference: String
        let schematicReference: String
        let sheetReference: String
        let componentReference: String
        let netReference: String
        let bomReference: String
        let pcbReference: String
        let footprintReference: String
        let objectID: UUID
        let objectReference: String
        let artifactPath: String
        let approvalRequestID: UUID
        let linkedVerificationClaim: String?
        let liveEvidenceCount: Int
        let pendingApprovalCount: Int
    }

    struct ManufacturingHandoffResult: Sendable, Equatable {
        let projectReference: String
        let revisionReference: String
        let schematicReference: String
        let sheetReference: String
        let componentReference: String
        let netReference: String
        let bomReference: String
        let pcbReference: String
        let footprintReference: String
        let objectID: UUID
        let objectReference: String
        let artifactPath: String
        let approvalRequestID: UUID
        let linkedVerificationClaim: String?
        let liveEvidenceCount: Int
        let pendingApprovalCount: Int
    }

    struct VerificationEvidenceResult: Sendable, Equatable {
        let projectReference: String
        let revisionReference: String
        let schematicReference: String
        let sheetReference: String
        let componentReference: String
        let netReference: String
        let bomReference: String
        let pcbReference: String
        let footprintReference: String
        let verificationArtifactReference: String
        let objectID: UUID
        let objectReference: String
        let evidenceID: UUID
        let claim: String
        let passed: Bool
        let warningCount: Int
        let errorCount: Int
        let gateSatisfied: Bool
        let gateFindings: [String]
        let liveEvidenceCount: Int
        let historianChainCount: Int
    }

    struct ProviderCheckResult: Sendable, Equatable {
        let projectReference: String
        let revisionReference: String
        let pcbReference: String
        let objectReference: String
        let providerReference: String
        let evidenceID: UUID
        let claim: String
        let providerName: String
        let subjectIdentifier: String
        let passed: Bool
        let liveEvidenceCount: Int
        let historianChainCount: Int
    }

    struct ComplianceCheckResult: Sendable, Equatable {
        let projectReference: String
        let revisionReference: String
        let componentReference: String
        let objectReference: String
        let providerReference: String
        let evidenceID: UUID
        let claim: String
        let providerName: String
        let subjectIdentifier: String
        let lifecycleStatus: String
        let rohsStatus: String
        let riskLevel: String
        let riskScore: Int
        let passed: Bool
        let liveEvidenceCount: Int
        let historianChainCount: Int
    }

    struct ImportedDesignResult: Sendable, Equatable {
        let projectReference: String
        let revisionReference: String
        let schematicReference: String
        let pcbReference: String
        let objectReference: String
        let evidenceID: UUID
        let claim: String
        let sourceReference: String
        let importedFilePath: String
        let importedFileType: String
        let liveEvidenceCount: Int
        let historianChainCount: Int
    }

    enum State: Equatable {
        case idle
        case booting
        case ready
        case failed(String)
    }

    private(set) var state: State = .idle
    private(set) var platform: Platform?
    private(set) var diagnostics: Platform.DiagnosticsSnapshot?
    private(set) var lastBoardRelease: BoardReleaseFlowResult?
    private(set) var lastManufacturingHandoff: ManufacturingHandoffResult?
    private(set) var lastVerificationEvidence: VerificationEvidenceResult?
    private(set) var lastProviderCheck: ProviderCheckResult?
    private(set) var lastComplianceCheck: ComplianceCheckResult?
    private(set) var lastImportedDesign: ImportedDesignResult?
    private(set) var lastDeniedApprovalID: UUID?
    private(set) var lastExpiredApprovalID: UUID?
    private var boardReleaseObjectID: WorldObjectID?
    private var projectObjectID: WorldObjectID?
    private var revisionObjectID: WorldObjectID?
    private var schematicObjectID: WorldObjectID?
    private var sheetObjectID: WorldObjectID?
    private var componentObjectID: WorldObjectID?
    private var netObjectID: WorldObjectID?
    private var bomObjectID: WorldObjectID?
    private var pcbObjectID: WorldObjectID?
    private var footprintObjectID: WorldObjectID?
    private var verificationArtifactObjectID: WorldObjectID?

    let configuration: GSAPlatformHostConfiguration

    init(configuration: GSAPlatformHostConfiguration = .live()) {
        self.configuration = configuration
    }

    func boot() {
        guard state != .booting && state != .ready else { return }
        state = .booting

        Task { @MainActor in
            await self.bootAsync()
        }
    }

    func refreshDiagnostics() async {
        guard let platform else { return }
        diagnostics = await platform.diagnostics()
    }

    func diagnosticsExport() -> WorldValue? {
        diagnostics?.export()
    }

    func recordVerificationEvidence(
        checkType: String,
        filePath: String,
        passed: Bool,
        warningCount: Int,
        errorCount: Int,
        failures: [String],
        context: GovernedProjectContext = .fallback
    ) async throws -> VerificationEvidenceResult {
        guard let platform else {
            throw NSError(domain: "GSAPlatformHost", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "GSA platform is not booted"
            ])
        }

        let projectObject = try await upsertProjectObject(on: platform, context: context)
        let projectReference = projectObjectReference(for: projectObject.id)
        let revisionObject = try await upsertRevisionObject(on: platform, context: context, status: passed ? "verified" : "verification_failed")
        let revisionReference = revisionObjectReference(for: revisionObject.id)
        let schematicObject = try await upsertSchematicObject(on: platform, context: context, status: passed ? "verified" : "verification_failed")
        let schematicReference = schematicObjectReference(for: schematicObject.id)
        let sheetObject = try await upsertSheetObject(on: platform, context: context, status: passed ? "verified" : "verification_failed")
        let sheetReference = sheetObjectReference(for: sheetObject.id)
        let componentObject = try await upsertComponentObject(on: platform, context: context, status: passed ? "verified" : "verification_failed")
        let componentReference = componentObjectReference(for: componentObject.id)
        let netObject = try await upsertNetObject(on: platform, context: context, status: passed ? "verified" : "verification_failed")
        let netReference = netObjectReference(for: netObject.id)
        let bomObject = try await upsertBOMObject(on: platform, context: context, status: passed ? "verified" : "verification_failed", artifactPath: nil)
        let bomReference = bomObjectReference(for: bomObject.id)
        let pcbObject = try await upsertPCBObject(on: platform, context: context, status: passed ? "verified" : "verification_failed", artifactPath: pcbArtifactPath(forCheckType: checkType, filePath: filePath))
        let pcbReference = pcbObjectReference(for: pcbObject.id)
        let footprintObject = try await upsertFootprintObject(on: platform, context: context, status: passed ? "verified" : "verification_failed")
        let footprintReference = footprintObjectReference(for: footprintObject.id)
        let verificationArtifactObject = try await upsertVerificationArtifactObject(
            on: platform,
            context: context,
            checkType: checkType,
            passed: passed,
            filePath: filePath
        )
        let verificationArtifactReference = verificationArtifactObjectReference(for: verificationArtifactObject.id)
        let boardObject = try await upsertBoardReleaseObject(
            on: platform,
            context: context,
            status: passed ? "verified" : "verification_failed",
            artifactPath: nil
        )
        let objectReference = boardReleaseObjectReference(for: boardObject.id)
        let claim = verificationClaim(checkType: checkType, objectID: boardObject.id)
        let evidence = Evidence(
            kind: .testRun,
            claim: claim,
            producer: Principal(rawValue: "system:volta-app"),
            ttl: 3600,
            payload: .object([
                "checkType": .string(checkType),
                "filePath": .string(filePath),
                "passed": .bool(passed),
                "warningCount": .int(warningCount),
                "errorCount": .int(errorCount),
                "failures": .array(failures.map(WorldValue.string)),
            ])
        )
        await platform.evidence.record(evidence)

        let verificationReference = "verification:\(evidence.id.uuidString)"
        let fileReference = "file:\(filePath)"
        await platform.historian.record(
            HistoricalEvent(
                category: .evidence,
                title: "\(checkType) verification recorded",
                detail: "\(checkType) \(passed ? "passed" : "failed") for \(filePath)",
                participants: [Principal(rawValue: "system:volta-app")],
                references: [verificationReference, fileReference, projectReference, revisionReference, schematicReference, sheetReference, componentReference, netReference, bomReference, pcbReference, footprintReference, verificationArtifactReference, objectReference, claim]
            )
        )

        let verdict = await CompletionGate(
            requirement: claim,
            bars: [
                EvidenceCountBar(kind: .testRun, minimum: 1),
                FreshnessBar(maxAge: 3600)
            ]
        ).evaluate(against: platform.evidence)

        let liveEvidence = await platform.evidence.liveEvidence()
        let chain = await platform.historian.chain(for: claim)
        let mapped = VerificationEvidenceResult(
            projectReference: projectReference,
            revisionReference: revisionReference,
            schematicReference: schematicReference,
            sheetReference: sheetReference,
            componentReference: componentReference,
            netReference: netReference,
            bomReference: bomReference,
            pcbReference: pcbReference,
            footprintReference: footprintReference,
            verificationArtifactReference: verificationArtifactReference,
            objectID: boardObject.id.value,
            objectReference: objectReference,
            evidenceID: evidence.id,
            claim: claim,
            passed: passed,
            warningCount: warningCount,
            errorCount: errorCount,
            gateSatisfied: verdict.satisfied,
            gateFindings: verdict.findings,
            liveEvidenceCount: liveEvidence.count,
            historianChainCount: chain.count
        )
        self.lastVerificationEvidence = mapped
        self.diagnostics = await platform.diagnostics()
        return mapped
    }

    func runGovernedBoardReleaseExport(
        context: GovernedProjectContext = .fallback
    ) async throws -> BoardReleaseFlowResult {
        guard let platform else {
            throw NSError(domain: "GSAPlatformHost", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "GSA platform is not booted"
            ])
        }

        try ensureArtifactRoot()
        let projectObject = try await upsertProjectObject(on: platform, context: context)
        let projectReference = projectObjectReference(for: projectObject.id)
        let revisionObject = try await upsertRevisionObject(on: platform, context: context, status: "released")
        let revisionReference = revisionObjectReference(for: revisionObject.id)
        let schematicObject = try await upsertSchematicObject(on: platform, context: context, status: "released")
        let schematicReference = schematicObjectReference(for: schematicObject.id)
        let sheetObject = try await upsertSheetObject(on: platform, context: context, status: "released")
        let sheetReference = sheetObjectReference(for: sheetObject.id)
        let componentObject = try await upsertComponentObject(on: platform, context: context, status: "released")
        let componentReference = componentObjectReference(for: componentObject.id)
        let netObject = try await upsertNetObject(on: platform, context: context, status: "released")
        let netReference = netObjectReference(for: netObject.id)
        let bomObject = try await upsertBOMObject(on: platform, context: context, status: "released", artifactPath: resultBOMPath(for: context, artifactRoot: configuration.artifactRoot))
        let bomReference = bomObjectReference(for: bomObject.id)
        let pcbObject = try await upsertPCBObject(on: platform, context: context, status: "released", artifactPath: resultPCBPath(for: context, artifactRoot: configuration.artifactRoot))
        let pcbReference = pcbObjectReference(for: pcbObject.id)
        let footprintObject = try await upsertFootprintObject(on: platform, context: context, status: "released")
        let footprintReference = footprintObjectReference(for: footprintObject.id)
        let harness = PlatformIntegrationHarness(
            storageDirectory: configuration.storageDirectory,
            allowedFileRoots: [configuration.artifactRoot],
            allowedExecutables: configuration.allowedExecutables
        )
        let scenario = AdopterIntegrationScenario(
            human: Principal(rawValue: "human:volta-operator"),
            system: Principal(rawValue: "system:volta-app")
        )
        let result = try await scenario.runGovernedRevisionArtifactFlow(
            on: platform,
            harness: harness,
            track: .init(
                title: "\(context.projectName) Board Release",
                typeName: "electronics.board.release"
            ),
            revision: .init(
                state: .object([
                    "title": .string("\(context.projectName) Board Release"),
                    "revision": .int(context.revision + 1),
                    "status": .string("verified"),
                    "projectID": .string(context.projectID.uuidString),
                ]),
                intent: "volta board release revision"
            ),
            approval: .init(
                title: "Export board release artifact",
                decision: "Write the governed Volta board release artifact to disk.",
                capabilities: ["fs.write", "fs.read"],
                ttl: 600
            ),
            fileName: "volta-board-release.zip",
            content: "governed volta board release artifact"
        )
        let boardObject = try await upsertBoardReleaseObject(
            on: platform,
            context: context,
            status: "released",
            artifactPath: result.artifactPath
        )
        let objectReference = boardReleaseObjectReference(for: boardObject.id)
        var exportReferences = [
            projectReference,
            revisionReference,
            schematicReference,
            sheetReference,
            componentReference,
            netReference,
            bomReference,
            pcbReference,
            footprintReference,
            objectReference,
            "approval:\(result.approvalRequestID.uuidString)",
            "artifact:\(result.artifactPath)"
        ]
        if let verificationClaim = lastVerificationEvidence?.claim {
            exportReferences.append(verificationClaim)
        }
        await platform.historian.record(
            HistoricalEvent(
                category: .capability,
                title: "Volta board release artifact exported",
                detail: "Governed board release artifact exported to \(result.artifactPath)",
                participants: [Principal(rawValue: "system:volta-app"), Principal(rawValue: "human:volta-operator")],
                references: exportReferences
            )
        )
        let mapped = BoardReleaseFlowResult(
            projectReference: projectReference,
            revisionReference: revisionReference,
            schematicReference: schematicReference,
            sheetReference: sheetReference,
            componentReference: componentReference,
            netReference: netReference,
            bomReference: bomReference,
            pcbReference: pcbReference,
            footprintReference: footprintReference,
            objectID: boardObject.id.value,
            objectReference: objectReference,
            artifactPath: result.artifactPath,
            approvalRequestID: result.approvalRequestID,
            linkedVerificationClaim: lastVerificationEvidence?.claim,
            liveEvidenceCount: result.liveEvidence.count,
            pendingApprovalCount: result.diagnostics.pendingApprovalCount
        )
        self.lastBoardRelease = mapped
        self.lastDeniedApprovalID = nil
        self.lastExpiredApprovalID = nil
        self.diagnostics = result.diagnostics
        return mapped
    }

    func runGovernedManufacturingHandoff(
        context: GovernedProjectContext = .fallback
    ) async throws -> ManufacturingHandoffResult {
        guard let platform else {
            throw NSError(domain: "GSAPlatformHost", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "GSA platform is not booted"
            ])
        }

        try ensureArtifactRoot()
        let projectObject = try await upsertProjectObject(on: platform, context: context)
        let projectReference = projectObjectReference(for: projectObject.id)
        let revisionObject = try await upsertRevisionObject(on: platform, context: context, status: "manufacturing_ready")
        let revisionReference = revisionObjectReference(for: revisionObject.id)
        let schematicObject = try await upsertSchematicObject(on: platform, context: context, status: "manufacturing_ready")
        let schematicReference = schematicObjectReference(for: schematicObject.id)
        let sheetObject = try await upsertSheetObject(on: platform, context: context, status: "manufacturing_ready")
        let sheetReference = sheetObjectReference(for: sheetObject.id)
        let componentObject = try await upsertComponentObject(on: platform, context: context, status: "manufacturing_ready")
        let componentReference = componentObjectReference(for: componentObject.id)
        let netObject = try await upsertNetObject(on: platform, context: context, status: "manufacturing_ready")
        let netReference = netObjectReference(for: netObject.id)
        let bomObject = try await upsertBOMObject(on: platform, context: context, status: "manufacturing_ready", artifactPath: resultBOMPath(for: context, artifactRoot: configuration.artifactRoot))
        let bomReference = bomObjectReference(for: bomObject.id)
        let pcbObject = try await upsertPCBObject(on: platform, context: context, status: "manufacturing_ready", artifactPath: resultPCBPath(for: context, artifactRoot: configuration.artifactRoot))
        let pcbReference = pcbObjectReference(for: pcbObject.id)
        let footprintObject = try await upsertFootprintObject(on: platform, context: context, status: "manufacturing_ready")
        let footprintReference = footprintObjectReference(for: footprintObject.id)
        let harness = PlatformIntegrationHarness(
            storageDirectory: configuration.storageDirectory,
            allowedFileRoots: [configuration.artifactRoot],
            allowedExecutables: configuration.allowedExecutables
        )
        let scenario = AdopterIntegrationScenario(
            human: Principal(rawValue: "human:volta-operator"),
            system: Principal(rawValue: "system:volta-app")
        )
        let result = try await scenario.runGovernedRevisionArtifactFlow(
            on: platform,
            harness: harness,
            track: .init(
                title: "\(context.projectName) Manufacturing Handoff",
                typeName: "electronics.board.release"
            ),
            revision: .init(
                state: .object([
                    "title": .string("\(context.projectName) Board Release"),
                    "revision": .int(context.revision + 2),
                    "status": .string("manufacturing_ready"),
                    "artifactKind": .string("manufacturing-handoff"),
                    "projectID": .string(context.projectID.uuidString),
                ]),
                intent: "volta manufacturing handoff revision"
            ),
            approval: .init(
                title: "Approve manufacturing handoff",
                decision: "Package the governed manufacturing handoff artifact for external fabrication.",
                capabilities: ["fs.write", "fs.read"],
                ttl: 600
            ),
            fileName: "volta-board-handoff.zip",
            content: "governed volta manufacturing handoff artifact"
        )
        let boardObject = try await upsertBoardReleaseObject(
            on: platform,
            context: context,
            status: "manufacturing_ready",
            artifactPath: result.artifactPath
        )
        let objectReference = boardReleaseObjectReference(for: boardObject.id)
        var handoffReferences = [
            projectReference,
            revisionReference,
            schematicReference,
            sheetReference,
            componentReference,
            netReference,
            bomReference,
            pcbReference,
            footprintReference,
            objectReference,
            "approval:\(result.approvalRequestID.uuidString)",
            "artifact:\(result.artifactPath)",
            "artifactKind:manufacturing-handoff"
        ]
        if let verificationClaim = lastVerificationEvidence?.claim {
            handoffReferences.append(verificationClaim)
        }
        if let boardReleaseArtifact = lastBoardRelease?.artifactPath {
            handoffReferences.append("release:\(boardReleaseArtifact)")
        }
        await platform.historian.record(
            HistoricalEvent(
                category: .capability,
                title: "Volta manufacturing handoff prepared",
                detail: "Governed manufacturing handoff artifact exported to \(result.artifactPath)",
                participants: [Principal(rawValue: "system:volta-app"), Principal(rawValue: "human:volta-operator")],
                references: handoffReferences
            )
        )
        let mapped = ManufacturingHandoffResult(
            projectReference: projectReference,
            revisionReference: revisionReference,
            schematicReference: schematicReference,
            sheetReference: sheetReference,
            componentReference: componentReference,
            netReference: netReference,
            bomReference: bomReference,
            pcbReference: pcbReference,
            footprintReference: footprintReference,
            objectID: boardObject.id.value,
            objectReference: objectReference,
            artifactPath: result.artifactPath,
            approvalRequestID: result.approvalRequestID,
            linkedVerificationClaim: lastVerificationEvidence?.claim,
            liveEvidenceCount: result.liveEvidence.count,
            pendingApprovalCount: result.diagnostics.pendingApprovalCount
        )
        self.lastManufacturingHandoff = mapped
        self.diagnostics = result.diagnostics
        return mapped
    }

    func runDeniedBoardReleaseExport() async throws -> UUID {
        guard let platform else {
            throw NSError(domain: "GSAPlatformHost", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "GSA platform is not booted"
            ])
        }

        try ensureArtifactRoot()
        let harness = PlatformIntegrationHarness(
            storageDirectory: configuration.storageDirectory,
            allowedFileRoots: [configuration.artifactRoot],
            allowedExecutables: configuration.allowedExecutables
        )
        let scenario = AdopterIntegrationScenario(
            human: Principal(rawValue: "human:volta-operator"),
            system: Principal(rawValue: "system:volta-app")
        )
        let result = try await scenario.runDeniedArtifactExportFlow(
            on: platform,
            harness: harness,
            track: .init(
                title: "Denied Volta Board Release",
                typeName: "electronics.board.release"
            ),
            approval: .init(
                title: "Deny board release export",
                decision: "Deny the governed Volta board release artifact export.",
                capabilities: ["fs.write", "fs.read"],
                ttl: 600
            ),
            fileName: "volta-board-release-denied.zip",
            content: "denied artifact"
        )
        self.lastDeniedApprovalID = result.approvalRequestID
        self.diagnostics = result.diagnostics
        return result.approvalRequestID
    }

    func runExpiredBoardReleaseExport() async throws -> UUID {
        guard let platform else {
            throw NSError(domain: "GSAPlatformHost", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "GSA platform is not booted"
            ])
        }

        try ensureArtifactRoot()
        let harness = PlatformIntegrationHarness(
            storageDirectory: configuration.storageDirectory,
            allowedFileRoots: [configuration.artifactRoot],
            allowedExecutables: configuration.allowedExecutables
        )
        let scenario = AdopterIntegrationScenario(
            human: Principal(rawValue: "human:volta-operator"),
            system: Principal(rawValue: "system:volta-app")
        )
        let result = try await scenario.runExpiredArtifactExportFlow(
            on: platform,
            harness: harness,
            track: .init(
                title: "Expired Volta Board Release",
                typeName: "electronics.board.release"
            ),
            seed: .init(
                approval: .init(
                    title: "Expire board release export",
                    decision: "Allow the governed Volta board release export to expire.",
                    capabilities: ["fs.write", "fs.read"],
                    ttl: 1
                )
            ),
            fileName: "volta-board-release-expired.zip",
            content: "expired artifact"
        )
        self.lastExpiredApprovalID = result.approvalRequestID
        self.diagnostics = result.diagnostics
        return result.approvalRequestID
    }

    func recordProviderAssemblyCheck(
        providerName: String,
        subjectIdentifier: String,
        availability: AssemblyAvailability,
        context: GovernedProjectContext = .fallback
    ) async throws -> ProviderCheckResult {
        guard let platform else {
            throw NSError(domain: "GSAPlatformHost", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "GSA platform is not booted"
            ])
        }

        let projectObject = try await upsertProjectObject(on: platform, context: context)
        let projectReference = projectObjectReference(for: projectObject.id)
        let revisionObject = try await upsertRevisionObject(on: platform, context: context, status: "provider_checked")
        let revisionReference = revisionObjectReference(for: revisionObject.id)
        let pcbObject = try await upsertPCBObject(on: platform, context: context, status: "provider_checked", artifactPath: nil)
        let pcbReference = pcbObjectReference(for: pcbObject.id)
        let boardObject = try await upsertBoardReleaseObject(
            on: platform,
            context: context,
            status: "provider_checked",
            artifactPath: nil
        )
        let objectReference = boardReleaseObjectReference(for: boardObject.id)

        let claim = providerAssemblyClaim(providerName: providerName, subjectIdentifier: subjectIdentifier, objectID: boardObject.id)
        let evidence = Evidence(
            kind: .testRun,
            claim: claim,
            producer: Principal(rawValue: "system:volta-app"),
            ttl: 3600,
            payload: .object([
                "provider": .string(providerName),
                "subjectIdentifier": .string(subjectIdentifier),
                "lcscPartNumber": .string(availability.lcscPartNumber),
                "assemblyType": .string(availability.assemblyType),
                "inStock": .bool(availability.inStock),
                "assemblyFee": availability.assemblyFee.map(WorldValue.double) ?? .null,
                "deliveryTime": availability.deliveryTime.map(WorldValue.string) ?? .null,
                "isAssemblyReady": .bool(availability.isAssemblyReady),
                "isBasicAssembly": .bool(availability.isBasicAssembly),
            ])
        )
        await platform.evidence.record(evidence)

        let providerReference = "provider:\(providerName)"
        await platform.historian.record(
            HistoricalEvent(
                category: .capability,
                title: "\(providerName) assembly provider check recorded",
                detail: "\(providerName) assembly status for \(subjectIdentifier): \(availability.assemblyType)",
                participants: [Principal(rawValue: "system:volta-app")],
                references: [
                    projectReference,
                    revisionReference,
                    pcbReference,
                    objectReference,
                    providerReference,
                    "subject:\(subjectIdentifier)",
                    claim
                ]
            )
        )

        let liveEvidence = await platform.evidence.liveEvidence()
        let chain = await platform.historian.chain(for: claim)
        let mapped = ProviderCheckResult(
            projectReference: projectReference,
            revisionReference: revisionReference,
            pcbReference: pcbReference,
            objectReference: objectReference,
            providerReference: providerReference,
            evidenceID: evidence.id,
            claim: claim,
            providerName: providerName,
            subjectIdentifier: subjectIdentifier,
            passed: availability.isAssemblyReady && availability.inStock,
            liveEvidenceCount: liveEvidence.count,
            historianChainCount: chain.count
        )
        self.lastProviderCheck = mapped
        self.diagnostics = await platform.diagnostics()
        return mapped
    }

    func recordComplianceCheck(
        providerName: String,
        subjectIdentifier: String,
        lifecycleStatus: LifecycleStatus,
        rohsStatus: RoHSStatus,
        riskAssessment: RiskAssessment,
        context: GovernedProjectContext = .fallback
    ) async throws -> ComplianceCheckResult {
        guard let platform else {
            throw NSError(domain: "GSAPlatformHost", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "GSA platform is not booted"
            ])
        }

        let projectObject = try await upsertProjectObject(on: platform, context: context)
        let projectReference = projectObjectReference(for: projectObject.id)
        let revisionObject = try await upsertRevisionObject(on: platform, context: context, status: "compliance_checked")
        let revisionReference = revisionObjectReference(for: revisionObject.id)
        let componentObject = try await upsertComponentObject(on: platform, context: context, status: "compliance_checked")
        let componentReference = componentObjectReference(for: componentObject.id)
        let boardObject = try await upsertBoardReleaseObject(
            on: platform,
            context: context,
            status: "compliance_checked",
            artifactPath: nil
        )
        let objectReference = boardReleaseObjectReference(for: boardObject.id)

        let claim = complianceClaim(providerName: providerName, subjectIdentifier: subjectIdentifier, objectID: boardObject.id)
        let evidence = Evidence(
            kind: .testRun,
            claim: claim,
            producer: Principal(rawValue: "system:volta-app"),
            ttl: 3600,
            payload: .object([
                "provider": .string(providerName),
                "subjectIdentifier": .string(subjectIdentifier),
                "lifecycleStatus": .string(lifecycleStatus.rawValue),
                "rohsStatus": .string(rohsStatus.rawValue),
                "riskLevel": .string(riskAssessment.riskLevel.rawValue),
                "riskScore": .int(riskAssessment.score),
                "riskConfidence": .double(riskAssessment.confidence),
                "riskFactors": .array(riskAssessment.factors.map(WorldValue.string)),
            ])
        )
        await platform.evidence.record(evidence)

        let providerReference = "provider:\(providerName)"
        await platform.historian.record(
            HistoricalEvent(
                category: .capability,
                title: "\(providerName) compliance check recorded",
                detail: "\(providerName) compliance for \(subjectIdentifier): \(lifecycleStatus.rawValue) / \(rohsStatus.rawValue)",
                participants: [Principal(rawValue: "system:volta-app")],
                references: [
                    projectReference,
                    revisionReference,
                    componentReference,
                    objectReference,
                    providerReference,
                    "subject:\(subjectIdentifier)",
                    claim
                ]
            )
        )

        let liveEvidence = await platform.evidence.liveEvidence()
        let chain = await platform.historian.chain(for: claim)
        let mapped = ComplianceCheckResult(
            projectReference: projectReference,
            revisionReference: revisionReference,
            componentReference: componentReference,
            objectReference: objectReference,
            providerReference: providerReference,
            evidenceID: evidence.id,
            claim: claim,
            providerName: providerName,
            subjectIdentifier: subjectIdentifier,
            lifecycleStatus: lifecycleStatus.rawValue,
            rohsStatus: rohsStatus.rawValue,
            riskLevel: riskAssessment.riskLevel.rawValue,
            riskScore: riskAssessment.score,
            passed: lifecycleStatus == .active && rohsStatus != .nonCompliant && riskAssessment.score < 50,
            liveEvidenceCount: liveEvidence.count,
            historianChainCount: chain.count
        )
        self.lastComplianceCheck = mapped
        self.diagnostics = await platform.diagnostics()
        return mapped
    }

    func recordImportedDesign(
        fileURL: URL,
        context: GovernedProjectContext = .fallback
    ) async throws -> ImportedDesignResult {
        guard let platform else {
            throw NSError(domain: "GSAPlatformHost", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "GSA platform is not booted"
            ])
        }

        let importedFileType = importedDesignType(for: fileURL)
        let projectObject = try await upsertProjectObject(on: platform, context: context)
        let projectReference = projectObjectReference(for: projectObject.id)
        let revisionObject = try await upsertRevisionObject(on: platform, context: context, status: "imported")
        let revisionReference = revisionObjectReference(for: revisionObject.id)
        let schematicObject = try await upsertSchematicObject(on: platform, context: context, status: "imported")
        let schematicReference = schematicObjectReference(for: schematicObject.id)
        let pcbObject = try await upsertPCBObject(
            on: platform,
            context: context,
            status: "imported",
            artifactPath: importedFileType == "kicad_pcb" ? fileURL.path : nil
        )
        let pcbReference = pcbObjectReference(for: pcbObject.id)
        let boardObject = try await upsertBoardReleaseObject(
            on: platform,
            context: context,
            status: "imported",
            artifactPath: fileURL.path
        )
        let objectReference = boardReleaseObjectReference(for: boardObject.id)

        let claim = importedDesignClaim(fileType: importedFileType, objectID: boardObject.id)
        let sourceReference = "import-source:\(fileURL.lastPathComponent)"
        let evidence = Evidence(
            kind: .testRun,
            claim: claim,
            producer: Principal(rawValue: "system:volta-app"),
            ttl: 3600,
            payload: .object([
                "fileName": .string(fileURL.lastPathComponent),
                "filePath": .string(fileURL.path),
                "fileType": .string(importedFileType),
                "projectID": .string(context.projectID.uuidString),
                "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            ])
        )
        await platform.evidence.record(evidence)

        await platform.historian.record(
            HistoricalEvent(
                category: .change,
                title: "Volta design import recorded",
                detail: "Imported \(fileURL.lastPathComponent) as \(importedFileType)",
                participants: [Principal(rawValue: "system:volta-app"), Principal(rawValue: "human:volta-operator")],
                references: [
                    projectReference,
                    revisionReference,
                    schematicReference,
                    pcbReference,
                    objectReference,
                    sourceReference,
                    "file:\(fileURL.path)",
                    claim
                ]
            )
        )

        let liveEvidence = await platform.evidence.liveEvidence()
        let chain = await platform.historian.chain(for: claim)
        let mapped = ImportedDesignResult(
            projectReference: projectReference,
            revisionReference: revisionReference,
            schematicReference: schematicReference,
            pcbReference: pcbReference,
            objectReference: objectReference,
            evidenceID: evidence.id,
            claim: claim,
            sourceReference: sourceReference,
            importedFilePath: fileURL.path,
            importedFileType: importedFileType,
            liveEvidenceCount: liveEvidence.count,
            historianChainCount: chain.count
        )
        self.lastImportedDesign = mapped
        self.diagnostics = await platform.diagnostics()
        return mapped
    }

    private func bootAsync() async {
        do {
            let platform = try await Platform.boot(
                storageDirectory: configuration.storageDirectory,
                allowedFileRoots: configuration.allowedFileRoots,
                allowedExecutables: configuration.allowedExecutables
            )
            self.platform = platform
            self.diagnostics = await platform.diagnostics()
            self.state = .ready
            Logger.appShell.info(
                "GSA platform booted at \(self.configuration.storageDirectory.path, privacy: .public)"
            )
        } catch {
            self.platform = nil
            self.diagnostics = nil
            self.state = .failed(error.localizedDescription)
            Logger.appShell.error(
                "GSA platform boot failed: \(error.localizedDescription, privacy: .public)"
            )
        }
    }

    private func ensureArtifactRoot() throws {
        try FileManager.default.createDirectory(
            at: configuration.artifactRoot,
            withIntermediateDirectories: true
        )
    }

    private func verificationClaim(checkType: String, objectID: WorldObjectID) -> String {
        "volta.\(checkType.lowercased()).verification:\(objectID.value.uuidString)"
    }

    private func providerAssemblyClaim(providerName: String, subjectIdentifier: String, objectID: WorldObjectID) -> String {
        let sanitizedSubject = subjectIdentifier.replacingOccurrences(of: " ", with: "-").lowercased()
        return "volta.\(providerName.lowercased()).assembly-check.\(sanitizedSubject):\(objectID.value.uuidString)"
    }

    private func complianceClaim(providerName: String, subjectIdentifier: String, objectID: WorldObjectID) -> String {
        let sanitizedSubject = subjectIdentifier.replacingOccurrences(of: " ", with: "-").lowercased()
        return "volta.\(providerName.lowercased()).compliance-check.\(sanitizedSubject):\(objectID.value.uuidString)"
    }

    private func importedDesignClaim(fileType: String, objectID: WorldObjectID) -> String {
        "volta.import.\(fileType.lowercased()):\(objectID.value.uuidString)"
    }

    private func importedDesignType(for fileURL: URL) -> String {
        switch fileURL.pathExtension.lowercased() {
        case "kicad_sch":
            return "kicad_sch"
        case "kicad_pcb":
            return "kicad_pcb"
        default:
            return "unknown"
        }
    }

    private func projectObjectReference(for objectID: WorldObjectID) -> String {
        "project:\(objectID.value.uuidString)"
    }

    private func revisionObjectReference(for objectID: WorldObjectID) -> String {
        "revision:\(objectID.value.uuidString)"
    }

    private func schematicObjectReference(for objectID: WorldObjectID) -> String {
        "schematic:\(objectID.value.uuidString)"
    }

    private func sheetObjectReference(for objectID: WorldObjectID) -> String {
        "sheet:\(objectID.value.uuidString)"
    }

    private func componentObjectReference(for objectID: WorldObjectID) -> String {
        "component:\(objectID.value.uuidString)"
    }

    private func netObjectReference(for objectID: WorldObjectID) -> String {
        "net:\(objectID.value.uuidString)"
    }

    private func bomObjectReference(for objectID: WorldObjectID) -> String {
        "bom:\(objectID.value.uuidString)"
    }

    private func pcbObjectReference(for objectID: WorldObjectID) -> String {
        "pcb:\(objectID.value.uuidString)"
    }

    private func footprintObjectReference(for objectID: WorldObjectID) -> String {
        "footprint:\(objectID.value.uuidString)"
    }

    private func verificationArtifactObjectReference(for objectID: WorldObjectID) -> String {
        "verification-artifact:\(objectID.value.uuidString)"
    }

    private func boardReleaseObjectReference(for objectID: WorldObjectID) -> String {
        "object:\(objectID.value.uuidString)"
    }

    private func resultBOMPath(for context: GovernedProjectContext, artifactRoot: URL) -> String {
        artifactRoot
            .appendingPathComponent("\(context.projectName.replacingOccurrences(of: " ", with: "-").lowercased())-bom.csv")
            .path
    }

    private func resultPCBPath(for context: GovernedProjectContext, artifactRoot: URL) -> String {
        artifactRoot
            .appendingPathComponent("\(context.projectName.replacingOccurrences(of: " ", with: "-").lowercased())-board.kicad_pcb")
            .path
    }

    private func pcbArtifactPath(forCheckType checkType: String, filePath: String) -> String? {
        checkType.caseInsensitiveCompare("DRC") == .orderedSame ? filePath : nil
    }

    private func upsertProjectObject(
        on platform: Platform,
        context: GovernedProjectContext
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.project"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let projectObjectID,
               let pinned = snapshot.objects[projectObjectID],
               pinned.typeName == "electronics.project",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.project" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "title": .string(context.projectName),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "revision": .int(context.revision),
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta project state"
                )
            ]).last ?? existing
            self.projectObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.project", initialState: newState),
                authorizedBy: principal,
                intent: "create volta project object"
            )
        ]).last!
        self.projectObjectID = created.id
        return created
    }

    private func upsertRevisionObject(
        on platform: Platform,
        context: GovernedProjectContext,
        status: String
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.project.revision"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let revisionObjectID,
               let pinned = snapshot.objects[revisionObjectID],
               pinned.typeName == "electronics.project.revision",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.project.revision" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "projectName": .string(context.projectName),
            "revision": .int(context.revision),
            "status": .string(status),
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta revision state"
                )
            ]).last ?? existing
            self.revisionObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.project.revision", initialState: newState),
                authorizedBy: principal,
                intent: "create volta revision object"
            )
        ]).last!
        self.revisionObjectID = created.id
        return created
    }

    private func upsertSchematicObject(
        on platform: Platform,
        context: GovernedProjectContext,
        status: String
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.schematic"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let schematicObjectID,
               let pinned = snapshot.objects[schematicObjectID],
               pinned.typeName == "electronics.schematic",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.schematic" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "projectName": .string(context.projectName),
            "revision": .int(context.revision),
            "status": .string(status),
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta schematic state"
                )
            ]).last ?? existing
            self.schematicObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.schematic", initialState: newState),
                authorizedBy: principal,
                intent: "create volta schematic object"
            )
        ]).last!
        self.schematicObjectID = created.id
        return created
    }

    private func upsertSheetObject(
        on platform: Platform,
        context: GovernedProjectContext,
        status: String
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.sheet"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let sheetObjectID,
               let pinned = snapshot.objects[sheetObjectID],
               pinned.typeName == "electronics.sheet",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.sheet" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "projectName": .string(context.projectName),
            "revision": .int(context.revision),
            "sheetName": .string("Main"),
            "sheetIndex": .int(1),
            "status": .string(status),
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta sheet state"
                )
            ]).last ?? existing
            self.sheetObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.sheet", initialState: newState),
                authorizedBy: principal,
                intent: "create volta sheet object"
            )
        ]).last!
        self.sheetObjectID = created.id
        return created
    }

    private func upsertComponentObject(
        on platform: Platform,
        context: GovernedProjectContext,
        status: String
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.component"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let componentObjectID,
               let pinned = snapshot.objects[componentObjectID],
               pinned.typeName == "electronics.component",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.component" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "projectName": .string(context.projectName),
            "revision": .int(context.revision),
            "componentSet": .string("release-default"),
            "status": .string(status),
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta component state"
                )
            ]).last ?? existing
            self.componentObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.component", initialState: newState),
                authorizedBy: principal,
                intent: "create volta component object"
            )
        ]).last!
        self.componentObjectID = created.id
        return created
    }

    private func upsertNetObject(
        on platform: Platform,
        context: GovernedProjectContext,
        status: String
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.net"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let netObjectID,
               let pinned = snapshot.objects[netObjectID],
               pinned.typeName == "electronics.net",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.net" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "projectName": .string(context.projectName),
            "revision": .int(context.revision),
            "netSet": .string("release-default"),
            "status": .string(status),
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta net state"
                )
            ]).last ?? existing
            self.netObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.net", initialState: newState),
                authorizedBy: principal,
                intent: "create volta net object"
            )
        ]).last!
        self.netObjectID = created.id
        return created
    }

    private func upsertBOMObject(
        on platform: Platform,
        context: GovernedProjectContext,
        status: String,
        artifactPath: String?
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.bom"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let bomObjectID,
               let pinned = snapshot.objects[bomObjectID],
               pinned.typeName == "electronics.bom",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.bom" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "projectName": .string(context.projectName),
            "revision": .int(context.revision),
            "status": .string(status),
            "artifactPath": artifactPath.map(WorldValue.string) ?? .null,
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta bom state"
                )
            ]).last ?? existing
            self.bomObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.bom", initialState: newState),
                authorizedBy: principal,
                intent: "create volta bom object"
            )
        ]).last!
        self.bomObjectID = created.id
        return created
    }

    private func upsertPCBObject(
        on platform: Platform,
        context: GovernedProjectContext,
        status: String,
        artifactPath: String?
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.pcb"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let pcbObjectID,
               let pinned = snapshot.objects[pcbObjectID],
               pinned.typeName == "electronics.pcb",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.pcb" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "projectName": .string(context.projectName),
            "revision": .int(context.revision),
            "status": .string(status),
            "artifactPath": artifactPath.map(WorldValue.string) ?? .null,
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta pcb state"
                )
            ]).last ?? existing
            self.pcbObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.pcb", initialState: newState),
                authorizedBy: principal,
                intent: "create volta pcb object"
            )
        ]).last!
        self.pcbObjectID = created.id
        return created
    }

    private func upsertFootprintObject(
        on platform: Platform,
        context: GovernedProjectContext,
        status: String
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.footprint"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let footprintObjectID,
               let pinned = snapshot.objects[footprintObjectID],
               pinned.typeName == "electronics.footprint",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.footprint" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "projectName": .string(context.projectName),
            "revision": .int(context.revision),
            "footprintSet": .string("release-default"),
            "status": .string(status),
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta footprint state"
                )
            ]).last ?? existing
            self.footprintObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.footprint", initialState: newState),
                authorizedBy: principal,
                intent: "create volta footprint object"
            )
        ]).last!
        self.footprintObjectID = created.id
        return created
    }

    private func upsertVerificationArtifactObject(
        on platform: Platform,
        context: GovernedProjectContext,
        checkType: String,
        passed: Bool,
        filePath: String
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.verification.artifact"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let verificationArtifactObjectID,
               let pinned = snapshot.objects[verificationArtifactObjectID],
               pinned.typeName == "electronics.verification.artifact",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.verification.artifact" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "projectName": .string(context.projectName),
            "revision": .int(context.revision),
            "checkType": .string(checkType),
            "passed": .bool(passed),
            "artifactPath": .string(filePath),
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta verification artifact state"
                )
            ]).last ?? existing
            self.verificationArtifactObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.verification.artifact", initialState: newState),
                authorizedBy: principal,
                intent: "create volta verification artifact object"
            )
        ]).last!
        self.verificationArtifactObjectID = created.id
        return created
    }

    private func upsertBoardReleaseObject(
        on platform: Platform,
        context: GovernedProjectContext,
        status: String,
        artifactPath: String?
    ) async throws -> WorldObject {
        let principal = Principal(rawValue: "system:volta-app")
        await platform.policy.issue(
            AuthorityGrant(
                principal: principal,
                scope: GrantScope(typeNames: ["electronics.board.release"]),
                grantedBy: Principal(rawValue: "human:volta-operator")
            )
        )

        let snapshot = await platform.runtime.snapshot()
        let existing: WorldObject? = {
            if let boardReleaseObjectID,
               let pinned = snapshot.objects[boardReleaseObjectID],
               pinned.typeName == "electronics.board.release",
               pinned.status == .live {
                return pinned
            }
            return snapshot.objects.values.first {
                $0.typeName == "electronics.board.release" && $0.status == .live
            }
        }()
        let newState: WorldValue = .object([
            "projectID": .string(context.projectID.uuidString),
            "projectName": .string(context.projectName),
            "conversationID": context.conversationID.map { .string($0.uuidString) } ?? .null,
            "title": .string("\(context.projectName) Board Release"),
            "revision": .int(context.revision),
            "status": .string(status),
            "artifactPath": artifactPath.map(WorldValue.string) ?? .null,
            "updatedAt": .string(ISO8601DateFormatter().string(from: Date())),
        ])

        if let existing {
            let updated = try await platform.runtime.transact([
                GovernedChange(
                    target: existing.id,
                    operation: .mutate(newState: newState),
                    authorizedBy: principal,
                    intent: "update volta board release state"
                )
            ]).last ?? existing
            self.boardReleaseObjectID = updated.id
            return updated
        }

        let objectID = WorldObjectID()
        let created = try await platform.runtime.transact([
            GovernedChange(
                target: objectID,
                operation: .create(typeName: "electronics.board.release", initialState: newState),
                authorizedBy: principal,
                intent: "create volta board release object"
            )
        ]).last!
        self.boardReleaseObjectID = created.id
        return created
    }
}

#endif
