import Foundation
import Testing
import GSAPlatform
import GSAModeledWorld

@Suite("Volta GSA Platform Proof")
struct VoltaGSAPlatformProofTests {

    @Test("Volta repo can run the packaged governed revision artifact scenario for a board release")
    func governedRevisionArtifactFlow() async throws {
        let harness = try PlatformIntegrationHarness.temporary(
            prefix: "volta-phase2-proof",
            includeFileRoot: true
        )
        defer { try? harness.cleanup() }

        let platform = try await harness.boot()
        let scenario = AdopterIntegrationScenario(
            actors: .init(
                human: Principal(rawValue: "human:volta"),
                system: Principal(rawValue: "system:volta")
            )
        )

        let result = try await scenario.runGovernedRevisionArtifactFlow(
            on: platform,
            harness: harness,
            track: .init(
                title: "Volta Board Release",
                typeName: "electronics.board.release"
            ),
            revision: .init(
                state: .object([
                    "title": .string("Volta Board Release"),
                    "revision": .int(2),
                    "status": .string("verified"),
                    "artifactKind": .string("manufacturing-handoff"),
                ]),
                intent: "prove governed revision plus manufacturing artifact flow in Volta"
            ),
            fileName: "volta-board-handoff.zip",
            content: "volta governed board handoff"
        )

        #expect(result.artifactPath.contains("volta-board-handoff.zip"))
        #expect(result.capabilityResult.evidence.claim.contains("volta-board-handoff.zip"))
        #expect(result.liveEvidence.count == 1)
        #expect(result.approvalChain.count == 3)
        #expect(result.diagnostics.runtime.metrics.successfulTransactions == 2)
        #expect(result.finalObject?.version == 2)
    }
}
