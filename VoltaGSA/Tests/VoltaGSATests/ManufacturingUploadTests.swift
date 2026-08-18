import Testing
import Foundation
@testable import VoltaGSA
import GSACore
import GSAModeledWorld
import GSAEvidence
import GSACapabilityKernel
import CryptoKit

// M2.4: the manufacturer-upload path — "Gerber/BOM uploads" from the
// Phase 2 plan — executes only through the broker, transmits a digest-
// VERIFIED quote package, writes its fabricator-facing transmission
// record as sha256 evidence inside the sandbox, and its authority
// arrives exclusively through a human approval flow.

@Suite(.serialized) struct ManufacturingUploadTests {
    static let founder = VoltaPrincipals.human("bret")
    static let human = VoltaPrincipals.human("bret")
    static let boardAgent = VoltaPrincipals.boardAgent

    static let uploadCapability = CapabilityID(name: "electronics.manufacturing.upload", version: 1)

    static func makeStorage() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("VoltaGSA-\(UUID().uuidString)", isDirectory: true)
    }

    /// Exports (founder), quotes (founder), and returns the upload input
    /// pinning the QUOTE artifact by path + sha256 — the full lineage.
    static func uploadInput(volta: VoltaPlatform, quoteSha256: String? = nil) async throws -> WorldValue {
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
            as: founder
        )
        guard case .object(let exportFields)? = exported.output,
              case .string(let exportPath)? = exportFields["path"],
              case .string(let exportSha)? = exportFields["sha256"]
        else {
            throw CapabilityInputError.missingField("export result must carry path + sha256")
        }

        let quoted = try await volta.platform.broker.invoke(
            CapabilityID(name: "electronics.manufacturing.quote", version: 1),
            input: .object([
                "projectName": .string("Smart Grid Breakout"),
                "provider": .string("jlcpcb"),
                "quantity": .int(10),
                "boardSpec": .object([
                    "layers": .int(2),
                    "widthMm": .double(50.8),
                    "heightMm": .double(101.6),
                ]),
                "gerberPackage": .object([
                    "path": .string(exportPath),
                    "sha256": .string(exportSha),
                ]),
                "outputDir": .string(volta.artifactRoot.path),
            ]),
            as: founder
        )
        guard case .object(let quoteFields)? = quoted.output,
              case .string(let quotePath)? = quoteFields["path"],
              case .string(let quoteSha)? = quoteFields["sha256"]
        else {
            throw CapabilityInputError.missingField("quote result must carry path + sha256")
        }

        return .object([
            "projectName": .string("Smart Grid Breakout"),
            "provider": .string("jlcpcb"),
            "quotePackage": .object([
                "path": .string(quotePath),
                "sha256": .string(quoteSha256 ?? quoteSha),
            ]),
            "outputDir": .string(volta.artifactRoot.path),
        ])
    }

    @Test func uploadCapabilityIsRegisteredBehindTheBroker() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        let registered = await volta.platform.broker.registeredCapabilities()
        #expect(registered.contains(Self.uploadCapability))
    }

    @Test func ungrantedUploadIsDenied() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        let input = try await Self.uploadInput(volta: volta)

        let evidenceBefore = await volta.platform.evidence.recordedCount
        await #expect(throws: Error.self) {
            _ = try await volta.platform.broker.invoke(
                Self.uploadCapability, input: input, as: Self.boardAgent
            )
        }
        #expect(await volta.platform.evidence.recordedCount == evidenceBefore)
    }

    @Test func uploadRequiresDigestVerifiedQuotePackage() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        // Tampered digest: the upload must refuse to publish.
        let input = try await Self.uploadInput(
            volta: volta, quoteSha256: String(repeating: "0", count: 64)
        )
        await #expect(throws: Error.self) {
            _ = try await volta.platform.broker.invoke(
                Self.uploadCapability, input: input, as: Self.founder
            )
        }
    }

    @Test func approvedUploadAuthorityLetsAgentTransmitWithEvidenceAndLineage() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        let input = try await Self.uploadInput(volta: volta)

        // 1. The agent asks; 2. the human approves; 3. authority is minted.
        let request = await volta.approvals.requestManufacturingUploadAuthority(
            requester: Self.boardAgent,
            human: Self.human,
            projectName: "Smart Grid Breakout",
            provider: "jlcpcb"
        )
        #expect(request.grantsScope.capabilities == ["electronics.manufacturing.upload"])
        try await volta.approvals.decide(request.id, as: Self.human, approved: true)
        _ = try await volta.approvals.mintAuthority(
            for: request.id, on: volta.platform.policy
        )

        // 4. The agent can now transmit — the quote is verified against
        //    its digest, the transmission lands as sha256-pinned evidence.
        let result = try await volta.platform.broker.invoke(
            Self.uploadCapability, input: input, as: Self.boardAgent
        )
        guard case .object(let fields)? = result.output,
              case .string(let path)? = fields["path"],
              case .string(let sha256)? = fields["sha256"],
              case .string(let quoteSha256)? = fields["quoteSha256"]
        else {
            Issue.record("upload result must carry path + sha256 + quoteSha256")
            return
        }
        #expect(FileManager.default.fileExists(atPath: path))

        let onDisk = try Data(contentsOf: URL(fileURLWithPath: path))
        #expect(Self.hex(onDisk) == sha256, "transmission digest on disk must match the claim")

        // The written record pins the quote it transmitted (full lineage).
        let manifest = try JSONSerialization.jsonObject(with: onDisk) as? [String: Any]
        let quote = manifest?["quotePackage"] as? [String: Any]
        #expect(quote?["sha256"] as? String == quoteSha256)

        let live = await volta.platform.evidence.liveEvidence()
        #expect(live.contains {
            $0.kind == .artifact && $0.producer.rawValue == "capability:electronics.manufacturing.upload"
        })
    }

    static func hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
