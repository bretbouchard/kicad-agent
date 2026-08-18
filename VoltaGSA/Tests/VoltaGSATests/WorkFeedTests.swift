import Foundation
import Testing
import GSACore
import GSAModeledWorld
import GSAObdurate
import GSAEvidence
import GSAArtifacts
import GSACapabilityKernel
import GSD
import GSAPlatform
@testable import VoltaGSA

@Suite("Volta feeds the Work Overview (VO-WO-1)")
struct VoltaWorkFeedTests {

    @Test("Governed Volta plans surface as canonical work items")
    func workStateFeedsProjection() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-feed-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let bret = Principal(rawValue: "human:bret")

        let platform = try await Platform.boot(storageDirectory: dir)
        await platform.policy.issue(
            AuthorityGrant(principal: bret, scope: .everything, grantedBy: bret)
        )

        // Volta plans its gap-closure work as a governed plan.
        let plan = try await GovernedPlan.create(
            intent: "Volta gap-closure phase 247",
            runtime: platform.runtime,
            evidenceLedger: platform.evidence,
            authorizedBy: bret,
            historian: platform.historian
        )
        let layout = WorkItem(
            title: "Route differential pairs",
            intent: "USB 90-ohm pairs length-matched"
        )
        _ = try await plan.add(layout)

        // The canonical projection sees it — Michelle, the table, and
        // the answers all read the same items.
        let snapshot = await platform.workProgressSnapshot(
            query: .init(scope: .plans, includeVerified: true)
        )
        #expect(snapshot.items.contains {
            $0.title == "Route differential pairs" || $0.title.contains("Volta gap-closure")
        })

        let remaining = await platform.remainingWork(scope: .all)
        #expect(!remaining.isEmpty)
    }

    @Test("AI-attributed exports mint with complete attribution (VO-TRUST-3 plumbing)")
    func aiAttributionOnExports() async throws {
        let registry = ArtifactRegistry()
        let board = WorldObjectID()

        // An LLM-proposed board revision, exported under attribution.
        let manifest = ArtifactManifest(
            entityType: "file",
            operation: "export",
            sourceObjects: [board],
            runtimeVersion: "VoltaGSA",
            toolchain: "electronics.export@1 (LLM-proposed revision)",
            outputs: ["revision-C.json"],
            author: Principal(rawValue: "capability:electronics.export"),
            governingChange: ChangeID(),
            aiAttribution: AIAttribution(
                modelIdentifier: "volta-layout-assistant",
                modelVersion: "2.3",
                humanReviewStatus: .reviewed,
                verificationOutcome: "DRC clean; human approved geometry"
            ),
            hashes: ["revision-C.json": ArtifactHash.sha256("proposed geometry")],
            evidenceReferences: ["evidence:\(UUID().uuidString)"],
            reproducibility: .deterministic
        )

        let daid = try await registry.mint(manifest)
        let stored = await registry.manifest(for: daid)
        #expect(stored?.aiAttribution?.modelIdentifier == "volta-layout-assistant")
        #expect(stored?.aiAttribution?.humanReviewStatus == .reviewed)
    }
}
