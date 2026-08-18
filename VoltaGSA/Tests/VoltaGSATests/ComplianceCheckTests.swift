import Testing
import Foundation
@testable import VoltaGSA
import GSACore
import GSAModeledWorld
import GSAEvidence
import GSACapabilityKernel
import CryptoKit

// M2.4: external compliance/provider checks behind the broker. The check
// crosses the system boundary with design data — recorded as a canonical
// sha256-evidenced artifact, package digest-verified when present, and
// its authority arrives exclusively through a human approval flow.

@Suite(.serialized) struct ComplianceCheckTests {
    static let founder = VoltaPrincipals.human("bret")
    static let human = VoltaPrincipals.human("bret")
    static let boardAgent = VoltaPrincipals.boardAgent

    static let checkCapability = CapabilityID(name: "electronics.compliance.check", version: 1)

    static func makeStorage() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("VoltaGSA-\(UUID().uuidString)", isDirectory: true)
    }

    static func checkInput(volta: VoltaPlatform) -> WorldValue {
        .object([
            "projectName": .string("Smart Grid Breakout"),
            "provider": .string("jlcpcb"),
            "checkType": .string("fabrication-rules"),
            "outputDir": .string(volta.artifactRoot.path),
        ])
    }

    @Test func checkCapabilityIsRegisteredBehindTheBroker() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        let registered = await volta.platform.broker.registeredCapabilities()
        #expect(registered.contains(Self.checkCapability))
    }

    @Test func ungrantedCheckIsDenied() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        let evidenceBefore = await volta.platform.evidence.recordedCount
        await #expect(throws: Error.self) {
            _ = try await volta.platform.broker.invoke(
                Self.checkCapability,
                input: Self.checkInput(volta: volta),
                as: Self.boardAgent
            )
        }
        #expect(await volta.platform.evidence.recordedCount == evidenceBefore)
    }

    @Test func approvedCheckAuthorityLetsAgentCheckWithEvidence() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        let request = await volta.approvals.requestComplianceCheckAuthority(
            requester: Self.boardAgent,
            human: Self.human,
            projectName: "Smart Grid Breakout",
            provider: "jlcpcb",
            checkType: "fabrication-rules"
        )
        #expect(request.grantsScope.capabilities == ["electronics.compliance.check"])
        try await volta.approvals.decide(request.id, as: Self.human, approved: true)
        _ = try await volta.approvals.mintAuthority(
            for: request.id, on: volta.platform.policy
        )

        let result = try await volta.platform.broker.invoke(
            Self.checkCapability,
            input: Self.checkInput(volta: volta),
            as: Self.boardAgent
        )
        guard case .object(let fields)? = result.output,
              case .string(let path)? = fields["path"],
              case .string(let sha256)? = fields["sha256"],
              case .string(let provider)? = fields["provider"],
              case .string(let checkType)? = fields["checkType"]
        else {
            Issue.record("check result must carry path + sha256 + provider + checkType")
            return
        }
        #expect(provider == "jlcpcb")
        #expect(checkType == "fabrication-rules")
        #expect(FileManager.default.fileExists(atPath: path))

        let onDisk = try Data(contentsOf: URL(fileURLWithPath: path))
        #expect(Self.hex(onDisk) == sha256, "record digest on disk must match the claim")

        let record = try JSONSerialization.jsonObject(with: onDisk) as? [String: Any]
        #expect(record?["checkType"] as? String == "fabrication-rules")

        let live = await volta.platform.evidence.liveEvidence()
        #expect(live.contains {
            $0.kind == .artifact && $0.producer.rawValue == "capability:electronics.compliance.check"
        })
    }

    @Test func checkWithPackageVerifiesDigest() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        // Export a package (founder) to reference from the check.
        let exported = try await volta.platform.broker.invoke(
            CapabilityID(name: "electronics.export", version: 1),
            input: .object([
                "projectName": .string("Smart Grid Breakout"),
                "project": .object([
                    "legacyID": .string("AAAAAAAA-BBBB-CCCC-DDDD-000000000001"),
                    "name": .string("Smart Grid Breakout"),
                    "componentCount": .int(2),
                ]),
                "outputDir": .string(volta.artifactRoot.path),
            ]),
            as: Self.founder
        )
        guard case .object(let exportFields)? = exported.output,
              case .string(let exportPath)? = exportFields["path"],
              case .string(let exportSha)? = exportFields["sha256"]
        else {
            Issue.record("export result must carry path + sha256")
            return
        }

        // Tampered digest must refuse — boundary crossing with a package
        // the capability cannot verify byte-for-byte.
        let input: WorldValue = .object([
            "projectName": .string("Smart Grid Breakout"),
            "provider": .string("jlcpcb"),
            "checkType": .string("fabrication-rules"),
            "package": .object([
                "path": .string(exportPath),
                "sha256": .string(String(repeating: "0", count: 64)),
            ]),
            "outputDir": .string(volta.artifactRoot.path),
        ])
        await #expect(throws: Error.self) {
            _ = try await volta.platform.broker.invoke(
                Self.checkCapability, input: input, as: Self.founder
            )
        }
    }

    static func hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
