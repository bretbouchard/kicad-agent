import Testing
import Foundation
@testable import VoltaGSA
import GSACore
import GSAModeledWorld
import GSAEvidence
import GSACapabilityKernel

// M2.4-seed evidence: the manufacturing quote request — the first
// consequential external operation of the Phase 2 plan — executes only
// through the broker, quotes a digest-VERIFIED export package, writes its
// provider-facing request as sha256 evidence inside the sandbox, and its
// authority arrives exclusively through a human approval flow.

@Suite(.serialized) struct ManufacturingQuoteTests {
    static let founder = VoltaPrincipals.human("bret")
    static let human = VoltaPrincipals.human("bret")
    static let boardAgent = VoltaPrincipals.boardAgent

    static let quoteCapability = CapabilityID(name: "electronics.manufacturing.quote", version: 1)

    static func makeStorage() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("VoltaGSA-\(UUID().uuidString)", isDirectory: true)
    }

    /// Exports as the founder (the release-artifact step), then returns the
    /// quote input pinning that artifact by path + sha256.
    static func quoteInput(volta: VoltaPlatform, gerberSha256: String? = nil) async throws -> WorldValue {
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
        guard case .object(let fields)? = exported.output,
              case .string(let path)? = fields["path"],
              case .string(let sha256)? = fields["sha256"]
        else {
            throw CapabilityInputError.missingField("export result must carry path + sha256")
        }
        return .object([
            "projectName": .string("Smart Grid Breakout"),
            "provider": .string("jlcpcb"),
            "quantity": .int(10),
            "boardSpec": .object([
                "layers": .int(2),
                "widthMm": .double(50.8),
                "heightMm": .double(101.6),
            ]),
            "gerberPackage": .object([
                "path": .string(path),
                "sha256": .string(gerberSha256 ?? sha256),
            ]),
            "outputDir": .string(volta.artifactRoot.path),
        ])
    }

    @Test func quoteCapabilityIsRegisteredBehindTheBroker() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        let registered = await volta.platform.broker.registeredCapabilities()
        #expect(registered.contains(Self.quoteCapability))
    }

    @Test func ungrantedQuoteRequestIsDenied() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        let input = try await Self.quoteInput(volta: volta)

        // The export artifact from the helper exists; the quote must not add
        // anything when the caller has no grant.
        let before = try FileManager.default.contentsOfDirectory(
            at: volta.artifactRoot, includingPropertiesForKeys: nil
        ).count
        let evidenceBefore = await volta.platform.evidence.recordedCount

        do {
            _ = try await volta.platform.broker.invoke(
                Self.quoteCapability, input: input, as: Self.boardAgent
            )
            Issue.record("board agent must not request quotes without granted authority")
        } catch let violation as ContractViolation {
            #expect(violation.contract == .authority)
            #expect(violation.summary.contains("electronics.manufacturing.quote"))
        }

        let after = try FileManager.default.contentsOfDirectory(
            at: volta.artifactRoot, includingPropertiesForKeys: nil
        ).count
        #expect(after == before, "no quote package was written")
        #expect(await volta.platform.evidence.recordedCount == evidenceBefore)
    }

    @Test func quoteRequiresDigestVerifiedPackage() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        // Wrong digest: the package on disk does not match the claim.
        let tampered = try await Self.quoteInput(volta: volta, gerberSha256: String(repeating: "0", count: 64))
        do {
            _ = try await volta.platform.broker.invoke(Self.quoteCapability, input: tampered, as: Self.founder)
            Issue.record("a digest-mismatched package must be refused")
        } catch let error as CapabilityInputError {
            guard case .notPermitted = error else {
                Issue.record("expected notPermitted, got \(error)")
                return
            }
        }

        // Package outside the allowed roots: refused before any write.
        var escaped = try await Self.quoteInput(volta: volta)
        if case .object(var fields) = escaped,
           case .object(var package)? = fields["gerberPackage"] {
            package["path"] = .string("/etc/passwd")
            fields["gerberPackage"] = .object(package)
            escaped = .object(fields)
        }
        do {
            _ = try await volta.platform.broker.invoke(Self.quoteCapability, input: escaped, as: Self.founder)
            Issue.record("a package outside the sandbox must be refused")
        } catch let error as CapabilityInputError {
            guard case .outsideSandbox = error else {
                Issue.record("expected outsideSandbox, got \(error)")
                return
            }
        }
    }

    @Test func quoteOutputSandboxEscapeIsRefused() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        var input = try await Self.quoteInput(volta: volta)
        if case .object(var fields) = input {
            fields["outputDir"] = .string("/tmp")
            input = .object(fields)
        }
        do {
            _ = try await volta.platform.broker.invoke(Self.quoteCapability, input: input, as: Self.founder)
            Issue.record("writes outside the allowed roots must be refused")
        } catch let error as CapabilityInputError {
            guard case .outsideSandbox = error else {
                Issue.record("expected outsideSandbox, got \(error)")
                return
            }
        }
    }

    @Test func approvedQuoteAuthorityLetsAgentQuoteWithEvidence() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        let input = try await Self.quoteInput(volta: volta)

        // 1. The agent asks; 2. the human approves; 3. authority is minted.
        let request = await volta.approvals.requestManufacturingQuoteAuthority(
            requester: Self.boardAgent,
            human: Self.human,
            projectName: "Smart Grid Breakout",
            provider: "jlcpcb"
        )
        #expect(request.grantsScope.capabilities == ["electronics.manufacturing.quote"])
        try await volta.approvals.decide(request.id, as: Self.human, approved: true)
        _ = try await volta.approvals.mintAuthority(
            for: request.id, on: volta.platform.policy
        )

        // 4. The agent can now quote — the package is verified against its
        //    digest, the request lands as sha256-pinned artifact evidence.
        let result = try await volta.platform.broker.invoke(
            Self.quoteCapability, input: input, as: Self.boardAgent
        )
        guard case .object(let fields)? = result.output,
              case .string(let path)? = fields["path"],
              case .string(let sha256)? = fields["sha256"],
              case .string(let packageSha256)? = fields["packageSha256"]
        else {
            Issue.record("quote result must carry path + sha256 + packageSha256")
            return
        }
        #expect(FileManager.default.fileExists(atPath: path))

        let onDisk = try Data(contentsOf: URL(fileURLWithPath: path))
        #expect(Self.hex(onDisk) == sha256, "request digest on disk must match the claim")

        // The written package pins the export artifact it quotes.
        let manifest = try JSONSerialization.jsonObject(with: onDisk) as? [String: Any]
        let package = manifest?["gerberPackage"] as? [String: Any]
        #expect(package?["sha256"] as? String == packageSha256)

        let live = await volta.platform.evidence.liveEvidence()
        #expect(live.contains {
            $0.kind == .artifact && $0.producer.rawValue == "capability:electronics.manufacturing.quote"
        })
    }

    static func hex(_ data: Data) -> String {
        CryptoKit.SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

import CryptoKit
