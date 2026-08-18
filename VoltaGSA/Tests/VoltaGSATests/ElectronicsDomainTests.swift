import Testing
import Foundation
@testable import VoltaGSA
import GSACore
import GSAModeledWorld

// M2.3 foundation-wave evidence: electronics objects live in the Modeled
// World under GSA identities derived from Volta's existing KiCad-model IDs,
// mutations are governed, ungranted principals are denied, identity and
// content survive restarts, and the domain document round-trips.

@Suite struct ElectronicsDomainTests {
    static let founder = VoltaPrincipals.human("bret")
    static let stranger = VoltaPrincipals.human("nobody")

    static func makeStorage() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("VoltaGSA-\(UUID().uuidString)", isDirectory: true)
    }

    /// A board shaped like Volta's own fixtures (x64-smart-grid.kicad_sch):
    /// one project UUID, one schematic keyed by file name, two placed
    /// components with reference designators — exactly the fields
    /// `Project`, `SchematicIR`, and `SymbolInstance` carry.
    static func makeDocument(
        legacyID: String = "AAAAAAAA-BBBB-CCCC-DDDD-000000000001",
        name: String = "Smart Grid Breakout"
    ) -> ElectronicsDocument {
        ElectronicsDocument(
            legacyID: legacyID,
            name: name,
            projectDescription: "x64 smart grid test board",
            schematics: [
                SchematicDocument(
                    key: "x64-smart-grid.kicad_sch",
                    kicadVersion: "20250114",
                    sheetName: "Main",
                    components: [
                        ComponentDocument(
                            reference: "R1",
                            libId: "Device:R",
                            value: "10k",
                            fitted: true,
                            x: 25.4,
                            y: 127.0
                        ),
                        ComponentDocument(
                            reference: "C1",
                            libId: "Device:C",
                            value: "100nF",
                            fitted: true,
                            x: 50.8,
                            y: 76.2,
                            mirror: "x"
                        ),
                    ]
                ),
            ]
        )
    }

    @Test func stableIdentityIsDerivedFromVoltaIDs() {
        // Same legacy ID → same object identity, forever, deterministically.
        let first = ElectronicsSchema.stableObjectID(legacyID: "abc-123")
        let second = ElectronicsSchema.stableObjectID(legacyID: "abc-123")
        #expect(first == second)
        #expect(first != ElectronicsSchema.stableObjectID(legacyID: "abc-124"))

        // Distinct composite identities for the derived kinds.
        let project = ElectronicsSchema.stableObjectID(legacyID: "p1")
        let schematic = ElectronicsSchema.schematicID(projectLegacyID: "p1", schematicKey: "s.kicad_sch")
        let component = ElectronicsSchema.componentID(
            projectLegacyID: "p1", schematicKey: "s.kicad_sch", reference: "R1"
        )
        let footprint = ElectronicsSchema.footprintID(projectLegacyID: "p1", reference: "R1")
        #expect(Set([project, schematic, component, footprint]).count == 4)

        // The identity namespace is Volta's, not White Room's.
        #expect(
            ElectronicsSchema.stableObjectID(legacyID: "x")
                != MusicSchemaCompat.stableObjectID(legacyID: "x")
        )
    }

    @Test func importCreatesProjectSchematicsAndComponents() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        let projectID = try await volta.electronics.importDocument(
            Self.makeDocument(), as: Self.founder
        )

        let projects = await volta.electronics.projects()
        #expect(projects.count == 1)
        #expect(projects[0].objectID == projectID)
        #expect(projects[0].name == "Smart Grid Breakout")
        #expect(projects[0].schematicCount == 1)
        #expect(projects[0].componentCount == 2)
        #expect(projects[0].version == 1)

        let schematics = try await volta.electronics.schematics(projectID: projectID)
        #expect(schematics.count == 1)
        #expect(schematics[0].key == "x64-smart-grid.kicad_sch")
        #expect(schematics[0].kicadVersion == "20250114")
        #expect(schematics[0].componentCount == 2)

        let components = try await volta.electronics.components(projectID: projectID)
        #expect(components.count == 2)
        #expect(components.contains { $0.reference == "R1" && $0.value == "10k" })
        #expect(components.contains { $0.reference == "C1" && $0.mirror == "x" })

        // The identity is derived from the legacy ID, not minted fresh.
        #expect(
            projectID == ElectronicsSchema.stableObjectID(
                legacyID: "AAAAAAAA-BBBB-CCCC-DDDD-000000000001"
            )
        )
        #expect(
            components[0].objectID == ElectronicsSchema.componentID(
                projectLegacyID: "AAAAAAAA-BBBB-CCCC-DDDD-000000000001",
                schematicKey: "x64-smart-grid.kicad_sch",
                reference: components[0].reference
            )
        )
    }

    @Test func importIsIdempotent() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        let document = Self.makeDocument()
        _ = try await volta.electronics.importDocument(document, as: Self.founder)
        _ = try await volta.electronics.importDocument(document, as: Self.founder)
        _ = try await volta.electronics.importDocument(document, as: Self.founder)

        let projects = await volta.electronics.projects()
        #expect(projects.count == 1)
        // No new governed changes were written for identical state.
        #expect(projects[0].version == 1)
        let history = await volta.electronics.history(
            ElectronicsSchema.stableObjectID(
                legacyID: "AAAAAAAA-BBBB-CCCC-DDDD-000000000001"
            )
        )
        #expect(history.count == 1)
    }

    @Test func documentRoundTripsThroughTheModeledWorld() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        let document = Self.makeDocument()
        let projectID = try await volta.electronics.importDocument(document, as: Self.founder)

        let decoded = try await volta.electronics.document(projectID: projectID)
        #expect(decoded != nil)
        #expect(decoded == document)
        #expect(decoded?.name == "Smart Grid Breakout")
        #expect(decoded?.schematics.first?.components.first?.reference == "R1")
        #expect(decoded?.schematics.first?.components.last?.mirror == "x")

        // Content preservation: the recovered document re-encodes to exactly
        // the canonical payload of the original.
        let originalEncoded = try WorldValueCodec.encode(document)
        let decodedOnce = try WorldValueCodec.decode(ElectronicsDocument.self, from: originalEncoded)
        let decodedEncoded = try WorldValueCodec.encode(decodedOnce)
        #expect(decodedEncoded == originalEncoded)
    }

    @Test func componentChangesAreGoverned() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        _ = try await volta.electronics.importDocument(Self.makeDocument(), as: Self.founder)
        let componentID = ElectronicsSchema.componentID(
            projectLegacyID: "AAAAAAAA-BBBB-CCCC-DDDD-000000000001",
            schematicKey: "x64-smart-grid.kicad_sch",
            reference: "R1"
        )

        let updated = try await volta.electronics.setComponentAttributes(
            componentID,
            value: "4k7",
            fitted: false,
            as: Self.founder
        )
        #expect(updated.value == "4k7")
        #expect(updated.fitted == false)
        #expect(updated.libId == "Device:R")

        let reread = try await volta.electronics.component(componentID)
        #expect(reread == updated)

        let history = await volta.electronics.history(componentID)
        #expect(history.count == 2)
        #expect(history.last?.resultingVersion == 2)
        #expect(history.last?.change.intent.contains("component change on R1") == true)
    }

    @Test func ungrantedPrincipalIsDenied() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        // No founder authority issued: default-deny must refuse everything.

        do {
            _ = try await volta.electronics.importDocument(
                Self.makeDocument(), as: Self.stranger
            )
            Issue.record("import without any grant must be denied")
        } catch let violation as ContractViolation {
            #expect(violation.contract == .authority)
        }

        let projects = await volta.electronics.projects()
        #expect(projects.isEmpty)
    }

    @Test func deleteProjectTombstonesEverythingAndNeverReusesIdentity() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        let projectID = try await volta.electronics.importDocument(
            Self.makeDocument(), as: Self.founder
        )
        try await volta.electronics.deleteProject(projectID, as: Self.founder)

        let projects = await volta.electronics.projects()
        #expect(projects.isEmpty)

        // History survives the tombstone: create + delete.
        let history = await volta.electronics.history(projectID)
        #expect(history.count == 2)
        let schematicID = ElectronicsSchema.schematicID(
            projectLegacyID: "AAAAAAAA-BBBB-CCCC-DDDD-000000000001",
            schematicKey: "x64-smart-grid.kicad_sch"
        )
        #expect(await volta.electronics.history(schematicID).count == 2)
        let componentID = ElectronicsSchema.componentID(
            projectLegacyID: "AAAAAAAA-BBBB-CCCC-DDDD-000000000001",
            schematicKey: "x64-smart-grid.kicad_sch",
            reference: "R1"
        )
        #expect(await volta.electronics.history(componentID).count == 2)

        // Identities are never reused: re-import is refused, not resurrected.
        do {
            _ = try await volta.electronics.importDocument(
                Self.makeDocument(), as: Self.founder
            )
            Issue.record("re-import of a deleted project must be refused")
        } catch let error as ElectronicsWorldError {
            #expect(
                error == .deletedLegacyID("AAAAAAAA-BBBB-CCCC-DDDD-000000000001")
            )
        }
    }

    @Test func worldRecoversAcrossRebootWithIdentityIntact() async throws {
        let storage = Self.makeStorage()

        let first = try await VoltaPlatform.boot(storageDirectory: storage)
        await first.issueFounderAuthority(to: Self.founder)
        let projectID = try await first.electronics.importDocument(
            Self.makeDocument(), as: Self.founder
        )
        _ = try await first.electronics.setComponentAttributes(
            ElectronicsSchema.componentID(
                projectLegacyID: "AAAAAAAA-BBBB-CCCC-DDDD-000000000001",
                schematicKey: "x64-smart-grid.kicad_sch",
                reference: "R1"
            ),
            value: "4k7",
            as: Self.founder
        )

        // A fresh boot on the same storage must recover the governed world
        // from the change log — same objects, same versions, same history.
        let second = try await VoltaPlatform.boot(storageDirectory: storage)
        let projects = await second.electronics.projects()
        #expect(projects.count == 1)
        #expect(projects[0].objectID == projectID)
        #expect(projects[0].version == 1)

        let resistor = try await second.electronics.component(
            ElectronicsSchema.componentID(
                projectLegacyID: "AAAAAAAA-BBBB-CCCC-DDDD-000000000001",
                schematicKey: "x64-smart-grid.kicad_sch",
                reference: "R1"
            )
        )
        #expect(resistor.value == "4k7")

        // Recovered state is authoritative: re-import of unchanged state is
        // still a no-op after recovery.
        await second.issueFounderAuthority(to: Self.founder)
        _ = try await second.electronics.importDocument(
            Self.makeDocument(name: "Smart Grid Breakout"), as: Self.founder
        )

        let history = await second.electronics.history(projectID)
        #expect(history.count == 1)
    }
}

/// White Room's identity rule, inlined only to prove Volta's namespace
/// ("volta:") is distinct from White Room's ("white-room:") — two products
/// hashing the same legacy key must never collide in a shared world.
private enum MusicSchemaCompat {
    static func stableObjectID(legacyID: String) -> WorldObjectID {
        var digest = CryptoCompat.sha256(Data("white-room:\(legacyID)".utf8))
        digest[6] = (digest[6] & 0x0F) | 0x50
        digest[8] = (digest[8] & 0x3F) | 0x80
        let u = digest
        return WorldObjectID(value: UUID(uuid: uuid_t(
            u[0], u[1], u[2], u[3], u[4], u[5], u[6], u[7],
            u[8], u[9], u[10], u[11], u[12], u[13], u[14], u[15]
        )))
    }
}

import CryptoKit

private enum CryptoCompat {
    static func sha256(_ data: Data) -> [UInt8] {
        Array(CryptoKit.SHA256.hash(data: data).prefix(16))
    }
}
