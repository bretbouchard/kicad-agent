import Foundation
import Testing
import GSACore
import GSAModeledWorld
import GSAObdurate
import GSAEvidence
import GSAArtifacts
import GSACapabilityKernel
import GSAPlatform
@testable import VoltaGSA

@Suite("VO-TRUST-1/2: manufacturing DAIDs and signed handoff")
struct ManufacturingArtifactTests {

    private let bret = Principal(rawValue: "human:bret")
    private let michelle = Principal(rawValue: "system:michelle")

    private func makeSandbox() throws -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-trust-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    private func makeBroker(sandbox: URL) async -> (broker: ExecutionBroker, artifacts: ArtifactRegistry) {
        let policy = Obdurate()
        await policy.issue(
            AuthorityGrant(
                principal: michelle,
                scope: GrantScope(capabilities: ["electronics.export"]),
                grantedBy: bret
            )
        )
        let artifacts = ArtifactRegistry()
        let broker = ExecutionBroker(policy: policy, mintingInto: artifacts)
        await broker.register(ElectronicsExportCapability(allowedRoots: [sandbox]))
        return (broker, artifacts)
    }

    private func exportInput(
        sandbox: URL, board: WorldObjectID, change: ChangeID,
        parent: DAID? = nil
    ) -> WorldValue {
        var fields: [String: WorldValue] = [
            "projectName": .string("channel-strip"),
            "project": .object(["layers": .int(4), "revision": .string("C")]),
            "outputDir": .string(sandbox.path),
            "board": .string(board.value.uuidString),
            "change": .string(change.value.uuidString),
        ]
        if let parent { fields["parentDAID"] = .string(parent.rawValue) }
        return .object(fields)
    }

    @Test("Exports mint DAIDs referencing the board and governing change")
    func exportMintsDAID() async throws {
        let sandbox = try makeSandbox()
        defer { try? FileManager.default.removeItem(at: sandbox) }
        let (broker, artifacts) = await makeBroker(sandbox: sandbox)
        let board = WorldObjectID()
        let change = ChangeID()

        _ = try await broker.invoke(
            CapabilityID(name: "electronics.export", version: 1),
            input: exportInput(sandbox: sandbox, board: board, change: change),
            as: michelle
        )

        let manifest = await artifacts.latest()
        #expect(manifest != nil)
        #expect(manifest!.daid.rawValue.hasPrefix("daid:v1.0:"))
        #expect(manifest!.sourceObjects == [board])
        #expect(manifest!.governingChange == change)
        #expect(manifest!.reproducibility == .deterministic)

        // On-disk integrity: the manifest hash matches the written export.
        let onDisk = try FileManager.default.contentsOfDirectory(atPath: sandbox.path)
            .first { manifest!.hashes[$0] != nil }
        #expect(onDisk != nil)
        if let onDisk {
            let verification = await artifacts.verify(
                manifest!.daid,
                content: [onDisk: try Data(contentsOf: sandbox.appendingPathComponent(onDisk))]
            )
            #expect(verification.isValid)
        }
    }

    @Test("Re-exports chain through parent DAIDs")
    func reExportLineage() async throws {
        let sandbox = try makeSandbox()
        defer { try? FileManager.default.removeItem(at: sandbox) }
        let (broker, artifacts) = await makeBroker(sandbox: sandbox)
        let board = WorldObjectID()

        _ = try await broker.invoke(
            CapabilityID(name: "electronics.export", version: 1),
            input: exportInput(sandbox: sandbox, board: board, change: ChangeID()),
            as: michelle
        )
        let first = await artifacts.latest()

        _ = try await broker.invoke(
            CapabilityID(name: "electronics.export", version: 1),
            input: exportInput(sandbox: sandbox, board: board, change: ChangeID(), parent: first!.daid),
            as: michelle
        )
        let second = await artifacts.latest()

        let lineage = await artifacts.lineage(of: second!.daid)
        #expect(lineage.map(\.daid) == [second!.daid, first!.daid])
    }

    @Test("Signed manufacturing packages verify on the recipient side (TRUST-T005)")
    func signedHandoff() async throws {
        let sandbox = try makeSandbox()
        defer { try? FileManager.default.removeItem(at: sandbox) }
        let (broker, artifacts) = await makeBroker(sandbox: sandbox)
        let board = WorldObjectID()

        _ = try await broker.invoke(
            CapabilityID(name: "electronics.export", version: 1),
            input: exportInput(sandbox: sandbox, board: board, change: ChangeID()),
            as: michelle
        )
        let exportManifest = await artifacts.latest()

        // The fabricator package: gerbers, BOM, pick-and-place.
        let files: [String: Data] = [
            "top.gbr": Data("G04 gerber top*".utf8),
            "bottom.gbr": Data("G04 gerber bottom*".utf8),
            "bom.csv": Data("ref,part\nR1,10k\n".utf8),
            "pick-place.csv": Data("ref,x,y,rot\nR1,1.0,2.0,90\n".utf8),
        ]
        let key = try ArtifactSigningKey.generate(keyIdentifier: "key:volta-fab")
        let bundleDir = sandbox.appendingPathComponent("fab-package", isDirectory: true)

        let (packageDAID, _) = try await ManufacturingPackageBuilder.build(
            projectName: "channel-strip rev C",
            board: board,
            governingChange: ChangeID(),
            parentExport: exportManifest!.daid,
            files: files,
            registry: artifacts,
            signingKey: key,
            to: bundleDir
        )

        // The package chains back to the export that produced it.
        let lineage = await artifacts.lineage(of: packageDAID)
        #expect(lineage.map(\.daid) == [packageDAID, exportManifest!.daid])

        // The FAB verifies with the bundle + public key alone — no Volta
        // registry on their side.
        let received = try ArtifactBundle.read(from: bundleDir)
        var keyring = ArtifactKeyring()
        keyring.add(publicKey: key.publicKeyRaw, for: "key:volta-fab")
        let verdict = ArtifactVerifier.verify(
            manifest: received.manifest, content: received.content, keyring: keyring
        )
        #expect(verdict.isValid)

        // Tampering in transit is caught at the fab.
        var tampered = received.content
        tampered["bom.csv"] = Data("ref,part\nR1,1k\n".utf8)
        let tamperedVerdict = ArtifactVerifier.verify(
            manifest: received.manifest, content: tampered, keyring: keyring
        )
        #expect(!tamperedVerdict.isValid)
        #expect(tamperedVerdict.findings.contains { $0.contains("hash mismatch") })
    }
}

@Suite("Volta import recovery (volta-2ji)")
struct VoltaPersistenceTests {

    @Test("Governed boards, history, and evidence recover across reboots")
    func recoveryAcrossBoots() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("volta-persist-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let bret = Principal(rawValue: "human:bret")

        let first = try await Platform.boot(storageDirectory: dir)
        await first.policy.issue(
            AuthorityGrant(principal: bret, scope: .everything, grantedBy: bret)
        )
        let board = WorldObjectID()
        _ = try await first.runtime.transact([
            GovernedChange(
                target: board,
                operation: .create(
                    typeName: "volta.board",
                    initialState: .object(["name": .string("channel-strip"), "revision": .string("C")]
                    )
                ),
                authorizedBy: bret,
                intent: "board for fab"
            ),
        ])

        // Reboot: the board, its change history, and the narrative all
        // recover — Volta's import path can rebuild from this alone.
        let second = try await Platform.boot(storageDirectory: dir)
        let recovered = await second.runtime.snapshot().objects[board]
        let expectedState: WorldValue = .object([
            "name": .string("channel-strip"), "revision": .string("C"),
        ])
        #expect(recovered?.state == expectedState)
        let committed = await second.historian.events(category: .change)
        #expect(committed.contains { $0.title == "Transaction committed" })
    }
}
