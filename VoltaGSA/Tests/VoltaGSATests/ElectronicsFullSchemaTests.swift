import Testing
import Foundation
@testable import VoltaGSA
import GSACore
import GSAModeledWorld

// M2.3 completion evidence: the eight remaining governed kinds (net, bus,
// sheet, symbol, pcb, footprint, bom, assembly) live in the Modeled World
// under GSA identities derived from Volta's existing KiCad-model IDs, their
// mutations are governed, their parent-child tombstone cascades hold,
// ungranted principals are denied, and identity and content survive
// restarts.

@Suite struct ElectronicsFullSchemaTests {
    static let founder = VoltaPrincipals.human("bret")
    static let stranger = VoltaPrincipals.human("nobody")

    static let legacyID = "AAAAAAAA-BBBB-CCCC-DDDD-000000000002"

    static func makeStorage() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("VoltaGSA-\(UUID().uuidString)", isDirectory: true)
    }

    /// A board shaped like Volta's own fixtures and parsers: one project
    /// UUID, one schematic keyed by file name with lib_symbols (Device:R /
    /// Device:C with ERC-relevant pins), two placed components, three nets
    /// from TopologyBuilder's naming, one bus, one PCBBoard with footprints
    /// / tracks / vias / net classes, a BOMLineItem aggregation, and one
    /// JLCPCB assembly run — exactly the fields `SchematicIR`,
    /// `TopologyBuilder`, `PCBParser`, `BOMView`, and `JlcpcbApiProvider`
    /// carry.
    static func makeFullDocument() -> ElectronicsDocument {
        ElectronicsDocument(
            legacyID: Self.legacyID,
            name: "Smart Grid Breakout II",
            projectDescription: "x64 smart grid test board, full governed schema",
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
                            x: 25.4,
                            y: 127.0
                        ),
                        ComponentDocument(
                            reference: "C1",
                            libId: "Device:C",
                            value: "100nF",
                            x: 50.8,
                            y: 76.2,
                            mirror: "x"
                        ),
                    ],
                    libSymbols: [
                        SymbolDocument(libId: "Device:R", pins: [
                            SymbolPinDocument(number: "1", name: "~", electricalType: "passive"),
                            SymbolPinDocument(number: "2", name: "~", electricalType: "passive"),
                        ]),
                        SymbolDocument(libId: "Device:C", pins: [
                            SymbolPinDocument(number: "1", name: "~", electricalType: "passive"),
                            SymbolPinDocument(number: "2", name: "~", electricalType: "passive"),
                        ]),
                    ]
                ),
            ],
            nets: [
                NetDocument(name: "GND", netNumber: 1, netClass: "Power", pins: ["R1.1", "C1.2"]),
                NetDocument(name: "+3V3", netNumber: 2, netClass: "Power", pins: ["R1.2"]),
                NetDocument(name: "/SDA", netNumber: 3, pins: ["C1.1"]),
            ],
            buses: [
                BusDocument(name: "I2C", memberNetNames: ["/SDA", "/SCL"]),
            ],
            pcb: PCBDocument(
                version: "20250114",
                layers: ["F.Cu", "B.Cu", "F.SilkS", "B.SilkS", "Edge.Cuts"],
                footprints: [
                    FootprintDocument(
                        reference: "R1",
                        libId: "Device:R-0603",
                        layer: "F.Cu",
                        x: 25.4,
                        y: 127.0,
                        rotation: 90,
                        pads: [
                            PadDocument(number: "1", type: "smd", shape: "rect", netName: "GND"),
                            PadDocument(number: "2", type: "smd", shape: "rect", netName: "+3V3"),
                        ]
                    ),
                    FootprintDocument(
                        reference: "C1",
                        libId: "Device:C-0603",
                        layer: "F.Cu",
                        x: 50.8,
                        y: 76.2,
                        pads: [
                            PadDocument(number: "1", type: "smd", shape: "rect", netName: "/SDA"),
                            PadDocument(number: "2", type: "smd", shape: "rect", netName: "GND"),
                        ]
                    ),
                ],
                tracks: [
                    TrackDocument(
                        startX: 25.4, startY: 127.0, endX: 26.4, endY: 127.0,
                        width: 0.25, layer: "F.Cu", netName: "GND"
                    ),
                    TrackDocument(
                        startX: 50.8, startY: 76.2, endX: 51.8, endY: 76.2,
                        width: 0.2, layer: "F.Cu", netName: "/SDA"
                    ),
                ],
                vias: [
                    ViaDocument(x: 30.0, y: 130.0, size: 0.6, drill: 0.3, layers: "F.Cu-B.Cu", netName: "GND"),
                ],
                netClasses: [
                    NetClassDocument(name: "Default", trackWidth: 0.25, clearance: 0.127, viaDiameter: 0.6, viaDrill: 0.3),
                    NetClassDocument(name: "Power", trackWidth: 0.5, clearance: 0.2, viaDiameter: 0.8, viaDrill: 0.4, nets: ["GND", "+3V3"]),
                ]
            ),
            bom: BOMDocument(lineItems: [
                BOMLineItemDocument(reference: "R1", value: "10k", quantity: 1),
                BOMLineItemDocument(
                    reference: "C1", value: "100nF", quantity: 2,
                    lcscPartNumber: "C1525", assemblyType: "basic"
                ),
            ]),
            assemblies: [
                AssemblyDocument(
                    key: "jlcpcb-20260817",
                    provider: "jlcpcb",
                    lines: [
                        AssemblyLineDocument(reference: "C1", lcscPartNumber: "C1525", assemblyType: "basic", inStock: true),
                    ],
                    assemblyFee: 0,
                    deliveryTime: "48h"
                ),
            ]
        )
    }

    @Test func everyKindHasDeterministicDistinctIdentity() {
        let project = ElectronicsSchema.stableObjectID(legacyID: Self.legacyID)
        let schematic = ElectronicsSchema.schematicID(projectLegacyID: Self.legacyID, schematicKey: "s.kicad_sch")
        let sheet = ElectronicsSchema.sheetID(projectLegacyID: Self.legacyID, schematicKey: "s.kicad_sch", sheetName: "Main")
        let symbol = ElectronicsSchema.symbolID(projectLegacyID: Self.legacyID, libID: "Device:R")
        let component = ElectronicsSchema.componentID(projectLegacyID: Self.legacyID, schematicKey: "s.kicad_sch", reference: "R1")
        let net = ElectronicsSchema.netID(projectLegacyID: Self.legacyID, netName: "GND")
        let bus = ElectronicsSchema.busID(projectLegacyID: Self.legacyID, busName: "I2C")
        let pcb = ElectronicsSchema.pcbID(projectLegacyID: Self.legacyID)
        let footprint = ElectronicsSchema.footprintID(projectLegacyID: Self.legacyID, reference: "R1")
        let bom = ElectronicsSchema.bomID(projectLegacyID: Self.legacyID)
        let assembly = ElectronicsSchema.assemblyID(projectLegacyID: Self.legacyID, assemblyKey: "run-1")

        let all = [project, schematic, sheet, symbol, component, net, bus, pcb, footprint, bom, assembly]
        #expect(Set(all).count == all.count, "every kind's identity namespace is distinct")

        // Deterministic: same keys → same identity, forever.
        #expect(net == ElectronicsSchema.netID(projectLegacyID: Self.legacyID, netName: "GND"))
        #expect(sheet == ElectronicsSchema.sheetID(projectLegacyID: Self.legacyID, schematicKey: "s.kicad_sch", sheetName: "Main"))
        #expect(assembly == ElectronicsSchema.assemblyID(projectLegacyID: Self.legacyID, assemblyKey: "run-1"))
        // Distinct keys → distinct identities.
        #expect(net != ElectronicsSchema.netID(projectLegacyID: Self.legacyID, netName: "+3V3"))
        #expect(assembly != ElectronicsSchema.assemblyID(projectLegacyID: Self.legacyID, assemblyKey: "run-2"))
    }

    @Test func importCreatesAllGovernedKinds() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        let projectID = try await volta.electronics.importDocument(
            Self.makeFullDocument(), as: Self.founder
        )

        let sheets = try await volta.electronics.sheets(schematicID: ElectronicsSchema.schematicID(
            projectLegacyID: Self.legacyID, schematicKey: "x64-smart-grid.kicad_sch"
        ))
        #expect(sheets.count == 1)
        #expect(sheets[0].sheetName == "Main")
        #expect(sheets[0].componentReferences == ["R1", "C1"])

        let symbols = try await volta.electronics.symbols(projectID: projectID)
        #expect(symbols.map(\.libId) == ["Device:C", "Device:R"])
        #expect(symbols.last?.pins.first?.electricalType == "passive")

        let nets = try await volta.electronics.nets(projectID: projectID)
        #expect(nets.count == 3)
        let gnd = nets.first { $0.name == "GND" }
        #expect(gnd?.netNumber == 1)
        #expect(gnd?.netClass == "Power")
        #expect(gnd?.pins == ["R1.1", "C1.2"])
        #expect(
            gnd?.objectID == ElectronicsSchema.netID(projectLegacyID: Self.legacyID, netName: "GND")
        )

        let buses = try await volta.electronics.buses(projectID: projectID)
        #expect(buses.count == 1)
        #expect(buses[0].memberNetNames == ["/SDA", "/SCL"])

        let board = try await volta.electronics.pcb(projectID: projectID)
        #expect(board?.version == "20250114")
        #expect(board?.layers.count == 5)
        #expect(board?.footprintReferences == ["R1", "C1"])
        #expect(board?.tracks.count == 2)
        #expect(board?.viaCount == 1)
        let powerClass = board?.netClasses.first { $0.name == "Power" }
        #expect(powerClass?.trackWidth == 0.5)
        #expect(powerClass?.nets == ["GND", "+3V3"])
        #expect(board?.objectID == ElectronicsSchema.pcbID(projectLegacyID: Self.legacyID))

        let footprints = try await volta.electronics.footprints(projectID: projectID)
        #expect(footprints.count == 2)
        let r1 = footprints.first { $0.reference == "R1" }
        #expect(r1?.layer == "F.Cu")
        #expect(r1?.rotation == 90)
        #expect(r1?.padCount == 2)
        #expect(r1?.padNetNames == ["GND", "+3V3"])

        let bom = try await volta.electronics.bom(projectID: projectID)
        #expect(bom?.lineItems.count == 2)
        #expect(bom?.lineItems.last?.lcscPartNumber == "C1525")
        #expect(bom?.objectID == ElectronicsSchema.bomID(projectLegacyID: Self.legacyID))

        let assemblies = try await volta.electronics.assemblies(projectID: projectID)
        #expect(assemblies.count == 1)
        #expect(assemblies[0].provider == "jlcpcb")
        #expect(assemblies[0].deliveryTime == "48h")
        #expect(assemblies[0].isReady == true)
    }

    @Test func fullImportIsIdempotent() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        let document = Self.makeFullDocument()
        _ = try await volta.electronics.importDocument(document, as: Self.founder)
        _ = try await volta.electronics.importDocument(document, as: Self.founder)
        _ = try await volta.electronics.importDocument(document, as: Self.founder)

        let projects = await volta.electronics.projects()
        #expect(projects.count == 1)
        #expect(projects[0].version == 1)

        // No new governed changes for identical state, on every kind.
        let net = ElectronicsSchema.netID(projectLegacyID: Self.legacyID, netName: "GND")
        #expect(await volta.electronics.history(net).count == 1)
        let pcb = ElectronicsSchema.pcbID(projectLegacyID: Self.legacyID)
        #expect(await volta.electronics.history(pcb).count == 1)
        let bom = ElectronicsSchema.bomID(projectLegacyID: Self.legacyID)
        #expect(await volta.electronics.history(bom).count == 1)
        let sheet = ElectronicsSchema.sheetID(
            projectLegacyID: Self.legacyID, schematicKey: "x64-smart-grid.kicad_sch", sheetName: "Main"
        )
        #expect(await volta.electronics.history(sheet).count == 1)
    }

    @Test func netRenameAndReclassifyAreGoverned() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        _ = try await volta.electronics.importDocument(Self.makeFullDocument(), as: Self.founder)

        let gndID = ElectronicsSchema.netID(projectLegacyID: Self.legacyID, netName: "GND")
        let renamed = try await volta.electronics.renameNet(gndID, to: "AGND", as: Self.founder)
        #expect(renamed.name == "AGND")
        // Identity stays pinned to the legacy key the net was imported under.
        #expect(renamed.objectID == gndID)

        let reclassified = try await volta.electronics.reclassifyNet(gndID, to: "Default", as: Self.founder)
        #expect(reclassified.netClass == "Default")
        #expect(reclassified.name == "AGND")

        let history = await volta.electronics.history(gndID)
        #expect(history.count == 3)
        #expect(history.last?.resultingVersion == 3)
        #expect(history[1].change.intent.contains("rename net GND"))
        #expect(history[2].change.intent.contains("reclassify net AGND"))
    }

    @Test func pcbLayerAndTrackMutationsAreGoverned() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        _ = try await volta.electronics.importDocument(Self.makeFullDocument(), as: Self.founder)

        let pcbID = ElectronicsSchema.pcbID(projectLegacyID: Self.legacyID)

        // 2-layer copper → 4-layer copper: fabrication-consequential.
        let relayered = try await volta.electronics.setPCBLayers(
            pcbID,
            to: ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu", "F.SilkS", "B.SilkS", "Edge.Cuts"],
            as: Self.founder
        )
        #expect(relayered.layers.count == 7)
        #expect(relayered.layers.contains("In1.Cu"))

        let rerouted = try await volta.electronics.setTrackAttributes(
            pcbID,
            trackIndex: 1,
            layer: "B.Cu",
            width: 0.5,
            as: Self.founder
        )
        #expect(rerouted.tracks[1].layer == "B.Cu")
        #expect(rerouted.tracks[1].width == 0.5)
        #expect(rerouted.tracks[1].netName == "/SDA")
        #expect(rerouted.tracks[0].layer == "F.Cu", "untouched track is unchanged")
        // Untouched net-class geometry survives the governed edit.
        #expect(rerouted.netClasses.first { $0.name == "Power" }?.trackWidth == 0.5)
        #expect(rerouted.viaCount == 1)

        // Out-of-range track index is a domain error, not a silent write.
        do {
            _ = try await volta.electronics.setTrackAttributes(
                pcbID, trackIndex: 9, layer: "B.Cu", as: Self.founder
            )
            Issue.record("out-of-range track index must throw")
        } catch let error as ElectronicsWorldError {
            #expect(error == .trackIndexOutOfRange(9))
        }

        let history = await volta.electronics.history(pcbID)
        #expect(history.count == 3)
        #expect(history[1].change.intent.contains("pcb layer stack"))
        #expect(history[2].change.intent.contains("pcb track 1"))
    }

    @Test func bomLineItemEditsAreGoverned() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        _ = try await volta.electronics.importDocument(Self.makeFullDocument(), as: Self.founder)

        let bomID = ElectronicsSchema.bomID(projectLegacyID: Self.legacyID)
        let edited = try await volta.electronics.setBOMLineItem(
            bomID,
            reference: "C1",
            quantity: 3,
            fitted: false,
            as: Self.founder
        )
        let line = edited.lineItems.first { $0.reference == "C1" }
        #expect(line?.quantity == 3)
        #expect(line?.fitted == false)
        #expect(line?.lcscPartNumber == "C1525", "nil argument leaves sourcing untouched")

        // Unknown line item is a domain error.
        do {
            _ = try await volta.electronics.setBOMLineItem(
                bomID, reference: "X9", quantity: 1, as: Self.founder
            )
            Issue.record("unknown BOM line must throw")
        } catch let error as ElectronicsWorldError {
            #expect(error == .lineItemNotFound("X9"))
        }

        let history = await volta.electronics.history(bomID)
        #expect(history.count == 2)
        #expect(history.last?.change.intent.contains("bom line C1") == true)
    }

    @Test func sheetSymbolBusFootprintAndAssemblyMutationsAreGoverned() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        _ = try await volta.electronics.importDocument(Self.makeFullDocument(), as: Self.founder)

        // Sheet rename (identity pinned to the legacy key).
        let sheetID = ElectronicsSchema.sheetID(
            projectLegacyID: Self.legacyID, schematicKey: "x64-smart-grid.kicad_sch", sheetName: "Main"
        )
        let renamedSheet = try await volta.electronics.renameSheet(sheetID, to: "Root", as: Self.founder)
        #expect(renamedSheet.sheetName == "Root")
        #expect(renamedSheet.objectID == sheetID)

        // Symbol pin electrical type — the field ERC outcomes key on.
        let symbolID = ElectronicsSchema.symbolID(projectLegacyID: Self.legacyID, libID: "Device:R")
        let retyped = try await volta.electronics.setSymbolPinElectricalType(
            symbolID, pin: "1", to: "power_out", as: Self.founder
        )
        #expect(retyped.pins.first?.electricalType == "power_out")
        #expect(retyped.pins.last?.electricalType == "passive")
        do {
            _ = try await volta.electronics.setSymbolPinElectricalType(
                symbolID, pin: "9", to: "passive", as: Self.founder
            )
            Issue.record("unknown pin must throw")
        } catch let error as ElectronicsWorldError {
            #expect(error == .pinNotFound("9"))
        }

        // Bus rename.
        let busID = ElectronicsSchema.busID(projectLegacyID: Self.legacyID, busName: "I2C")
        let renamedBus = try await volta.electronics.renameBus(busID, to: "I2C_BUS", as: Self.founder)
        #expect(renamedBus.name == "I2C_BUS")
        #expect(renamedBus.memberNetNames == ["/SDA", "/SCL"])

        // Footprint flip to back copper — fabrication-consequential.
        let footprintID = ElectronicsSchema.footprintID(projectLegacyID: Self.legacyID, reference: "R1")
        let moved = try await volta.electronics.setFootprintPlacement(
            footprintID, layer: "B.Cu", rotation: 270, as: Self.founder
        )
        #expect(moved.layer == "B.Cu")
        #expect(moved.rotation == 270)
        #expect(moved.padNetNames == ["GND", "+3V3"])

        // Assembly part substitution.
        let assemblyID = ElectronicsSchema.assemblyID(
            projectLegacyID: Self.legacyID, assemblyKey: "jlcpcb-20260817"
        )
        let reassigned = try await volta.electronics.setAssemblyLineAssignment(
            assemblyID, reference: "C1", lcscPartNumber: "C14663", as: Self.founder
        )
        #expect(reassigned.lines.first?.lcscPartNumber == "C14663")
        #expect(reassigned.isReady == true)

        for id in [sheetID, symbolID, busID, footprintID, assemblyID] {
            #expect(await volta.electronics.history(id).count == 2)
        }
    }

    @Test func cascadeSchematicDeleteRemovesSheetsAndComponentsButNotSymbols() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        let projectID = try await volta.electronics.importDocument(
            Self.makeFullDocument(), as: Self.founder
        )

        let schematicID = ElectronicsSchema.schematicID(
            projectLegacyID: Self.legacyID, schematicKey: "x64-smart-grid.kicad_sch"
        )
        try await volta.electronics.deleteSchematic(schematicID, as: Self.founder)

        #expect(try await volta.electronics.schematics(projectID: projectID).isEmpty)
        #expect(try await volta.electronics.components(projectID: projectID).isEmpty)
        // Reading sheets THROUGH the deleted schematic refuses (notFound),
        // never returns stale children.
        do {
            _ = try await volta.electronics.sheets(schematicID: schematicID)
            Issue.record("sheets of a deleted schematic must refuse")
        } catch let error as ElectronicsWorldError {
            #expect(error == .schematicNotFound(schematicID))
        }

        // Symbols are project-scoped library entries: they survive a
        // schematic deletion. So do nets (board-level topology).
        #expect(try await !volta.electronics.symbols(projectID: projectID).isEmpty)
        #expect(try await !volta.electronics.nets(projectID: projectID).isEmpty)

        // History survives every tombstone: create + delete.
        #expect(await volta.electronics.history(schematicID).count == 2)
        let sheetID = ElectronicsSchema.sheetID(
            projectLegacyID: Self.legacyID, schematicKey: "x64-smart-grid.kicad_sch", sheetName: "Main"
        )
        #expect(await volta.electronics.history(sheetID).count == 2)
        let componentID = ElectronicsSchema.componentID(
            projectLegacyID: Self.legacyID, schematicKey: "x64-smart-grid.kicad_sch", reference: "R1"
        )
        #expect(await volta.electronics.history(componentID).count == 2)

        // The deleted schematic's identity is never reused.
        do {
            _ = try await volta.electronics.importDocument(
                Self.makeFullDocument(), as: Self.founder
            )
            Issue.record("re-import over a deleted schematic must be refused")
        } catch let error as ElectronicsWorldError {
            #expect(error == .deletedLegacyID("\(Self.legacyID)/schematic/x64-smart-grid.kicad_sch"))
        }
    }

    @Test func cascadeSheetDeleteRemovesOnlyThatSheetsComponents() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)

        var document = Self.makeFullDocument()
        document.schematics.append(SchematicDocument(
            key: "psu.kicad_sch",
            kicadVersion: "20250114",
            sheetName: "PSU",
            components: [
                ComponentDocument(reference: "U1", libId: "Regulator:LM1117", value: "3.3V"),
            ]
        ))
        let projectID = try await volta.electronics.importDocument(document, as: Self.founder)

        let mainSheetID = ElectronicsSchema.sheetID(
            projectLegacyID: Self.legacyID, schematicKey: "x64-smart-grid.kicad_sch", sheetName: "Main"
        )
        try await volta.electronics.deleteSheet(mainSheetID, as: Self.founder)

        let remaining = try await volta.electronics.components(projectID: projectID)
        #expect(remaining.map(\.reference) == ["U1"], "only the deleted sheet's components cascade")

        let psuSheetID = ElectronicsSchema.sheetID(
            projectLegacyID: Self.legacyID, schematicKey: "psu.kicad_sch", sheetName: "PSU"
        )
        #expect(try await !volta.electronics.sheets(schematicID: ElectronicsSchema.schematicID(
            projectLegacyID: Self.legacyID, schematicKey: "psu.kicad_sch"
        )).isEmpty)
        #expect(await volta.electronics.history(psuSheetID).count == 1)
    }

    @Test func cascadePCBDeleteRemovesFootprints() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        let projectID = try await volta.electronics.importDocument(
            Self.makeFullDocument(), as: Self.founder
        )

        let pcbID = ElectronicsSchema.pcbID(projectLegacyID: Self.legacyID)
        try await volta.electronics.deletePCB(pcbID, as: Self.founder)

        #expect(try await volta.electronics.pcb(projectID: projectID) == nil)
        #expect(try await volta.electronics.footprints(projectID: projectID).isEmpty)
        // Nets survive: they are board-level topology, not copper.
        #expect(try await !volta.electronics.nets(projectID: projectID).isEmpty)

        #expect(await volta.electronics.history(pcbID).count == 2)
        let footprintID = ElectronicsSchema.footprintID(projectLegacyID: Self.legacyID, reference: "R1")
        #expect(await volta.electronics.history(footprintID).count == 2)
    }

    @Test func cascadeBOMDeleteRemovesAssemblies() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        let projectID = try await volta.electronics.importDocument(
            Self.makeFullDocument(), as: Self.founder
        )

        let bomID = ElectronicsSchema.bomID(projectLegacyID: Self.legacyID)
        try await volta.electronics.deleteBOM(bomID, as: Self.founder)

        #expect(try await volta.electronics.bom(projectID: projectID) == nil)
        #expect(try await volta.electronics.assemblies(projectID: projectID).isEmpty)

        #expect(await volta.electronics.history(bomID).count == 2)
        let assemblyID = ElectronicsSchema.assemblyID(
            projectLegacyID: Self.legacyID, assemblyKey: "jlcpcb-20260817"
        )
        #expect(await volta.electronics.history(assemblyID).count == 2)
    }

    @Test func projectDeleteCascadesEveryKind() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        let projectID = try await volta.electronics.importDocument(
            Self.makeFullDocument(), as: Self.founder
        )

        try await volta.electronics.deleteProject(projectID, as: Self.founder)

        #expect(await volta.electronics.projects().isEmpty)
        // Listing kinds THROUGH the deleted project refuses (notFound),
        // never returns stale children.
        do {
            _ = try await volta.electronics.symbols(projectID: projectID)
            _ = try await volta.electronics.nets(projectID: projectID)
            _ = try await volta.electronics.buses(projectID: projectID)
            _ = try await volta.electronics.pcb(projectID: projectID)
            _ = try await volta.electronics.footprints(projectID: projectID)
            _ = try await volta.electronics.bom(projectID: projectID)
            _ = try await volta.electronics.assemblies(projectID: projectID)
            Issue.record("projections through a deleted project must refuse")
        } catch let error as ElectronicsWorldError {
            #expect(error == .projectNotFound(projectID))
        }

        // Tombstones everywhere; history survives for audit.
        let netID = ElectronicsSchema.netID(projectLegacyID: Self.legacyID, netName: "GND")
        #expect(await volta.electronics.history(netID).count == 2)
        let symbolID = ElectronicsSchema.symbolID(projectLegacyID: Self.legacyID, libID: "Device:R")
        #expect(await volta.electronics.history(symbolID).count == 2)
        let busID = ElectronicsSchema.busID(projectLegacyID: Self.legacyID, busName: "I2C")
        #expect(await volta.electronics.history(busID).count == 2)

        // Identity never reused: re-import refused, not resurrected.
        do {
            _ = try await volta.electronics.importDocument(
                Self.makeFullDocument(), as: Self.founder
            )
            Issue.record("re-import of a deleted project must be refused")
        } catch let error as ElectronicsWorldError {
            #expect(error == .deletedLegacyID(Self.legacyID))
        }
    }

    @Test func ungrantedPrincipalIsDeniedOnNewKinds() async throws {
        let volta = try await VoltaPlatform.boot(storageDirectory: Self.makeStorage())
        await volta.issueFounderAuthority(to: Self.founder)
        _ = try await volta.electronics.importDocument(Self.makeFullDocument(), as: Self.founder)

        // A principal with no grant cannot mutate any of the new kinds.
        let netID = ElectronicsSchema.netID(projectLegacyID: Self.legacyID, netName: "GND")
        do {
            _ = try await volta.electronics.renameNet(netID, to: "AGND", as: Self.stranger)
            Issue.record("ungranted net rename must be denied")
        } catch let violation as ContractViolation {
            #expect(violation.contract == .authority)
        }

        let pcbID = ElectronicsSchema.pcbID(projectLegacyID: Self.legacyID)
        do {
            _ = try await volta.electronics.setTrackAttributes(
                pcbID, trackIndex: 0, layer: "B.Cu", as: Self.stranger
            )
            Issue.record("ungranted track mutation must be denied")
        } catch let violation as ContractViolation {
            #expect(violation.contract == .authority)
        }

        let bomID = ElectronicsSchema.bomID(projectLegacyID: Self.legacyID)
        do {
            _ = try await volta.electronics.setBOMLineItem(
                bomID, reference: "R1", quantity: 5, as: Self.stranger
            )
            Issue.record("ungranted BOM edit must be denied")
        } catch let violation as ContractViolation {
            #expect(violation.contract == .authority)
        }

        // Nothing changed: the world is exactly as imported.
        #expect(try await volta.electronics.net(netID).name == "GND")
        #expect(try await volta.electronics.pcbObject(pcbID).tracks[0].layer == "F.Cu")
        #expect(await volta.electronics.history(netID).count == 1)
    }

    @Test func worldRecoversAcrossRebootWithEveryKindIntact() async throws {
        let storage = Self.makeStorage()

        let first = try await VoltaPlatform.boot(storageDirectory: storage)
        await first.issueFounderAuthority(to: Self.founder)
        let projectID = try await first.electronics.importDocument(
            Self.makeFullDocument(), as: Self.founder
        )
        // Land governed mutations of the new kinds before the restart.
        _ = try await first.electronics.renameNet(
            ElectronicsSchema.netID(projectLegacyID: Self.legacyID, netName: "GND"),
            to: "AGND",
            as: Self.founder
        )
        _ = try await first.electronics.setTrackAttributes(
            ElectronicsSchema.pcbID(projectLegacyID: Self.legacyID),
            trackIndex: 0,
            width: 0.4,
            as: Self.founder
        )
        _ = try await first.electronics.setBOMLineItem(
            ElectronicsSchema.bomID(projectLegacyID: Self.legacyID),
            reference: "R1",
            quantity: 4,
            as: Self.founder
        )

        // A fresh boot on the same storage recovers the governed world —
        // every kind, same identities, same versions, same mutations.
        let second = try await VoltaPlatform.boot(storageDirectory: storage)
        let projects = await second.electronics.projects()
        #expect(projects.count == 1)
        #expect(projects[0].objectID == projectID)
        #expect(projects[0].version == 1)

        let net = try await second.electronics.net(
            ElectronicsSchema.netID(projectLegacyID: Self.legacyID, netName: "GND")
        )
        #expect(net.name == "AGND")

        let board = try await second.electronics.pcb(projectID: projectID)
        #expect(board?.tracks[0].width == 0.4)
        #expect(board?.tracks[1].width == 0.2)

        let bom = try await second.electronics.bom(projectID: projectID)
        #expect(bom?.lineItems.first { $0.reference == "R1" }?.quantity == 4)

        #expect(try await !second.electronics.symbols(projectID: projectID).isEmpty)
        #expect(try await !second.electronics.assemblies(projectID: projectID).isEmpty)

        // Recovered state is authoritative: re-import of unchanged state is
        // still a no-op after recovery (the in-world mutations block the
        // document diff, so only genuinely-new content would land).
        await second.issueFounderAuthority(to: Self.founder)
        let symbolID = ElectronicsSchema.symbolID(projectLegacyID: Self.legacyID, libID: "Device:R")
        let historyCount = await second.electronics.history(symbolID).count
        _ = try await second.electronics.importDocument(Self.makeFullDocument(), as: Self.founder)
        #expect(
            await second.electronics.history(symbolID).count == historyCount,
            "unchanged symbols must not gain changes on re-import"
        )
    }
}
