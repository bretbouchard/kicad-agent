import Testing
import Foundation
@testable import VoltaGSA
import GSACore
import GSAModeledWorld
import GSAEvidence
import GSACapabilityKernel

// M2.3/M2.4-seed evidence: electronics operations execute only through the
// broker, default-deny blocks ungranted invocation, approvals mint scoped
// authority for humans to delegate, and every execution produces verified
// evidence.

@Suite(.serialized) struct CapabilityApprovalTests {
    static let founder = VoltaPrincipals.human("bret")
    static let human = VoltaPrincipals.human("bret")
    static let wrongHuman = VoltaPrincipals.human("someone-else")
    static let boardAgent = VoltaPrincipals.boardAgent

    static func makeStorage() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("VoltaGSA-\(UUID().uuidString)", isDirectory: true)
    }

    static func exportInput(volta: VoltaPlatform) -> WorldValue {
        .object([
            "projectName": .string("Smart Grid Breakout"),
            "project": .object([
                "legacyID": .string("AAAAAAAA-BBBB-CCCC-DDDD-000000000001"),
                "name": .string("Smart Grid Breakout"),
                "componentCount": .int(2),
            ]),
            "outputDir": .string(volta.artifactRoot.path),
        ])
    }

    @Test func capabilitiesAreRegisteredBehindTheBroker() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        let registered = await volta.platform.broker.registeredCapabilities()
        #expect(registered.contains(CapabilityID(name: "electronics.export", version: 1)))
        // Standard capabilities from Platform.boot are present too.
        #expect(registered.contains(CapabilityID(name: "fs.write", version: 1)))
    }

    @Test func ungrantedCapabilityInvocationIsDenied() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())

        do {
            _ = try await volta.platform.broker.invoke(
                CapabilityID(name: "electronics.export", version: 1),
                input: Self.exportInput(volta: volta),
                as: Self.boardAgent
            )
            Issue.record("board agent must not export without granted authority")
        } catch let violation as ContractViolation {
            #expect(violation.contract == .authority)
            #expect(violation.summary.contains("electronics.export"))
        }

        // Nothing was written and no evidence was recorded.
        let artifacts = try FileManager.default.contentsOfDirectory(
            at: volta.artifactRoot,
            includingPropertiesForKeys: nil
        )
        #expect(artifacts.isEmpty)
        let evidenceCount = await volta.platform.evidence.recordedCount
        #expect(evidenceCount == 0)
    }

    @Test func sandboxEscapeIsRefused() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        // Exporting outside the allowed roots is refused before any write.
        do {
            _ = try await volta.platform.broker.invoke(
                CapabilityID(name: "electronics.export", version: 1),
                input: .object([
                    "projectName": .string("Escape"),
                    "project": .object([:]),
                    "outputDir": .string("/tmp"),
                ]),
                as: Self.founder
            )
            Issue.record("writes outside the allowed roots must be refused")
        } catch let error as CapabilityInputError {
            guard case .outsideSandbox = error else {
                Issue.record("expected outsideSandbox, got \(error)")
                return
            }
        }
    }

    @Test func approvedExportAuthorityLetsAgentExportWithEvidence() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        // 1. The agent asks; 2. the human approves; 3. authority is minted.
        let request = await volta.approvals.requestExportAuthority(
            requester: Self.boardAgent,
            human: Self.human,
            projectName: "Smart Grid Breakout"
        )
        #expect(request.grantsScope.capabilities == ["electronics.export"])

        // The wrong human cannot decide it.
        await {
            do {
                try await volta.approvals.decide(
                    request.id, as: Self.wrongHuman, approved: true
                )
                Issue.record("wrong approver must be refused")
            } catch {
                // expected: wrongApprover
            }
        }()

        try await volta.approvals.decide(request.id, as: Self.human, approved: true)
        _ = try await volta.approvals.mintAuthority(
            for: request.id, on: volta.platform.policy
        )

        // 4. The agent can now export — and the broker records evidence.
        let result = try await volta.platform.broker.invoke(
            CapabilityID(name: "electronics.export", version: 1),
            input: Self.exportInput(volta: volta),
            as: Self.boardAgent
        )
        guard case .object(let fields)? = result.output,
              case .string(let path)? = fields["path"],
              case .string(let sha256)? = fields["sha256"]
        else {
            Issue.record("export result must carry path + sha256")
            return
        }
        #expect(FileManager.default.fileExists(atPath: path))
        let onDisk = try Data(contentsOf: URL(fileURLWithPath: path))
        #expect(
            SHA256Compat.hex(onDisk) == sha256,
            "artifact digest on disk must match the claimed sha256"
        )

        let live = await volta.platform.evidence.liveEvidence()
        #expect(live.contains { $0.kind == .artifact })
    }

    @Test func rejectedRequestMintsNothing() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())

        let request = await volta.approvals.requestExportAuthority(
            requester: Self.boardAgent,
            human: Self.human,
            projectName: "Smart Grid Breakout"
        )
        try await volta.approvals.decide(request.id, as: Self.human, approved: false)

        do {
            _ = try await volta.approvals.mintAuthority(
                for: request.id, on: volta.platform.policy
            )
            Issue.record("a rejected request must mint no authority")
        } catch {
            // expected: notApproved
        }

        // And the agent still cannot export.
        do {
            _ = try await volta.platform.broker.invoke(
                CapabilityID(name: "electronics.export", version: 1),
                input: Self.exportInput(volta: volta),
                as: Self.boardAgent
            )
            Issue.record("rejected agent must remain denied")
        } catch let violation as ContractViolation {
            #expect(violation.contract == .authority)
        }
    }
}

import CryptoKit

enum SHA256Compat {
    static func hex(_ data: Data) -> String {
        CryptoKit.SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
