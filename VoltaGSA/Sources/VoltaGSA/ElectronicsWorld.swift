import Foundation
import GSACore
import GSAModeledWorld
import GSAStewardshipRuntime

/// Failures of the electronics-domain layer itself. Refusals from the
/// platform (policy denials, contract violations) surface as
/// `ContractViolation` from `StewardshipRuntime.transact` and are rethrown
/// unchanged.
public enum ElectronicsWorldError: Error, Equatable {
    case projectNotFound(WorldObjectID)
    case schematicNotFound(WorldObjectID)
    case sheetNotFound(WorldObjectID)
    case symbolNotFound(WorldObjectID)
    case componentNotFound(WorldObjectID)
    case netNotFound(WorldObjectID)
    case busNotFound(WorldObjectID)
    case pcbNotFound(WorldObjectID)
    case footprintNotFound(WorldObjectID)
    case bomNotFound(WorldObjectID)
    case assemblyNotFound(WorldObjectID)
    /// A BOM line item (`reference`) or assembly line does not exist on the
    /// object being mutated.
    case lineItemNotFound(String)
    /// A pin (`number`) does not exist on the symbol being mutated.
    case pinNotFound(String)
    /// A track index does not address a segment of the PCB being mutated.
    case trackIndexOutOfRange(Int)
    /// Deleted identities are never reused (KERNEL-001/003); re-importing a
    /// deleted legacy object is refused rather than silently resurrected.
    case deletedLegacyID(String)
    case malformedState(String)
}

// MARK: - Domain documents (grounded in Volta's KiCad models)

/// A whole board project ready to enter the governed world. Field-by-field
/// this mirrors what Volta already has:
///
/// - `legacyID` ← the SwiftData `Project.id` UUID (`Models/Project.swift`),
///   the stable, never-user-visible key.
/// - `name`/`projectDescription` ← `Project.name`/`Project.projectDescription`.
/// - `schematics` ← the parsed `SchematicIR` documents
///   (`Parsing/SchematicParser.swift`, Phase 221) of the project's
///   `.kicad_sch` files.
/// - `nets` ← the union-find nets of `TopologyBuilder`
///   (`Parsing/TopologyBuilder.swift:120-146`) / `PCBNet`s
///   (`Parsing/PCBParser.swift:65-68`).
/// - `buses` ← KiCad bus aggregates of the schematic's label/wire graph
///   (`Parsing/SchematicParser.swift:23-31`).
/// - `pcb` ← the parsed `PCBBoard` (`Parsing/PCBParser.swift:16-27`).
/// - `bom` ← the `BOMLineItem` aggregation of `Views/BOM/BOMView.swift:24-29`.
/// - `assemblies` ← assembly-provider runs (`Providers/JLCPCB/
///   JlcpcbApiProvider.swift:107-139`).
///
/// The type is `Codable` so it round-trips losslessly through the Modeled
/// World (stored verbatim on the project object) and can be built directly
/// from Volta's parser output without any intermediate format.
public struct ElectronicsDocument: Codable, Sendable, Equatable {
    public let legacyID: String
    public var name: String
    public var projectDescription: String
    public var schematics: [SchematicDocument]
    public var nets: [NetDocument]
    public var buses: [BusDocument]
    /// The project's board (`PCBBoard`); nil until a `.kicad_pcb` is parsed.
    public var pcb: PCBDocument?
    public var bom: BOMDocument?
    public var assemblies: [AssemblyDocument]

    public init(
        legacyID: String,
        name: String,
        projectDescription: String = "",
        schematics: [SchematicDocument] = [],
        nets: [NetDocument] = [],
        buses: [BusDocument] = [],
        pcb: PCBDocument? = nil,
        bom: BOMDocument? = nil,
        assemblies: [AssemblyDocument] = []
    ) {
        self.legacyID = legacyID
        self.name = name
        self.projectDescription = projectDescription
        self.schematics = schematics
        self.nets = nets
        self.buses = buses
        self.pcb = pcb
        self.bom = bom
        self.assemblies = assemblies
    }
}

/// One parsed `.kicad_sch`, mirroring `SchematicIR`
/// (`Parsing/SchematicParser.swift:33-44`): the KiCad file version, the
/// placed symbol instances, and the `lib_symbols` entries. Wires, labels,
/// and no-connects stay in the raw file — the governed object carries what
/// has identity and consequence.
public struct SchematicDocument: Codable, Sendable, Equatable {
    /// Stable key inside the project: by convention the `.kicad_sch` file
    /// name (e.g. `"x64-smart-grid.kicad_sch"`).
    public let key: String
    /// The `(version …)` field of the KiCad file / `SchematicIR.version`.
    public let kicadVersion: String
    /// Sheet name for the flat single-sheet case (`"Main"`); hierarchical
    /// projects widen to one `SchematicDocument` per sheet.
    public let sheetName: String
    /// Placed symbol instances (`SchematicIR.symbols: [SymbolInstance]`,
    /// `Parsing/SchematicParser.swift:35`).
    public var components: [ComponentDocument]
    /// `lib_symbols` entries (`SchematicIR.libSymbols: [LibSymbol]`,
    /// `Parsing/SchematicParser.swift:36`), shared project-wide by `libId`.
    public var libSymbols: [SymbolDocument]

    public init(
        key: String,
        kicadVersion: String,
        sheetName: String = "Main",
        components: [ComponentDocument] = [],
        libSymbols: [SymbolDocument] = []
    ) {
        self.key = key
        self.kicadVersion = kicadVersion
        self.sheetName = sheetName
        self.components = components
        self.libSymbols = libSymbols
    }
}

/// One placed component, mirroring `SymbolInstance`
/// (`Parsing/SchematicParser.swift:46-51`): reference designator, library
/// id, position, mirror — plus the value field KiCad carries on symbol
/// properties and the fitted/DNP state Volta's BOM view
/// (`Views/BOM/BOMView.swift:24-29`) projects.
public struct ComponentDocument: Codable, Sendable, Equatable {
    /// Reference designator (`R1`, `C2`, `U3`) — unique per schematic.
    public let reference: String
    /// Library id (`Device:C`, `MCU_ST_STM32F1:...`) — `SymbolInstance.libId`.
    public var libId: String
    /// Component value (`10k`, `100nF`) from symbol properties.
    public var value: String
    /// Whether the component is fitted in this build variant (BOM view).
    public var fitted: Bool
    /// Placement (`SymbolInstance.position`).
    public var x: Double
    public var y: Double
    /// `SymbolInstance.mirror`.
    public var mirror: String?

    public init(
        reference: String,
        libId: String,
        value: String = "",
        fitted: Bool = true,
        x: Double = 0,
        y: Double = 0,
        mirror: String? = nil
    ) {
        self.reference = reference
        self.libId = libId
        self.value = value
        self.fitted = fitted
        self.x = x
        self.y = y
        self.mirror = mirror
    }
}

/// One `lib_symbols` entry, mirroring `LibSymbol`
/// (`Parsing/SchematicParser.swift:53-56`) with its `LibPin`s
/// (`Parsing/SchematicParser.swift:58-63`): number, name, and electrical
/// type — the fields ERC rules key on. Identity is project-scoped because
/// the `libId` namespace (`Device:R`, `MCU_ST_STM32F1:STM32F103C8Tx`) is
/// project-global in KiCad, which Volta's parser preserves verbatim.
public struct SymbolDocument: Codable, Sendable, Equatable {
    /// `LibSymbol.libId` (e.g. `"Device:R"`).
    public let libId: String
    /// `LibSymbol.pins: [LibPin]`.
    public var pins: [SymbolPinDocument]

    public init(libId: String, pins: [SymbolPinDocument] = []) {
        self.libId = libId
        self.pins = pins
    }
}

/// One library pin, mirroring `LibPin`
/// (`Parsing/SchematicParser.swift:58-63`).
public struct SymbolPinDocument: Codable, Sendable, Equatable {
    /// `LibPin.number` (`"1"`, `"A"`).
    public let number: String
    /// `LibPin.name` (`"~"`, `"VCC"`).
    public var name: String
    /// `LibPin.electricalType` (`"passive"`, `"power_in"`, ...) — the field
    /// ERC outcomes depend on.
    public var electricalType: String

    public init(number: String, name: String, electricalType: String) {
        self.number = number
        self.name = name
        self.electricalType = electricalType
    }
}

/// One electrical net, mirroring `PCBNet`
/// (`Parsing/PCBParser.swift:65-68`: `number`, `name`) and the pin→net
/// clusters `TopologyBuilder.resolvePinNets` produces
/// (`Parsing/TopologyBuilder.swift:120-146`: named-by-label nets like `GND`
/// or anonymous `Net_N` ones). Member pins use TopologyBuilder's
/// `"ref.pin"` key convention (`Parsing/TopologyBuilder.swift:61`).
public struct NetDocument: Codable, Sendable, Equatable {
    /// Net name (`GND`, `+3V3`, `/SDA`, `Net-1`) — `PCBNet.name`.
    public let name: String
    /// `PCBNet.number` — the ordinal KiCad assigns in the board file.
    public var netNumber: Int
    /// Net-class assignment (`PCBNetClass.name`,
    /// `Parsing/PCBParser.swift:70-77`; KiCad's default class is `"Default"`,
    /// `Parsing/PCBParser.swift:156`).
    public var netClass: String
    /// Connected pins as `"ref.pin"` keys (`TopologyBuilder.PinNets`).
    public var pins: [String]

    public init(
        name: String,
        netNumber: Int,
        netClass: String = "Default",
        pins: [String] = []
    ) {
        self.name = name
        self.netNumber = netNumber
        self.netClass = netClass
        self.pins = pins
    }
}

/// One bus aggregate: a named bundle of nets crossing the schematic
/// (KiCad `(bus ...)` geometry rides the same wire/label graph Volta's
/// `SchematicParser` parses — `Parsing/SchematicParser.swift:23-31` — and
/// members resolve to the same `TopologyBuilder` net names).
public struct BusDocument: Codable, Sendable, Equatable {
    /// Bus name (`I2C`, `SPI`).
    public let name: String
    /// The nets bundled by this bus, by net name.
    public var memberNetNames: [String]

    public init(name: String, memberNetNames: [String] = []) {
        self.name = name
        self.memberNetNames = memberNetNames
    }
}

/// One parsed `.kicad_pcb`, mirroring `PCBBoard`
/// (`Parsing/PCBParser.swift:16-27`): version, layer stack, footprints,
/// track segments, vias, and net classes. Pads stay nested on their
/// footprint (as in `PCBFootprint.pads`, `Parsing/PCBParser.swift:35`).
public struct PCBDocument: Codable, Sendable, Equatable {
    /// `PCBBoard.version`.
    public let version: String
    /// `PCBBoard.layers` (`F.Cu`, `B.Cu`, `F.SilkS`, `Edge.Cuts`, ...).
    public var layers: [String]
    /// `PCBBoard.footprints: [PCBFootprint]`.
    public var footprints: [FootprintDocument]
    /// `PCBBoard.segments: [PCBSegment]` — the copper tracks.
    public var tracks: [TrackDocument]
    /// `PCBBoard.vias: [PCBVia]`.
    public var vias: [ViaDocument]
    /// `PCBBoard.netClasses: [PCBNetClass]`.
    public var netClasses: [NetClassDocument]

    public init(
        version: String,
        layers: [String] = [],
        footprints: [FootprintDocument] = [],
        tracks: [TrackDocument] = [],
        vias: [ViaDocument] = [],
        netClasses: [NetClassDocument] = []
    ) {
        self.version = version
        self.layers = layers
        self.footprints = footprints
        self.tracks = tracks
        self.vias = vias
        self.netClasses = netClasses
    }
}

/// One placed footprint, mirroring `PCBFootprint`
/// (`Parsing/PCBParser.swift:29-36`): reference, library id, layer,
/// position, rotation, and pads.
public struct FootprintDocument: Codable, Sendable, Equatable {
    /// `PCBFootprint.reference` (from the `Reference` property).
    public let reference: String
    /// `PCBFootprint.libId` (`Device:R-0603`).
    public var libId: String
    /// `PCBFootprint.layer` (`F.Cu` / `B.Cu`).
    public var layer: String
    /// `PCBFootprint.position`.
    public var x: Double
    public var y: Double
    /// `PCBFootprint.rotation`.
    public var rotation: Double
    /// `PCBFootprint.pads: [PCBPad]`.
    public var pads: [PadDocument]

    public init(
        reference: String,
        libId: String,
        layer: String = "F.Cu",
        x: Double = 0,
        y: Double = 0,
        rotation: Double = 0,
        pads: [PadDocument] = []
    ) {
        self.reference = reference
        self.libId = libId
        self.layer = layer
        self.x = x
        self.y = y
        self.rotation = rotation
        self.pads = pads
    }
}

/// One pad of a footprint, mirroring `PCBPad`
/// (`Parsing/PCBParser.swift:38-47`).
public struct PadDocument: Codable, Sendable, Equatable {
    /// `PCBPad.number`.
    public let number: String
    /// `PCBPad.type` (`thru_hole`, `smd`, `np_thru_hole`, `connect`).
    public var type: String
    /// `PCBPad.shape` (`circle`, `rect`, `oval`).
    public var shape: String
    /// `PCBPad.netName` — the pad's net assignment.
    public var netName: String

    public init(number: String, type: String, shape: String, netName: String) {
        self.number = number
        self.type = type
        self.shape = shape
        self.netName = netName
    }
}

/// One copper track segment, mirroring `PCBSegment`
/// (`Parsing/PCBParser.swift:49-55`).
public struct TrackDocument: Codable, Sendable, Equatable {
    public var startX: Double
    public var startY: Double
    public var endX: Double
    public var endY: Double
    /// `PCBSegment.width`.
    public var width: Double
    /// `PCBSegment.layer`.
    public var layer: String
    /// `PCBSegment.netName`.
    public var netName: String

    public init(
        startX: Double,
        startY: Double,
        endX: Double,
        endY: Double,
        width: Double,
        layer: String,
        netName: String
    ) {
        self.startX = startX
        self.startY = startY
        self.endX = endX
        self.endY = endY
        self.width = width
        self.layer = layer
        self.netName = netName
    }
}

/// One via, mirroring `PCBVia` (`Parsing/PCBParser.swift:57-63`).
public struct ViaDocument: Codable, Sendable, Equatable {
    public var x: Double
    public var y: Double
    public var size: Double
    public var drill: Double
    public var layers: String
    public var netName: String

    public init(
        x: Double,
        y: Double,
        size: Double,
        drill: Double,
        layers: String,
        netName: String
    ) {
        self.x = x
        self.y = y
        self.size = size
        self.drill = drill
        self.layers = layers
        self.netName = netName
    }
}

/// One net class, mirroring `PCBNetClass`
/// (`Parsing/PCBParser.swift:70-77`).
public struct NetClassDocument: Codable, Sendable, Equatable {
    public var name: String
    public var trackWidth: Double
    public var clearance: Double
    public var viaDiameter: Double
    public var viaDrill: Double
    public var nets: [String]

    public init(
        name: String,
        trackWidth: Double,
        clearance: Double,
        viaDiameter: Double,
        viaDrill: Double,
        nets: [String] = []
    ) {
        self.name = name
        self.trackWidth = trackWidth
        self.clearance = clearance
        self.viaDiameter = viaDiameter
        self.viaDrill = viaDrill
        self.nets = nets
    }
}

/// A project's bill of materials: the governed aggregation of Volta's
/// `BOMLineItem`s (`Views/BOM/BOMView.swift:24-29`), which pair a
/// `UnifiedComponent` with a quantity and an `AssemblyAvailability`.
/// Line items are governed content of the BOM object (KiCad's BOM is one
/// artifact of the board, not per-line files).
public struct BOMDocument: Codable, Sendable, Equatable {
    public var lineItems: [BOMLineItemDocument]

    public init(lineItems: [BOMLineItemDocument] = []) {
        self.lineItems = lineItems
    }
}

/// One BOM line, mirroring `BOMLineItem`
/// (`Views/BOM/BOMView.swift:24-29`): the component (reference/value), the
/// quantity, the fitted/DNP state the BOM view projects, and the LCSC
/// sourcing part number `UnifiedComponent.lcscPartNumber` carries
/// (`Views/BOM/BOMView.swift:236`).
public struct BOMLineItemDocument: Codable, Sendable, Equatable {
    /// Reference designator of the placed component this line buys.
    public let reference: String
    /// Component value (`10k`, `100nF`).
    public var value: String
    /// `BOMLineItem.quantity`.
    public var quantity: Int
    /// Fitted in this build variant (do-not-populate when false).
    public var fitted: Bool
    /// LCSC part number for assembly sourcing, when assigned.
    public var lcscPartNumber: String?
    /// `AssemblyAvailability.assemblyType` (`"basic"`, `"extended"`,
    /// `"none"`, `"unknown"`) once checked.
    public var assemblyType: String

    public init(
        reference: String,
        value: String,
        quantity: Int,
        fitted: Bool = true,
        lcscPartNumber: String? = nil,
        assemblyType: String = "unknown"
    ) {
        self.reference = reference
        self.value = value
        self.quantity = quantity
        self.fitted = fitted
        self.lcscPartNumber = lcscPartNumber
        self.assemblyType = assemblyType
    }
}

/// One assembly-provider run, mirroring what
/// `JlcpcbApiProvider.checkAssemblyAvailability` returns per part
/// (`Providers/JLCPCB/JlcpcbApiProvider.swift:107-139`) as
/// `AssemblyAvailability` structs
/// (`Providers/JLCPCB/JlcpcbApiProvider.swift:266-282`): per-line basic/
/// extended/in-stock state, assembly fee, delivery time.
public struct AssemblyDocument: Codable, Sendable, Equatable {
    /// Stable key of this run inside the project (e.g. `"jlcpcb-20260817"`).
    public let key: String
    /// Provider the run targets (`"jlcpcb"`).
    public var provider: String
    /// Per-part availability results.
    public var lines: [AssemblyLineDocument]
    /// `AssemblyAvailability.assemblyFee`.
    public var assemblyFee: Double?
    /// `AssemblyAvailability.deliveryTime`.
    public var deliveryTime: String?

    public init(
        key: String,
        provider: String,
        lines: [AssemblyLineDocument] = [],
        assemblyFee: Double? = nil,
        deliveryTime: String? = nil
    ) {
        self.key = key
        self.provider = provider
        self.lines = lines
        self.assemblyFee = assemblyFee
        self.deliveryTime = deliveryTime
    }
}

/// One part's availability on an assembly run, mirroring
/// `AssemblyAvailability`
/// (`Providers/JLCPCB/JlcpcbApiProvider.swift:266-282`).
public struct AssemblyLineDocument: Codable, Sendable, Equatable {
    /// Reference designator of the placed component this line assembles.
    public let reference: String
    /// `AssemblyAvailability.lcscPartNumber`.
    public var lcscPartNumber: String
    /// `AssemblyAvailability.assemblyType` (`"basic"`, `"extended"`, ...).
    public var assemblyType: String
    /// `AssemblyAvailability.inStock`.
    public var inStock: Bool

    public init(
        reference: String,
        lcscPartNumber: String,
        assemblyType: String,
        inStock: Bool
    ) {
        self.reference = reference
        self.lcscPartNumber = lcscPartNumber
        self.assemblyType = assemblyType
        self.inStock = inStock
    }
}

// MARK: - Projections (Modeled World → domain)

/// A live board project as projected from the Modeled World.
public struct ProjectSummary: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let legacyID: String
    public let name: String
    public let schematicCount: Int
    public let componentCount: Int
    public let version: Int
}

/// One governed schematic of a project.
public struct SchematicRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let key: String
    public let kicadVersion: String
    public let sheetName: String
    public let componentCount: Int
}

/// One governed sheet of a schematic (the schematic's root sheet in the
/// flat case; one per `SchematicDocument`).
public struct SheetRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let schematicKey: String
    public let sheetName: String
    public let componentReferences: [String]
}

/// One governed symbol library entry.
public struct SymbolRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let libId: String
    public let pins: [SymbolPinDocument]
}

/// One governed component with placement and BOM-visible state.
public struct ComponentRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let schematicKey: String
    /// The sheet of the schematic this component is placed on.
    public let sheetName: String
    public let reference: String
    public let libId: String
    public let value: String
    public let fitted: Bool
    public let x: Double
    public let y: Double
    public let mirror: String?
}

/// One governed net.
public struct NetRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let name: String
    public let netNumber: Int
    public let netClass: String
    public let pins: [String]
}

/// One governed bus.
public struct BusRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let name: String
    public let memberNetNames: [String]
}

/// One governed PCB with its layer stack, tracks, vias, and net classes.
public struct PCBRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let version: String
    public let layers: [String]
    public let footprintReferences: [String]
    public let tracks: [TrackDocument]
    public let viaCount: Int
    public let netClasses: [NetClassDocument]
}

/// One governed footprint with placement and pad summary.
public struct FootprintRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let reference: String
    public let libId: String
    public let layer: String
    public let x: Double
    public let y: Double
    public let rotation: Double
    public let padCount: Int
    public let padNetNames: [String]
}

/// One governed BOM with its line items.
public struct BOMRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let lineItems: [BOMLineItemDocument]
}

/// One governed assembly run.
public struct AssemblyRecord: Sendable, Equatable {
    public let objectID: WorldObjectID
    public let projectLegacyID: String
    public let key: String
    public let provider: String
    public let lines: [AssemblyLineDocument]
    public let assemblyFee: Double?
    public let deliveryTime: String?
    /// `AssemblyAvailability.isAssemblyReady` over the run's lines: every
    /// line is basic/extended and in stock
    /// (`Providers/JLCPCB/JlcpcbApiProvider.swift:273-276`).
    public var isReady: Bool {
        !lines.isEmpty && lines.allSatisfy {
            ($0.assemblyType == "basic" || $0.assemblyType == "extended") && $0.inStock
        }
    }
}

// MARK: - The governed world facade

/// The electronics domain as governed world objects. Every mutation is a
/// `GovernedChange` applied through `StewardshipRuntime.transact` — there is
/// no other write path (KERNEL-002/003), and every read is a projection of
/// the canonical snapshot (KERNEL-001).
///
/// Completed M2.3 schema: project, schematic, sheet, symbol, component,
/// net, bus, pcb, footprint, bom, assembly (the verification-artifact kind
/// is written by the app-side `GSAPlatformHost` embedding and converges on
/// the same type name).
///
/// ## Tombstone-cascade edges (KERNEL-003)
///
/// Deleting a parent tombstones its live children in the same atomic
/// transaction; deleted identities are never reused:
///
/// - project → every object carrying its `projectLegacyID`
///   (schematics, sheets, symbols, components, nets, buses, the pcb,
///   footprints, the bom, assemblies)
/// - schematic → its sheets and components (by `schematicKey`)
/// - sheet → the components placed on it (by `schematicKey` + `sheetName`)
/// - pcb → its footprints
/// - bom → the project's assembly runs
///
/// Symbols deliberately cascade only from the project: their identity is
/// project-scoped (`libId` namespace is project-global in KiCad), so a
/// schematic deletion leaves the shared library entries live.
public struct ElectronicsWorld: Sendable {
    public let runtime: StewardshipRuntime

    public init(runtime: StewardshipRuntime) {
        self.runtime = runtime
    }

    // MARK: - Import (Volta models → Modeled World)

    /// Imports (or re-syncs) an `ElectronicsDocument` into the Modeled
    /// World. Every governed kind — project, schematics, sheets, symbols,
    /// components, nets, buses, the pcb, footprints, the bom, assemblies —
    /// is created or updated in ONE atomic transaction. Re-importing an
    /// unchanged document is a no-op (identity is derived from the legacy
    /// IDs, state equality is checked before writing), so migration is
    /// idempotent and safe to re-run — KiCad files stay authoritative until
    /// a governed equivalent replaces them (M2.3 preservation rule).
    ///
    /// Symbols are deduplicated project-wide by `libId`; the first
    /// schematic's pins win, deterministically in import order.
    @discardableResult
    public func importDocument(
        _ document: ElectronicsDocument,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> WorldObjectID {
        let projectID = ElectronicsSchema.stableObjectID(legacyID: document.legacyID)
        let snapshot = await runtime.snapshot()
        let historyNote = intent ?? "import volta project \(document.legacyID)"

        // The full plan: every object this import wants live, with its
        // deterministic identity and canonical desired state.
        struct Planned {
            let id: WorldObjectID
            let typeName: String
            let state: WorldValue
            let intent: String
            /// The composite legacy key, for tombstone-refusal labels.
            let legacyKey: String
        }

        var planned: [Planned] = []
        planned.append(Planned(
            id: projectID,
            typeName: ElectronicsSchema.projectType,
            state: try Self.projectState(for: document),
            intent: historyNote,
            legacyKey: document.legacyID
        ))

        var symbolsByLibID: [String: SymbolDocument] = [:]
        for schematic in document.schematics {
            let schematicID = ElectronicsSchema.schematicID(
                projectLegacyID: document.legacyID,
                schematicKey: schematic.key
            )
            planned.append(Planned(
                id: schematicID,
                typeName: ElectronicsSchema.schematicType,
                state: Self.schematicState(
                    projectLegacyID: document.legacyID,
                    schematic: schematic
                ),
                intent: "\(historyNote): schematic \(schematic.key)",
                legacyKey: "\(document.legacyID)/schematic/\(schematic.key)"
            ))

            let sheetID = ElectronicsSchema.sheetID(
                projectLegacyID: document.legacyID,
                schematicKey: schematic.key,
                sheetName: schematic.sheetName
            )
            planned.append(Planned(
                id: sheetID,
                typeName: ElectronicsSchema.sheetType,
                state: Self.sheetState(
                    projectLegacyID: document.legacyID,
                    schematicKey: schematic.key,
                    sheetName: schematic.sheetName,
                    componentReferences: schematic.components.map(\.reference)
                ),
                intent: "\(historyNote): sheet \(schematic.sheetName) of \(schematic.key)",
                legacyKey: "\(document.legacyID)/schematic/\(schematic.key)/sheet/\(schematic.sheetName)"
            ))

            for symbol in schematic.libSymbols where symbolsByLibID[symbol.libId] == nil {
                symbolsByLibID[symbol.libId] = symbol
            }

            for component in schematic.components {
                let componentID = ElectronicsSchema.componentID(
                    projectLegacyID: document.legacyID,
                    schematicKey: schematic.key,
                    reference: component.reference
                )
                planned.append(Planned(
                    id: componentID,
                    typeName: ElectronicsSchema.componentType,
                    state: Self.componentState(
                        projectLegacyID: document.legacyID,
                        schematicKey: schematic.key,
                        sheetName: schematic.sheetName,
                        component: component
                    ),
                    intent: "\(historyNote): component \(component.reference)",
                    legacyKey: "\(document.legacyID)/schematic/\(schematic.key)/component/\(component.reference)"
                ))
            }
        }

        for symbol in symbolsByLibID.values.sorted(by: { $0.libId < $1.libId }) {
            let symbolID = ElectronicsSchema.symbolID(
                projectLegacyID: document.legacyID,
                libID: symbol.libId
            )
            planned.append(Planned(
                id: symbolID,
                typeName: ElectronicsSchema.symbolType,
                state: Self.symbolState(projectLegacyID: document.legacyID, symbol: symbol),
                intent: "\(historyNote): symbol \(symbol.libId)",
                legacyKey: "\(document.legacyID)/symbol/\(symbol.libId)"
            ))
        }

        for net in document.nets {
            let netID = ElectronicsSchema.netID(
                projectLegacyID: document.legacyID,
                netName: net.name
            )
            planned.append(Planned(
                id: netID,
                typeName: ElectronicsSchema.netType,
                state: Self.netState(projectLegacyID: document.legacyID, net: net),
                intent: "\(historyNote): net \(net.name)",
                legacyKey: "\(document.legacyID)/net/\(net.name)"
            ))
        }

        for bus in document.buses {
            let busID = ElectronicsSchema.busID(
                projectLegacyID: document.legacyID,
                busName: bus.name
            )
            planned.append(Planned(
                id: busID,
                typeName: ElectronicsSchema.busType,
                state: Self.busState(projectLegacyID: document.legacyID, bus: bus),
                intent: "\(historyNote): bus \(bus.name)",
                legacyKey: "\(document.legacyID)/bus/\(bus.name)"
            ))
        }

        if let pcb = document.pcb {
            let pcbID = ElectronicsSchema.pcbID(projectLegacyID: document.legacyID)
            planned.append(Planned(
                id: pcbID,
                typeName: ElectronicsSchema.pcbType,
                state: Self.pcbState(projectLegacyID: document.legacyID, pcb: pcb),
                intent: "\(historyNote): pcb",
                legacyKey: "\(document.legacyID)/pcb"
            ))
            for footprint in pcb.footprints {
                let footprintID = ElectronicsSchema.footprintID(
                    projectLegacyID: document.legacyID,
                    reference: footprint.reference
                )
                planned.append(Planned(
                    id: footprintID,
                    typeName: ElectronicsSchema.footprintType,
                    state: Self.footprintState(
                        projectLegacyID: document.legacyID,
                        footprint: footprint
                    ),
                    intent: "\(historyNote): footprint \(footprint.reference)",
                    legacyKey: "\(document.legacyID)/footprint/\(footprint.reference)"
                ))
            }
        }

        if let bom = document.bom {
            let bomID = ElectronicsSchema.bomID(projectLegacyID: document.legacyID)
            planned.append(Planned(
                id: bomID,
                typeName: ElectronicsSchema.bomType,
                state: Self.bomState(projectLegacyID: document.legacyID, bom: bom),
                intent: "\(historyNote): bom",
                legacyKey: "\(document.legacyID)/bom"
            ))
        }

        for assembly in document.assemblies {
            let assemblyID = ElectronicsSchema.assemblyID(
                projectLegacyID: document.legacyID,
                assemblyKey: assembly.key
            )
            planned.append(Planned(
                id: assemblyID,
                typeName: ElectronicsSchema.assemblyType,
                state: Self.assemblyState(
                    projectLegacyID: document.legacyID,
                    assembly: assembly
                ),
                intent: "\(historyNote): assembly \(assembly.key)",
                legacyKey: "\(document.legacyID)/assembly/\(assembly.key)"
            ))
        }

        // Deleted identities are never reused: refuse the whole import if
        // ANY object it wants is tombstoned (KERNEL-001/003).
        for object in planned where snapshot.objects[object.id]?.status == .deleted {
            throw ElectronicsWorldError.deletedLegacyID(object.legacyKey)
        }

        // Idempotent diff against the live world: only real changes land.
        var changes: [GovernedChange] = []
        for object in planned {
            let existing = snapshot.objects[object.id]
            if existing == nil {
                changes.append(GovernedChange(
                    target: object.id,
                    operation: .create(
                        typeName: object.typeName,
                        initialState: object.state
                    ),
                    authorizedBy: principal,
                    intent: object.intent
                ))
            } else if existing?.state != object.state {
                changes.append(GovernedChange(
                    target: object.id,
                    operation: .mutate(newState: object.state),
                    authorizedBy: principal,
                    intent: object.intent
                ))
            }
        }

        if !changes.isEmpty {
            _ = try await runtime.transact(changes)
        }
        return projectID
    }

    // MARK: - Governed mutations

    /// Renames a project. Every landed rename is a tracked change.
    public func renameProject(
        _ projectID: WorldObjectID,
        to newName: String,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> ProjectSummary {
        let current = try await projectSummary(projectID)
        var document = try await document(projectID: projectID) ?? ElectronicsDocument(
            legacyID: current.legacyID,
            name: current.name
        )
        document.name = newName

        _ = try await runtime.transact([
            GovernedChange(
                target: projectID,
                operation: .mutate(newState: try Self.projectState(for: document)),
                authorizedBy: principal,
                intent: intent ?? "rename project \(current.name) → \(newName)"
            ),
        ])
        return try await projectSummary(projectID)
    }

    /// Updates one component's value/fitted state. `nil` arguments leave
    /// the current value untouched. Component state is governed, so every
    /// BOM-visible change (value swap, DNP toggle) is a tracked change.
    public func setComponentAttributes(
        _ componentID: WorldObjectID,
        value: String? = nil,
        fitted: Bool? = nil,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> ComponentRecord {
        let record = try await component(componentID)
        let updated = ComponentRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            schematicKey: record.schematicKey,
            sheetName: record.sheetName,
            reference: record.reference,
            libId: record.libId,
            value: value ?? record.value,
            fitted: fitted ?? record.fitted,
            x: record.x,
            y: record.y,
            mirror: record.mirror
        )

        _ = try await runtime.transact([
            GovernedChange(
                target: componentID,
                operation: .mutate(newState: Self.componentState(for: updated)),
                authorizedBy: principal,
                intent: intent
                    ?? "component change on \(record.reference) (value \(updated.value), fitted \(updated.fitted))"
            ),
        ])
        return updated
    }

    /// Renames a net (`GND` → `AGND`). Identity stays pinned to the legacy
    /// key the net was imported under — Volta's net names ARE identity keys
    /// (`TopologyBuilder` names nets from labels,
    /// `Parsing/TopologyBuilder.swift:135-143`), so a rename that reaches
    /// the KiCad files re-imports as a new object; this mutation records
    /// the in-world rename as a tracked change either way.
    public func renameNet(
        _ netID: WorldObjectID,
        to newName: String,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> NetRecord {
        let record = try await net(netID)
        return try await mutateNet(
            netID,
            record: record,
            name: newName,
            netClass: nil,
            as: principal,
            intent: intent ?? "rename net \(record.name) → \(newName)"
        )
    }

    /// Reclassifies a net into another net class (`Default` ↔ `Power`) —
    /// the governed form of KiCad net-class assignment
    /// (`PCBNetClass`, `Parsing/PCBParser.swift:70-77`). Track width and
    /// clearance follow the class, so this is fabrication-consequential.
    public func reclassifyNet(
        _ netID: WorldObjectID,
        to netClass: String,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> NetRecord {
        let record = try await net(netID)
        return try await mutateNet(
            netID,
            record: record,
            name: nil,
            netClass: netClass,
            as: principal,
            intent: intent ?? "reclassify net \(record.name) → class \(netClass)"
        )
    }

    private func mutateNet(
        _ netID: WorldObjectID,
        record: NetRecord,
        name: String?,
        netClass: String?,
        as principal: Principal,
        intent: String
    ) async throws -> NetRecord {
        let updated = NetRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            name: name ?? record.name,
            netNumber: record.netNumber,
            netClass: netClass ?? record.netClass,
            pins: record.pins
        )
        _ = try await runtime.transact([
            GovernedChange(
                target: netID,
                operation: .mutate(newState: Self.netState(for: updated)),
                authorizedBy: principal,
                intent: intent
            ),
        ])
        return updated
    }

    /// Renames a bus aggregate. Identity stays pinned to the legacy key the
    /// bus was imported under (same semantics as `renameNet`).
    public func renameBus(
        _ busID: WorldObjectID,
        to newName: String,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> BusRecord {
        let record = try await bus(busID)
        let updated = BusRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            name: newName,
            memberNetNames: record.memberNetNames
        )
        _ = try await runtime.transact([
            GovernedChange(
                target: busID,
                operation: .mutate(newState: Self.busState(for: updated)),
                authorizedBy: principal,
                intent: intent ?? "rename bus \(record.name) → \(newName)"
            ),
        ])
        return updated
    }

    /// Renames a sheet (KiCad's `(sheet_name ...)` property). Identity
    /// stays pinned to the legacy key the sheet was imported under.
    public func renameSheet(
        _ sheetID: WorldObjectID,
        to newSheetName: String,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> SheetRecord {
        let record = try await sheet(sheetID)
        let updated = SheetRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            schematicKey: record.schematicKey,
            sheetName: newSheetName,
            componentReferences: record.componentReferences
        )
        _ = try await runtime.transact([
            GovernedChange(
                target: sheetID,
                operation: .mutate(newState: Self.sheetState(for: updated)),
                authorizedBy: principal,
                intent: intent ?? "rename sheet \(record.sheetName) → \(newSheetName)"
            ),
        ])
        return updated
    }

    /// Sets a library pin's electrical type (`passive` ↔ `power_in`) — the
    /// field ERC rules key on (`LibPin.electricalType`,
    /// `Parsing/SchematicParser.swift:58-63`). Changing it changes ERC
    /// outcomes, so it is governed.
    public func setSymbolPinElectricalType(
        _ symbolID: WorldObjectID,
        pin number: String,
        to electricalType: String,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> SymbolRecord {
        let record = try await symbol(symbolID)
        guard let index = record.pins.firstIndex(where: { $0.number == number }) else {
            throw ElectronicsWorldError.pinNotFound(number)
        }
        var pins = record.pins
        pins[index] = SymbolPinDocument(
            number: pins[index].number,
            name: pins[index].name,
            electricalType: electricalType
        )
        let updated = SymbolRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            libId: record.libId,
            pins: pins
        )
        _ = try await runtime.transact([
            GovernedChange(
                target: symbolID,
                operation: .mutate(newState: Self.symbolState(for: updated)),
                authorizedBy: principal,
                intent: intent
                    ?? "symbol \(record.libId) pin \(number) electrical type → \(electricalType)"
            ),
        ])
        return updated
    }

    /// Replaces the PCB's layer stack — e.g. a 2-layer → 4-layer change
    /// (`PCBBoard.layers`, `Parsing/PCBParser.swift:24`). Fabrication-
    /// consequential: the stack drives board cost and manufacturing.
    public func setPCBLayers(
        _ pcbID: WorldObjectID,
        to layers: [String],
        as principal: Principal,
        intent: String? = nil
    ) async throws -> PCBRecord {
        let record = try await pcbObject(pcbID)
        let updated = PCBRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            version: record.version,
            layers: layers,
            footprintReferences: record.footprintReferences,
            tracks: record.tracks,
            viaCount: record.viaCount,
            netClasses: record.netClasses
        )
        _ = try await runtime.transact([
            GovernedChange(
                target: pcbID,
                operation: .mutate(newState: Self.pcbState(for: updated)),
                authorizedBy: principal,
                intent: intent ?? "pcb layer stack → \(layers.count) layers (\(layers.joined(separator: ", ")))"
            ),
        ])
        return updated
    }

    /// Mutates one copper track (re-layer, re-width) of the PCB's governed
    /// segment list (`PCBSegment.layer`/`PCBSegment.width`,
    /// `Parsing/PCBParser.swift:49-55`). Copper changes are the heart of
    /// board fabrication, so every track edit is a tracked change.
    public func setTrackAttributes(
        _ pcbID: WorldObjectID,
        trackIndex: Int,
        layer: String? = nil,
        width: Double? = nil,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> PCBRecord {
        let record = try await pcbObject(pcbID)
        guard record.tracks.indices.contains(trackIndex) else {
            throw ElectronicsWorldError.trackIndexOutOfRange(trackIndex)
        }
        var tracks = record.tracks
        tracks[trackIndex] = TrackDocument(
            startX: tracks[trackIndex].startX,
            startY: tracks[trackIndex].startY,
            endX: tracks[trackIndex].endX,
            endY: tracks[trackIndex].endY,
            width: width ?? tracks[trackIndex].width,
            layer: layer ?? tracks[trackIndex].layer,
            netName: tracks[trackIndex].netName
        )
        let updated = PCBRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            version: record.version,
            layers: record.layers,
            footprintReferences: record.footprintReferences,
            tracks: tracks,
            viaCount: record.viaCount,
            netClasses: record.netClasses
        )
        _ = try await runtime.transact([
            GovernedChange(
                target: pcbID,
                operation: .mutate(newState: Self.pcbState(for: updated)),
                authorizedBy: principal,
                intent: intent
                    ?? "pcb track \(trackIndex) change (layer \(tracks[trackIndex].layer), width \(tracks[trackIndex].width))"
            ),
        ])
        return updated
    }

    /// Moves a footprint (layer/position/rotation) — flipping a part to the
    /// back copper (`F.Cu` → `B.Cu`) is fabrication-consequential
    /// (`PCBFootprint`, `Parsing/PCBParser.swift:29-36`). `nil` arguments
    /// leave the current value untouched.
    public func setFootprintPlacement(
        _ footprintID: WorldObjectID,
        layer: String? = nil,
        x: Double? = nil,
        y: Double? = nil,
        rotation: Double? = nil,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> FootprintRecord {
        let record = try await footprint(footprintID)
        let updated = FootprintRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            reference: record.reference,
            libId: record.libId,
            layer: layer ?? record.layer,
            x: x ?? record.x,
            y: y ?? record.y,
            rotation: rotation ?? record.rotation,
            padCount: record.padCount,
            padNetNames: record.padNetNames
        )
        _ = try await runtime.transact([
            GovernedChange(
                target: footprintID,
                operation: .mutate(newState: Self.footprintState(for: updated)),
                authorizedBy: principal,
                intent: intent
                    ?? "footprint \(record.reference) placement change (layer \(updated.layer), rotation \(updated.rotation))"
            ),
        ])
        return updated
    }

    /// Edits one BOM line item (quantity, fitted/DNP, LCSC sourcing part) —
    /// the governed form of Volta's BOM-view edits (`BOMLineItem`,
    /// `Views/BOM/BOMView.swift:24-29`). `nil` arguments leave the current
    /// value untouched; the line item must exist.
    public func setBOMLineItem(
        _ bomID: WorldObjectID,
        reference: String,
        quantity: Int? = nil,
        fitted: Bool? = nil,
        lcscPartNumber: String? = nil,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> BOMRecord {
        let record = try await bomObject(bomID)
        guard let index = record.lineItems.firstIndex(where: { $0.reference == reference })
        else {
            throw ElectronicsWorldError.lineItemNotFound(reference)
        }
        var lineItems = record.lineItems
        lineItems[index] = BOMLineItemDocument(
            reference: lineItems[index].reference,
            value: lineItems[index].value,
            quantity: quantity ?? lineItems[index].quantity,
            fitted: fitted ?? lineItems[index].fitted,
            lcscPartNumber: lcscPartNumber ?? lineItems[index].lcscPartNumber,
            assemblyType: lineItems[index].assemblyType
        )
        let updated = BOMRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            lineItems: lineItems
        )
        _ = try await runtime.transact([
            GovernedChange(
                target: bomID,
                operation: .mutate(newState: Self.bomState(for: updated)),
                authorizedBy: principal,
                intent: intent
                    ?? "bom line \(reference) change (quantity \(lineItems[index].quantity), fitted \(lineItems[index].fitted))"
            ),
        ])
        return updated
    }

    /// Assigns a sourcing part to one line of an assembly run — the
    /// governed part-substitution flow, mirroring how
    /// `BOMLineItem.assemblyAvailability` attaches an LCSC part to a
    /// reference (`Views/BOM/BOMView.swift:52-54`,
    /// `Providers/JLCPCB/JlcpcbApiProvider.swift:132-138`).
    public func setAssemblyLineAssignment(
        _ assemblyID: WorldObjectID,
        reference: String,
        lcscPartNumber: String,
        as principal: Principal,
        intent: String? = nil
    ) async throws -> AssemblyRecord {
        let record = try await assembly(assemblyID)
        guard let index = record.lines.firstIndex(where: { $0.reference == reference })
        else {
            throw ElectronicsWorldError.lineItemNotFound(reference)
        }
        var lines = record.lines
        lines[index] = AssemblyLineDocument(
            reference: lines[index].reference,
            lcscPartNumber: lcscPartNumber,
            assemblyType: lines[index].assemblyType,
            inStock: lines[index].inStock
        )
        let updated = AssemblyRecord(
            objectID: record.objectID,
            projectLegacyID: record.projectLegacyID,
            key: record.key,
            provider: record.provider,
            lines: lines,
            assemblyFee: record.assemblyFee,
            deliveryTime: record.deliveryTime
        )
        _ = try await runtime.transact([
            GovernedChange(
                target: assemblyID,
                operation: .mutate(newState: Self.assemblyState(for: updated)),
                authorizedBy: principal,
                intent: intent
                    ?? "assembly \(record.key) line \(reference) sourcing → \(lcscPartNumber)"
            ),
        ])
        return updated
    }

    // MARK: - Governed deletes (tombstone cascades)

    /// Deletes a project and everything derived from it (schematics,
    /// sheets, symbols, components, nets, buses, the pcb, footprints, the
    /// bom, assemblies) as tombstones in one atomic transaction. Deleted
    /// identities are never reused — history stays complete (KERNEL-003).
    ///
    /// Destructive: the principal needs delete authority over the
    /// electronics types, which for non-founder principals arrives only
    /// through an approval flow
    /// (`ElectronicsApprovals.requestProjectDeletionAuthority`). The raw
    /// KiCad files are NOT touched — only the governed mirror.
    public func deleteProject(
        _ projectID: WorldObjectID,
        as principal: Principal,
        intent: String? = nil
    ) async throws {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()

        var changes = [GovernedChange(
            target: projectID,
            operation: .delete,
            authorizedBy: principal,
            intent: intent ?? "delete project \(summary.name) (\(summary.legacyID))"
        )]

        for object in snapshot.objects.values where object.status == .live {
            guard let derived = Self.derivedLegacyID(of: object, projectLegacyID: summary.legacyID)
            else { continue }
            changes.append(GovernedChange(
                target: object.id,
                operation: .delete,
                authorizedBy: principal,
                intent: "delete \(object.typeName) \(derived) of project \(summary.legacyID)"
            ))
        }

        _ = try await runtime.transact(changes)
    }

    /// Deletes a schematic and its live children — its sheets and its
    /// components — as tombstones in one atomic transaction. Symbols stay
    /// live: their `libId` namespace is project-global, so they cascade
    /// only from the project (see the type discussion above).
    public func deleteSchematic(
        _ schematicID: WorldObjectID,
        as principal: Principal,
        intent: String? = nil
    ) async throws {
        let record = try await schematic(schematicID)
        let snapshot = await runtime.snapshot()

        var changes = [GovernedChange(
            target: schematicID,
            operation: .delete,
            authorizedBy: principal,
            intent: intent ?? "delete schematic \(record.key) of project \(record.projectLegacyID)"
        )]

        for object in snapshot.objects.values where object.status == .live {
            let fields = Self.fields(of: object)
            guard Self.stringField(fields, "projectLegacyID") == record.projectLegacyID,
                  Self.stringField(fields, "schematicKey") == record.key,
                  object.id != schematicID
            else { continue }
            changes.append(GovernedChange(
                target: object.id,
                operation: .delete,
                authorizedBy: principal,
                intent: "delete \(object.typeName) of schematic \(record.key)"
            ))
        }

        _ = try await runtime.transact(changes)
    }

    /// Deletes a sheet and the components placed on it as tombstones in one
    /// atomic transaction.
    public func deleteSheet(
        _ sheetID: WorldObjectID,
        as principal: Principal,
        intent: String? = nil
    ) async throws {
        let record = try await sheet(sheetID)
        let snapshot = await runtime.snapshot()

        var changes = [GovernedChange(
            target: sheetID,
            operation: .delete,
            authorizedBy: principal,
            intent: intent
                ?? "delete sheet \(record.sheetName) of schematic \(record.schematicKey)"
        )]

        for object in snapshot.objects.values
        where object.status == .live && object.typeName == ElectronicsSchema.componentType {
            let fields = Self.fields(of: object)
            guard Self.stringField(fields, "projectLegacyID") == record.projectLegacyID,
                  Self.stringField(fields, "schematicKey") == record.schematicKey,
                  Self.stringField(fields, "sheetName") == record.sheetName
            else { continue }
            changes.append(GovernedChange(
                target: object.id,
                operation: .delete,
                authorizedBy: principal,
                intent: "delete component \(Self.stringField(fields, "reference") ?? "?") of sheet \(record.sheetName)"
            ))
        }

        _ = try await runtime.transact(changes)
    }

    /// Deletes the project's PCB and its footprints as tombstones in one
    /// atomic transaction.
    public func deletePCB(
        _ pcbID: WorldObjectID,
        as principal: Principal,
        intent: String? = nil
    ) async throws {
        let record = try await pcbObject(pcbID)
        let snapshot = await runtime.snapshot()

        var changes = [GovernedChange(
            target: pcbID,
            operation: .delete,
            authorizedBy: principal,
            intent: intent ?? "delete pcb of project \(record.projectLegacyID)"
        )]

        for object in snapshot.objects.values
        where object.status == .live && object.typeName == ElectronicsSchema.footprintType {
            let fields = Self.fields(of: object)
            guard Self.stringField(fields, "projectLegacyID") == record.projectLegacyID
            else { continue }
            changes.append(GovernedChange(
                target: object.id,
                operation: .delete,
                authorizedBy: principal,
                intent: "delete footprint \(Self.stringField(fields, "reference") ?? "?") of pcb"
            ))
        }

        _ = try await runtime.transact(changes)
    }

    /// Deletes the project's BOM and its assembly runs as tombstones in one
    /// atomic transaction (assembly availability is derived per BOM line,
    /// `Views/BOM/BOMView.swift:24-29`, so the runs follow the BOM down).
    public func deleteBOM(
        _ bomID: WorldObjectID,
        as principal: Principal,
        intent: String? = nil
    ) async throws {
        let record = try await bomObject(bomID)
        let snapshot = await runtime.snapshot()

        var changes = [GovernedChange(
            target: bomID,
            operation: .delete,
            authorizedBy: principal,
            intent: intent ?? "delete bom of project \(record.projectLegacyID)"
        )]

        for object in snapshot.objects.values
        where object.status == .live && object.typeName == ElectronicsSchema.assemblyType {
            let fields = Self.fields(of: object)
            guard Self.stringField(fields, "projectLegacyID") == record.projectLegacyID
            else { continue }
            changes.append(GovernedChange(
                target: object.id,
                operation: .delete,
                authorizedBy: principal,
                intent: "delete assembly \(Self.stringField(fields, "key") ?? "?") of bom"
            ))
        }

        _ = try await runtime.transact(changes)
    }

    // MARK: - Projections (Modeled World → domain)

    /// All live projects, ordered by legacy ID for stable presentation.
    public func projects() async -> [ProjectSummary] {
        let snapshot = await runtime.snapshot()
        return snapshot.objects.values
            .filter { $0.typeName == ElectronicsSchema.projectType && $0.status == .live }
            .compactMap { Self.summary(from: $0) }
            .sorted { $0.legacyID < $1.legacyID }
    }

    /// The `ElectronicsDocument` of a governed project, decoded back from
    /// the canonical state. Identity and content survive the round trip —
    /// this is what "no functionality loss" is checked against.
    public func document(projectID: WorldObjectID) async throws -> ElectronicsDocument? {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[projectID], object.status == .live else { return nil }
        guard case .object(let fields) = object.state,
              let documentValue = fields["document"]
        else {
            throw ElectronicsWorldError.malformedState(
                "project \(projectID) has no document payload"
            )
        }
        return try WorldValueCodec.decode(ElectronicsDocument.self, from: documentValue)
    }

    /// The governed schematics of a project.
    public func schematics(projectID: WorldObjectID) async throws -> [SchematicRecord] {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        return try Self.schematicKeys(in: snapshot, projectID: projectID)
            .map { key in
                ElectronicsSchema.schematicID(
                    projectLegacyID: summary.legacyID,
                    schematicKey: key
                )
            }
            .compactMap { id in
                guard let object = snapshot.objects[id], object.status == .live else {
                    return nil
                }
                return try Self.schematicRecord(from: object)
            }
            .sorted { $0.key < $1.key }
    }

    /// One governed schematic.
    public func schematic(_ schematicID: WorldObjectID) async throws -> SchematicRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[schematicID], object.status == .live else {
            throw ElectronicsWorldError.schematicNotFound(schematicID)
        }
        return try Self.schematicRecord(from: object)
    }

    /// The governed sheets of a schematic, ordered by sheet name.
    public func sheets(schematicID: WorldObjectID) async throws -> [SheetRecord] {
        let schematic = try await schematic(schematicID)
        let snapshot = await runtime.snapshot()
        return snapshot.objects.values
            .filter {
                $0.typeName == ElectronicsSchema.sheetType
                    && $0.status == .live
                    && Self.stringField(Self.fields(of: $0), "projectLegacyID") == schematic.projectLegacyID
                    && Self.stringField(Self.fields(of: $0), "schematicKey") == schematic.key
            }
            .compactMap { try? Self.sheetRecord(from: $0) }
            .sorted { $0.sheetName < $1.sheetName }
    }

    /// One governed sheet.
    public func sheet(_ sheetID: WorldObjectID) async throws -> SheetRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[sheetID], object.status == .live else {
            throw ElectronicsWorldError.sheetNotFound(sheetID)
        }
        return try Self.sheetRecord(from: object)
    }

    /// The governed symbol library of a project, ordered by libId.
    public func symbols(projectID: WorldObjectID) async throws -> [SymbolRecord] {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        return snapshot.objects.values
            .filter {
                $0.typeName == ElectronicsSchema.symbolType
                    && $0.status == .live
                    && Self.stringField(Self.fields(of: $0), "projectLegacyID") == summary.legacyID
            }
            .compactMap { try? Self.symbolRecord(from: $0) }
            .sorted { $0.libId < $1.libId }
    }

    /// One governed symbol.
    public func symbol(_ symbolID: WorldObjectID) async throws -> SymbolRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[symbolID], object.status == .live else {
            throw ElectronicsWorldError.symbolNotFound(symbolID)
        }
        return try Self.symbolRecord(from: object)
    }

    /// The governed components of a project, across all schematics.
    public func components(projectID: WorldObjectID) async throws -> [ComponentRecord] {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        return try snapshot.objects.values
            .filter {
                $0.typeName == ElectronicsSchema.componentType
                    && $0.status == .live
                    && Self.stringField(Self.fields(of: $0), "projectLegacyID") == summary.legacyID
            }
            .compactMap { try Self.componentRecord(from: $0) }
            .sorted { ($0.schematicKey, $0.reference) < ($1.schematicKey, $1.reference) }
    }

    /// One governed component.
    public func component(_ componentID: WorldObjectID) async throws -> ComponentRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[componentID], object.status == .live else {
            throw ElectronicsWorldError.componentNotFound(componentID)
        }
        return try Self.componentRecord(from: object)
    }

    /// The governed nets of a project, ordered by name.
    public func nets(projectID: WorldObjectID) async throws -> [NetRecord] {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        return snapshot.objects.values
            .filter {
                $0.typeName == ElectronicsSchema.netType
                    && $0.status == .live
                    && Self.stringField(Self.fields(of: $0), "projectLegacyID") == summary.legacyID
            }
            .compactMap { try? Self.netRecord(from: $0) }
            .sorted { $0.name < $1.name }
    }

    /// One governed net.
    public func net(_ netID: WorldObjectID) async throws -> NetRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[netID], object.status == .live else {
            throw ElectronicsWorldError.netNotFound(netID)
        }
        return try Self.netRecord(from: object)
    }

    /// The governed buses of a project, ordered by name.
    public func buses(projectID: WorldObjectID) async throws -> [BusRecord] {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        return snapshot.objects.values
            .filter {
                $0.typeName == ElectronicsSchema.busType
                    && $0.status == .live
                    && Self.stringField(Self.fields(of: $0), "projectLegacyID") == summary.legacyID
            }
            .compactMap { try? Self.busRecord(from: $0) }
            .sorted { $0.name < $1.name }
    }

    /// One governed bus.
    public func bus(_ busID: WorldObjectID) async throws -> BusRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[busID], object.status == .live else {
            throw ElectronicsWorldError.busNotFound(busID)
        }
        return try Self.busRecord(from: object)
    }

    /// The project's governed PCB, or nil when no board is imported.
    public func pcb(projectID: WorldObjectID) async throws -> PCBRecord? {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        let pcbID = ElectronicsSchema.pcbID(projectLegacyID: summary.legacyID)
        guard let object = snapshot.objects[pcbID], object.status == .live else { return nil }
        return try Self.pcbRecord(from: object)
    }

    /// One governed PCB, by object identity.
    public func pcbObject(_ pcbID: WorldObjectID) async throws -> PCBRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[pcbID], object.status == .live else {
            throw ElectronicsWorldError.pcbNotFound(pcbID)
        }
        return try Self.pcbRecord(from: object)
    }

    /// The governed footprints of a project, ordered by reference.
    public func footprints(projectID: WorldObjectID) async throws -> [FootprintRecord] {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        return snapshot.objects.values
            .filter {
                $0.typeName == ElectronicsSchema.footprintType
                    && $0.status == .live
                    && Self.stringField(Self.fields(of: $0), "projectLegacyID") == summary.legacyID
            }
            .compactMap { try? Self.footprintRecord(from: $0) }
            .sorted { $0.reference < $1.reference }
    }

    /// One governed footprint.
    public func footprint(_ footprintID: WorldObjectID) async throws -> FootprintRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[footprintID], object.status == .live else {
            throw ElectronicsWorldError.footprintNotFound(footprintID)
        }
        return try Self.footprintRecord(from: object)
    }

    /// The project's governed BOM, or nil when none is imported.
    public func bom(projectID: WorldObjectID) async throws -> BOMRecord? {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        let bomID = ElectronicsSchema.bomID(projectLegacyID: summary.legacyID)
        guard let object = snapshot.objects[bomID], object.status == .live else { return nil }
        return try Self.bomRecord(from: object)
    }

    /// One governed BOM, by object identity.
    public func bomObject(_ bomID: WorldObjectID) async throws -> BOMRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[bomID], object.status == .live else {
            throw ElectronicsWorldError.bomNotFound(bomID)
        }
        return try Self.bomRecord(from: object)
    }

    /// The governed assembly runs of a project, ordered by key.
    public func assemblies(projectID: WorldObjectID) async throws -> [AssemblyRecord] {
        let summary = try await projectSummary(projectID)
        let snapshot = await runtime.snapshot()
        return snapshot.objects.values
            .filter {
                $0.typeName == ElectronicsSchema.assemblyType
                    && $0.status == .live
                    && Self.stringField(Self.fields(of: $0), "projectLegacyID") == summary.legacyID
            }
            .compactMap { try? Self.assemblyRecord(from: $0) }
            .sorted { $0.key < $1.key }
    }

    /// One governed assembly run.
    public func assembly(_ assemblyID: WorldObjectID) async throws -> AssemblyRecord {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[assemblyID], object.status == .live else {
            throw ElectronicsWorldError.assemblyNotFound(assemblyID)
        }
        return try Self.assemblyRecord(from: object)
    }

    /// The immutable change history of one object, oldest first.
    public func history(_ objectID: WorldObjectID) async -> [ChangeRecord] {
        let snapshot = await runtime.snapshot()
        return snapshot.histories[objectID] ?? []
    }

    // MARK: - State shapes

    private static func projectState(for document: ElectronicsDocument) throws -> WorldValue {
        .object([
            "legacyID": .string(document.legacyID),
            "name": .string(document.name),
            "projectDescription": .string(document.projectDescription),
            "schematicKeys": .array(document.schematics.map { .string($0.key) }),
            "componentCount": .int(document.schematics.reduce(0) { $0 + $1.components.count }),
            "document": try WorldValueCodec.encode(document),
        ])
    }

    private static func schematicState(
        projectLegacyID: String,
        schematic: SchematicDocument
    ) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "key": .string(schematic.key),
            "kicadVersion": .string(schematic.kicadVersion),
            "sheetName": .string(schematic.sheetName),
            "componentReferences": .array(schematic.components.map { .string($0.reference) }),
        ])
    }

    private static func sheetState(
        projectLegacyID: String,
        schematicKey: String,
        sheetName: String,
        componentReferences: [String]
    ) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "schematicKey": .string(schematicKey),
            "sheetName": .string(sheetName),
            "componentReferences": .array(componentReferences.map { .string($0) }),
        ])
    }

    private static func sheetState(for record: SheetRecord) -> WorldValue {
        sheetState(
            projectLegacyID: record.projectLegacyID,
            schematicKey: record.schematicKey,
            sheetName: record.sheetName,
            componentReferences: record.componentReferences
        )
    }

    private static func symbolState(
        projectLegacyID: String,
        symbol: SymbolDocument
    ) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "libId": .string(symbol.libId),
            "pins": .array(symbol.pins.map(Self.pinState)),
        ])
    }

    private static func symbolState(for record: SymbolRecord) -> WorldValue {
        symbolState(
            projectLegacyID: record.projectLegacyID,
            symbol: SymbolDocument(libId: record.libId, pins: record.pins)
        )
    }

    private static func pinState(_ pin: SymbolPinDocument) -> WorldValue {
        .object([
            "number": .string(pin.number),
            "name": .string(pin.name),
            "electricalType": .string(pin.electricalType),
        ])
    }

    private static func componentState(
        projectLegacyID: String,
        schematicKey: String,
        sheetName: String,
        component: ComponentDocument
    ) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "schematicKey": .string(schematicKey),
            "sheetName": .string(sheetName),
            "reference": .string(component.reference),
            "libId": .string(component.libId),
            "value": .string(component.value),
            "fitted": .bool(component.fitted),
            "x": .double(component.x),
            "y": .double(component.y),
            "mirror": component.mirror.map(WorldValue.string) ?? .null,
        ])
    }

    private static func componentState(for record: ComponentRecord) -> WorldValue {
        componentState(
            projectLegacyID: record.projectLegacyID,
            schematicKey: record.schematicKey,
            sheetName: record.sheetName,
            component: ComponentDocument(
                reference: record.reference,
                libId: record.libId,
                value: record.value,
                fitted: record.fitted,
                x: record.x,
                y: record.y,
                mirror: record.mirror
            )
        )
    }

    private static func netState(projectLegacyID: String, net: NetDocument) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "name": .string(net.name),
            "netNumber": .int(net.netNumber),
            "netClass": .string(net.netClass),
            "pins": .array(net.pins.map { .string($0) }),
        ])
    }

    private static func netState(for record: NetRecord) -> WorldValue {
        netState(
            projectLegacyID: record.projectLegacyID,
            net: NetDocument(
                name: record.name,
                netNumber: record.netNumber,
                netClass: record.netClass,
                pins: record.pins
            )
        )
    }

    private static func busState(projectLegacyID: String, bus: BusDocument) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "name": .string(bus.name),
            "memberNetNames": .array(bus.memberNetNames.map { .string($0) }),
        ])
    }

    private static func busState(for record: BusRecord) -> WorldValue {
        busState(
            projectLegacyID: record.projectLegacyID,
            bus: BusDocument(name: record.name, memberNetNames: record.memberNetNames)
        )
    }

    private static func pcbState(projectLegacyID: String, pcb: PCBDocument) -> WorldValue {
        pcbState(
            projectLegacyID: projectLegacyID,
            version: pcb.version,
            layers: pcb.layers,
            footprintReferences: pcb.footprints.map(\.reference),
            tracks: pcb.tracks,
            viaCount: pcb.vias.count,
            netClasses: pcb.netClasses
        )
    }

    /// The one canonical PCB state shape, shared by import and mutation so
    /// a governed edit never loses net-class geometry it didn't touch.
    private static func pcbState(
        projectLegacyID: String,
        version: String,
        layers: [String],
        footprintReferences: [String],
        tracks: [TrackDocument],
        viaCount: Int,
        netClasses: [NetClassDocument]
    ) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "version": .string(version),
            "layers": .array(layers.map { .string($0) }),
            "footprintReferences": .array(footprintReferences.map { .string($0) }),
            "tracks": .array(tracks.map(Self.trackState)),
            "viaCount": .int(viaCount),
            "netClasses": .array(netClasses.map(Self.netClassState)),
        ])
    }

    private static func pcbState(for record: PCBRecord) -> WorldValue {
        pcbState(
            projectLegacyID: record.projectLegacyID,
            version: record.version,
            layers: record.layers,
            footprintReferences: record.footprintReferences,
            tracks: record.tracks,
            viaCount: record.viaCount,
            netClasses: record.netClasses
        )
    }

    private static func trackState(_ track: TrackDocument) -> WorldValue {
        .object([
            "startX": .double(track.startX),
            "startY": .double(track.startY),
            "endX": .double(track.endX),
            "endY": .double(track.endY),
            "width": .double(track.width),
            "layer": .string(track.layer),
            "netName": .string(track.netName),
        ])
    }

    private static func netClassState(_ netClass: NetClassDocument) -> WorldValue {
        .object([
            "name": .string(netClass.name),
            "trackWidth": .double(netClass.trackWidth),
            "clearance": .double(netClass.clearance),
            "viaDiameter": .double(netClass.viaDiameter),
            "viaDrill": .double(netClass.viaDrill),
            "nets": .array(netClass.nets.map { .string($0) }),
        ])
    }

    private static func footprintState(
        projectLegacyID: String,
        footprint: FootprintDocument
    ) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "reference": .string(footprint.reference),
            "libId": .string(footprint.libId),
            "layer": .string(footprint.layer),
            "x": .double(footprint.x),
            "y": .double(footprint.y),
            "rotation": .double(footprint.rotation),
            "padNetNames": .array(footprint.pads.map { .string($0.netName) }),
        ])
    }

    private static func footprintState(for record: FootprintRecord) -> WorldValue {
        .object([
            "projectLegacyID": .string(record.projectLegacyID),
            "reference": .string(record.reference),
            "libId": .string(record.libId),
            "layer": .string(record.layer),
            "x": .double(record.x),
            "y": .double(record.y),
            "rotation": .double(record.rotation),
            "padNetNames": .array(record.padNetNames.map { .string($0) }),
        ])
    }

    private static func bomState(projectLegacyID: String, bom: BOMDocument) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "lineItems": .array(bom.lineItems.map(Self.bomLineItemState)),
        ])
    }

    private static func bomState(for record: BOMRecord) -> WorldValue {
        .object([
            "projectLegacyID": .string(record.projectLegacyID),
            "lineItems": .array(record.lineItems.map(Self.bomLineItemState)),
        ])
    }

    private static func bomLineItemState(_ item: BOMLineItemDocument) -> WorldValue {
        .object([
            "reference": .string(item.reference),
            "value": .string(item.value),
            "quantity": .int(item.quantity),
            "fitted": .bool(item.fitted),
            "lcscPartNumber": item.lcscPartNumber.map(WorldValue.string) ?? .null,
            "assemblyType": .string(item.assemblyType),
        ])
    }

    private static func assemblyState(
        projectLegacyID: String,
        assembly: AssemblyDocument
    ) -> WorldValue {
        .object([
            "projectLegacyID": .string(projectLegacyID),
            "key": .string(assembly.key),
            "provider": .string(assembly.provider),
            "lines": .array(assembly.lines.map(Self.assemblyLineState)),
            "assemblyFee": assembly.assemblyFee.map(WorldValue.double) ?? .null,
            "deliveryTime": assembly.deliveryTime.map(WorldValue.string) ?? .null,
        ])
    }

    private static func assemblyState(for record: AssemblyRecord) -> WorldValue {
        assemblyState(
            projectLegacyID: record.projectLegacyID,
            assembly: AssemblyDocument(
                key: record.key,
                provider: record.provider,
                lines: record.lines,
                assemblyFee: record.assemblyFee,
                deliveryTime: record.deliveryTime
            )
        )
    }

    private static func assemblyLineState(_ line: AssemblyLineDocument) -> WorldValue {
        .object([
            "reference": .string(line.reference),
            "lcscPartNumber": .string(line.lcscPartNumber),
            "assemblyType": .string(line.assemblyType),
            "inStock": .bool(line.inStock),
        ])
    }

    // MARK: - Record decoding

    private static func fields(of object: WorldObject) -> [String: WorldValue] {
        if case .object(let fields) = object.state { return fields }
        return [:]
    }

    private static func stringField(_ fields: [String: WorldValue], _ key: String) -> String? {
        if case .string(let value)? = fields[key] { return value }
        return nil
    }

    private static func doubleField(_ fields: [String: WorldValue], _ key: String) -> Double? {
        if case .double(let value)? = fields[key] { return value }
        return nil
    }

    private static func stringArrayField(
        _ fields: [String: WorldValue], _ key: String
    ) -> [String]? {
        guard case .array(let values)? = fields[key] else { return nil }
        return values.compactMap {
            if case .string(let value) = $0 { return value }
            return nil
        }
    }

    private func projectSummary(_ projectID: WorldObjectID) async throws -> ProjectSummary {
        let snapshot = await runtime.snapshot()
        guard let object = snapshot.objects[projectID], object.status == .live else {
            throw ElectronicsWorldError.projectNotFound(projectID)
        }
        guard let summary = Self.summary(from: object) else {
            throw ElectronicsWorldError.malformedState(
                "project \(projectID) state is malformed"
            )
        }
        return summary
    }

    private static func schematicKeys(
        in snapshot: WorldSnapshot,
        projectID: WorldObjectID
    ) -> [String] {
        guard let object = snapshot.objects[projectID],
              case .object(let projectFields) = object.state,
              case .array(let keyValues)? = projectFields["schematicKeys"]
        else { return [] }
        return keyValues.compactMap {
            if case .string(let key) = $0 { return key }
            return nil
        }
    }

    /// The `<projectID>/…` composite legacy ID of an object derived from a
    /// project, if it is one of the derived kinds carrying a
    /// `projectLegacyID` field. Used to cascade deletes without guessing
    /// from type names.
    private static func derivedLegacyID(
        of object: WorldObject,
        projectLegacyID: String
    ) -> String? {
        let fields = Self.fields(of: object)
        guard object.typeName != ElectronicsSchema.projectType,
              Self.stringField(fields, "projectLegacyID") == projectLegacyID
        else { return nil }
        if let key = Self.stringField(fields, "key") { return key }
        if let reference = Self.stringField(fields, "reference") { return reference }
        if let name = Self.stringField(fields, "name") { return name }
        if let libId = Self.stringField(fields, "libId") { return libId }
        if let sheetName = Self.stringField(fields, "sheetName") { return sheetName }
        return object.typeName
    }

    private static func summary(from object: WorldObject) -> ProjectSummary? {
        guard case .object(let fields) = object.state,
              case .string(let legacyID)? = fields["legacyID"],
              case .string(let name)? = fields["name"],
              case .array(let keyValues)? = fields["schematicKeys"],
              case .int(let componentCount)? = fields["componentCount"]
        else { return nil }
        return ProjectSummary(
            objectID: object.id,
            legacyID: legacyID,
            name: name,
            schematicCount: keyValues.count,
            componentCount: componentCount,
            version: object.version
        )
    }

    private static func schematicRecord(from object: WorldObject) throws -> SchematicRecord {
        let fields = Self.fields(of: object)
        guard let projectLegacyID = Self.stringField(fields, "projectLegacyID"),
              let key = Self.stringField(fields, "key"),
              let kicadVersion = Self.stringField(fields, "kicadVersion"),
              let sheetName = Self.stringField(fields, "sheetName"),
              let componentReferences = Self.stringArrayField(fields, "componentReferences")
        else {
            throw ElectronicsWorldError.malformedState(
                "schematic \(object.id) state is malformed"
            )
        }
        return SchematicRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            key: key,
            kicadVersion: kicadVersion,
            sheetName: sheetName,
            componentCount: componentReferences.count
        )
    }

    private static func sheetRecord(from object: WorldObject) throws -> SheetRecord {
        let fields = Self.fields(of: object)
        guard let projectLegacyID = Self.stringField(fields, "projectLegacyID"),
              let schematicKey = Self.stringField(fields, "schematicKey"),
              let sheetName = Self.stringField(fields, "sheetName"),
              let componentReferences = Self.stringArrayField(fields, "componentReferences")
        else {
            throw ElectronicsWorldError.malformedState(
                "sheet \(object.id) state is malformed"
            )
        }
        return SheetRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            schematicKey: schematicKey,
            sheetName: sheetName,
            componentReferences: componentReferences
        )
    }

    private static func symbolRecord(from object: WorldObject) throws -> SymbolRecord {
        let fields = Self.fields(of: object)
        guard let projectLegacyID = Self.stringField(fields, "projectLegacyID"),
              let libId = Self.stringField(fields, "libId"),
              case .array(let pinValues)? = fields["pins"]
        else {
            throw ElectronicsWorldError.malformedState(
                "symbol \(object.id) state is malformed"
            )
        }
        let pins: [SymbolPinDocument] = pinValues.compactMap { value in
            guard case .object(let pinFields) = value,
                  let number = Self.stringField(pinFields, "number"),
                  let name = Self.stringField(pinFields, "name"),
                  let electricalType = Self.stringField(pinFields, "electricalType")
            else { return nil }
            return SymbolPinDocument(
                number: number,
                name: name,
                electricalType: electricalType
            )
        }
        return SymbolRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            libId: libId,
            pins: pins
        )
    }

    private static func componentRecord(from object: WorldObject) throws -> ComponentRecord {
        let fields = Self.fields(of: object)
        guard let projectLegacyID = Self.stringField(fields, "projectLegacyID"),
              let schematicKey = Self.stringField(fields, "schematicKey"),
              let sheetName = Self.stringField(fields, "sheetName"),
              let reference = Self.stringField(fields, "reference"),
              let libId = Self.stringField(fields, "libId"),
              let value = Self.stringField(fields, "value"),
              case .bool(let fitted)? = fields["fitted"],
              let x = Self.doubleField(fields, "x"),
              let y = Self.doubleField(fields, "y")
        else {
            throw ElectronicsWorldError.malformedState(
                "component \(object.id) state is malformed"
            )
        }
        let mirror = Self.stringField(fields, "mirror")
        return ComponentRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            schematicKey: schematicKey,
            sheetName: sheetName,
            reference: reference,
            libId: libId,
            value: value,
            fitted: fitted,
            x: x,
            y: y,
            mirror: mirror
        )
    }

    private static func netRecord(from object: WorldObject) throws -> NetRecord {
        let fields = Self.fields(of: object)
        guard let projectLegacyID = Self.stringField(fields, "projectLegacyID"),
              let name = Self.stringField(fields, "name"),
              case .int(let netNumber)? = fields["netNumber"],
              let netClass = Self.stringField(fields, "netClass"),
              let pins = Self.stringArrayField(fields, "pins")
        else {
            throw ElectronicsWorldError.malformedState(
                "net \(object.id) state is malformed"
            )
        }
        return NetRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            name: name,
            netNumber: netNumber,
            netClass: netClass,
            pins: pins
        )
    }

    private static func busRecord(from object: WorldObject) throws -> BusRecord {
        let fields = Self.fields(of: object)
        guard let projectLegacyID = Self.stringField(fields, "projectLegacyID"),
              let name = Self.stringField(fields, "name"),
              let memberNetNames = Self.stringArrayField(fields, "memberNetNames")
        else {
            throw ElectronicsWorldError.malformedState(
                "bus \(object.id) state is malformed"
            )
        }
        return BusRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            name: name,
            memberNetNames: memberNetNames
        )
    }

    private static func pcbRecord(from object: WorldObject) throws -> PCBRecord {
        let fields = Self.fields(of: object)
        guard let projectLegacyID = Self.stringField(fields, "projectLegacyID"),
              let version = Self.stringField(fields, "version"),
              let layers = Self.stringArrayField(fields, "layers"),
              let footprintReferences = Self.stringArrayField(fields, "footprintReferences"),
              case .array(let trackValues)? = fields["tracks"],
              case .int(let viaCount)? = fields["viaCount"]
        else {
            throw ElectronicsWorldError.malformedState(
                "pcb \(object.id) state is malformed"
            )
        }
        let tracks: [TrackDocument] = trackValues.compactMap { value in
            guard case .object(let trackFields) = value,
                  let startX = Self.doubleField(trackFields, "startX"),
                  let startY = Self.doubleField(trackFields, "startY"),
                  let endX = Self.doubleField(trackFields, "endX"),
                  let endY = Self.doubleField(trackFields, "endY"),
                  let width = Self.doubleField(trackFields, "width"),
                  let layer = Self.stringField(trackFields, "layer"),
                  let netName = Self.stringField(trackFields, "netName")
            else { return nil }
            return TrackDocument(
                startX: startX,
                startY: startY,
                endX: endX,
                endY: endY,
                width: width,
                layer: layer,
                netName: netName
            )
        }
        guard case .array(let netClassValues)? = fields["netClasses"]
        else {
            throw ElectronicsWorldError.malformedState(
                "pcb \(object.id) state is malformed"
            )
        }
        let netClasses: [NetClassDocument] = netClassValues.compactMap { value in
            guard case .object(let netClassFields) = value,
                  let name = Self.stringField(netClassFields, "name"),
                  let trackWidth = Self.doubleField(netClassFields, "trackWidth"),
                  let clearance = Self.doubleField(netClassFields, "clearance"),
                  let viaDiameter = Self.doubleField(netClassFields, "viaDiameter"),
                  let viaDrill = Self.doubleField(netClassFields, "viaDrill"),
                  let nets = Self.stringArrayField(netClassFields, "nets")
            else { return nil }
            return NetClassDocument(
                name: name,
                trackWidth: trackWidth,
                clearance: clearance,
                viaDiameter: viaDiameter,
                viaDrill: viaDrill,
                nets: nets
            )
        }
        return PCBRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            version: version,
            layers: layers,
            footprintReferences: footprintReferences,
            tracks: tracks,
            viaCount: viaCount,
            netClasses: netClasses
        )
    }

    private static func footprintRecord(from object: WorldObject) throws -> FootprintRecord {
        let fields = Self.fields(of: object)
        guard let projectLegacyID = Self.stringField(fields, "projectLegacyID"),
              let reference = Self.stringField(fields, "reference"),
              let libId = Self.stringField(fields, "libId"),
              let layer = Self.stringField(fields, "layer"),
              let x = Self.doubleField(fields, "x"),
              let y = Self.doubleField(fields, "y"),
              let rotation = Self.doubleField(fields, "rotation"),
              let padNetNames = Self.stringArrayField(fields, "padNetNames")
        else {
            throw ElectronicsWorldError.malformedState(
                "footprint \(object.id) state is malformed"
            )
        }
        return FootprintRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            reference: reference,
            libId: libId,
            layer: layer,
            x: x,
            y: y,
            rotation: rotation,
            padCount: padNetNames.count,
            padNetNames: padNetNames
        )
    }

    private static func bomRecord(from object: WorldObject) throws -> BOMRecord {
        let fields = Self.fields(of: object)
        guard let projectLegacyID = Self.stringField(fields, "projectLegacyID"),
              case .array(let lineValues)? = fields["lineItems"]
        else {
            throw ElectronicsWorldError.malformedState(
                "bom \(object.id) state is malformed"
            )
        }
        let lineItems: [BOMLineItemDocument] = lineValues.compactMap { value in
            guard case .object(let lineFields) = value,
                  let reference = Self.stringField(lineFields, "reference"),
                  let lineValue = Self.stringField(lineFields, "value"),
                  case .int(let quantity)? = lineFields["quantity"],
                  case .bool(let fitted)? = lineFields["fitted"],
                  let assemblyType = Self.stringField(lineFields, "assemblyType")
            else { return nil }
            return BOMLineItemDocument(
                reference: reference,
                value: lineValue,
                quantity: quantity,
                fitted: fitted,
                lcscPartNumber: Self.stringField(lineFields, "lcscPartNumber"),
                assemblyType: assemblyType
            )
        }
        return BOMRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            lineItems: lineItems
        )
    }

    private static func assemblyRecord(from object: WorldObject) throws -> AssemblyRecord {
        let fields = Self.fields(of: object)
        guard let projectLegacyID = Self.stringField(fields, "projectLegacyID"),
              let key = Self.stringField(fields, "key"),
              let provider = Self.stringField(fields, "provider"),
              case .array(let lineValues)? = fields["lines"]
        else {
            throw ElectronicsWorldError.malformedState(
                "assembly \(object.id) state is malformed"
            )
        }
        let lines: [AssemblyLineDocument] = lineValues.compactMap { value in
            guard case .object(let lineFields) = value,
                  let reference = Self.stringField(lineFields, "reference"),
                  let lcscPartNumber = Self.stringField(lineFields, "lcscPartNumber"),
                  let assemblyType = Self.stringField(lineFields, "assemblyType"),
                  case .bool(let inStock)? = lineFields["inStock"]
            else { return nil }
            return AssemblyLineDocument(
                reference: reference,
                lcscPartNumber: lcscPartNumber,
                assemblyType: assemblyType,
                inStock: inStock
            )
        }
        let assemblyFee = Self.doubleField(fields, "assemblyFee")
        let deliveryTime = Self.stringField(fields, "deliveryTime")
        return AssemblyRecord(
            objectID: object.id,
            projectLegacyID: projectLegacyID,
            key: key,
            provider: provider,
            lines: lines,
            assemblyFee: assemblyFee,
            deliveryTime: deliveryTime
        )
    }
}
