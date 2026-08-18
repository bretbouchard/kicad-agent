import Foundation

#if os(macOS)

enum GovernedReleaseSummaryBuilder {
    static func build(
        from release: GSAPlatformHost.BoardReleaseFlowResult,
        manufacturingHandoff: GSAPlatformHost.ManufacturingHandoffResult? = nil,
        phaseName: String = "Board Release Export",
        verification: GSAPlatformHost.VerificationEvidenceResult? = nil,
        totalDurationSeconds: Int
    ) -> CompletionSummary {
        let artifactURL = URL(fileURLWithPath: release.artifactPath)
        let artifactSize = (try? artifactURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        let manufacturingArtifact = manufacturingHandoff.map { handoff in
            ExportArtifact(
                fileName: URL(fileURLWithPath: handoff.artifactPath).lastPathComponent,
                fileSizeBytes: Int64((try? URL(fileURLWithPath: handoff.artifactPath)
                    .resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0),
                kind: .other
            )
        }

        return CompletionSummary(
            phaseName: phaseName,
            exports: [
                ExportArtifact(
                    fileName: artifactURL.lastPathComponent,
                    fileSizeBytes: Int64(artifactSize),
                    kind: .other
                )
            ] + (manufacturingArtifact.map { [$0] } ?? []),
            governedExport: GovernedExportSummary(
                projectReference: release.projectReference,
                revisionReference: release.revisionReference,
                schematicReference: release.schematicReference,
                sheetReference: release.sheetReference,
                componentReference: release.componentReference,
                netReference: release.netReference,
                bomReference: release.bomReference,
                pcbReference: release.pcbReference,
                footprintReference: release.footprintReference,
                objectReference: release.objectReference,
                artifactPath: release.artifactPath,
                approvalRequestID: release.approvalRequestID,
                evidenceCount: release.liveEvidenceCount
            ),
            governedManufacturingHandoff: manufacturingHandoff.map {
                GovernedManufacturingHandoffSummary(
                    projectReference: $0.projectReference,
                    revisionReference: $0.revisionReference,
                    schematicReference: $0.schematicReference,
                    sheetReference: $0.sheetReference,
                    componentReference: $0.componentReference,
                    netReference: $0.netReference,
                    bomReference: $0.bomReference,
                    pcbReference: $0.pcbReference,
                    footprintReference: $0.footprintReference,
                    objectReference: $0.objectReference,
                    artifactPath: $0.artifactPath,
                    approvalRequestID: $0.approvalRequestID,
                    linkedVerificationClaim: $0.linkedVerificationClaim,
                    evidenceCount: $0.liveEvidenceCount
                )
            },
            governedVerification: verification.map {
                GovernedVerificationSummary(
                    projectReference: $0.projectReference,
                    revisionReference: $0.revisionReference,
                    schematicReference: $0.schematicReference,
                    sheetReference: $0.sheetReference,
                    componentReference: $0.componentReference,
                    netReference: $0.netReference,
                    bomReference: $0.bomReference,
                    pcbReference: $0.pcbReference,
                    footprintReference: $0.footprintReference,
                    verificationArtifactReference: $0.verificationArtifactReference,
                    objectReference: $0.objectReference,
                    claim: $0.claim,
                    gateSatisfied: $0.gateSatisfied,
                    liveEvidenceCount: $0.liveEvidenceCount,
                    historianChainCount: $0.historianChainCount
                )
            },
            decisionsCount: 1,
            totalDurationSeconds: max(totalDurationSeconds, 0)
        )
    }
}

#endif
