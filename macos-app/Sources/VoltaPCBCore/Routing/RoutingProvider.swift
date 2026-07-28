//
//  RoutingProvider.swift
//  VoltaPCBCore
//
//  Phase 253 Task 1 — Routing Provider Protocol Foundation
//
//  Vendor-neutral protocol for PCB auto-routing engines. Implementations
//  (Freerouting, KiCad native, future cloud adapters) live in the Volta
//  app target and translate their format-specific IO into RoutingResult
//  at the adapter boundary — no vendor specifics escape the adapter.
//
//  ponytail: domain isolation. Provider never sees KiCad / Freerouting /
//  DeepPCB internals; only the protocol contract. Format conversions
//  (DSN ⇄ .kicad_pcb, .kicad_pcb → cloud upload) belong in adapters.
//
//  Mirrors ComponentDataProvider shape:
//    - Sendable constraint
//    - ProviderAvailability enum reused
//    - name / displayName / capabilities / availability
//    - Difference: output is RoutingResult (mutated .kicad_pcb + log +
//      metrics), not UnifiedComponent.
//

import Foundation

// MARK: - Length

/// Length in millimeters. Plain Double so adapters serialize without a
/// custom Length type. Keep the SI convention here so RoutingRules is
/// unambiguous when read from disk.
public typealias Length = Double

// MARK: - Routing Capability

/// Capabilities a routing provider can declare. Drives UI filtering
/// (e.g., "show only offline routers") and registry ordering.
public enum RoutingCapability: String, Sendable, Hashable, CaseIterable {
    /// Fully automatic — hands the board off and returns a routed result.
    case autoroute
    /// Supports step-by-step human guidance (interactive router).
    case interactive
    /// Requires network to operate (cloud router).
    case cloud
    /// Works fully local (no network).
    case offline
    /// Routes power nets with current-aware heuristics.
    case powerAware
}

// MARK: - Net Class

/// Routing net class — drives clearance / trace-width / via-size overrides.
public enum NetClass: String, Sendable, Codable, CaseIterable {
    case signal
    case power
    case analog
    case digital
}

// MARK: - Routing Rules

/// Vendor-neutral design rules and routing parameters. Every adapter must
/// accept this shape; adapter-specific config (e.g., Freerouting optimization
/// passes) lives in the adapter's own namespace and is not part of the
/// protocol contract.
public struct RoutingRules: Sendable, Codable, Equatable {
    /// Number of copper layers (2, 4, 6, …).
    public var layerCount: Int

    /// Minimum clearance between traces / pads, in mm.
    public var clearance: Length

    /// Minimum trace width, in mm.
    public var minTraceWidth: Length

    /// Minimum via pad diameter, in mm.
    public var minViaSize: Length

    /// Net-class specific overrides. Empty means "use defaults for all".
    public var netClasses: [NetClass]

    /// Maximum time the router is allowed to spend before being cancelled.
    public var timeout: Duration

    public init(
        layerCount: Int = 2,
        clearance: Length = 0.2,
        minTraceWidth: Length = 0.15,
        minViaSize: Length = 0.4,
        netClasses: [NetClass] = [.signal, .power],
        timeout: Duration = .seconds(600)
    ) {
        self.layerCount = layerCount
        self.clearance = clearance
        self.minTraceWidth = minTraceWidth
        self.minViaSize = minViaSize
        self.netClasses = netClasses
        self.timeout = timeout
    }
}

// MARK: - Routing Progress

/// Streamed progress events emitted by `route(...)` via the optional
/// progress closure. Lets the UI show percent-complete or log lines
/// without polling.
public enum RoutingProgress: Sendable, Equatable {
    /// Routing has begun on the board.
    case started
    /// Percent complete in [0.0, 1.0]. Some routers don't emit this —
    /// adapters should emit `log` instead.
    case percent(Double)
    /// Free-form log line for the UI's progress pane.
    case log(String)
    /// Routing finished (regardless of success — check RoutingResult).
    case completed
}

// MARK: - Routing Metrics

/// Quantitative output of a routing pass. Surfaced to the UI for the
/// "before / after" summary and to the merge engine if downstream actions
/// consume the result.
public struct RoutingMetrics: Sendable, Codable, Equatable {
    public let wiresRouted: Int
    public let viasPlaced: Int
    /// Net names that could not be routed within `RoutingRules.timeout`.
    public let unroutedNets: [String]
    public let layers: Int

    public init(wiresRouted: Int, viasPlaced: Int, unroutedNets: [String], layers: Int) {
        self.wiresRouted = wiresRouted
        self.viasPlaced = viasPlaced
        self.unroutedNets = unroutedNets
        self.layers = layers
    }
}

// MARK: - Routing Result

/// Result of a successful `route(...)` call. The mutated .kicad_pcb is
/// written in-place to `pcbFile`; `log` is the saved router log for the
/// UI / debug pane.
public struct RoutingResult: Sendable {
    /// Mutated .kicad_pcb on disk. Caller is responsible for re-loading.
    public let pcbFile: URL

    /// Saved router log file (human-readable stdout from the engine).
    public let log: URL

    /// Quantitative metrics for the routing pass.
    public let metrics: RoutingMetrics

    /// Provider name that produced this result — useful when multiple
    /// registries route the same board and the user wants source attribution.
    public let providerName: String

    /// Wall-clock duration of the routing pass.
    public let duration: TimeInterval

    public init(
        pcbFile: URL,
        log: URL,
        metrics: RoutingMetrics,
        providerName: String,
        duration: TimeInterval
    ) {
        self.pcbFile = pcbFile
        self.log = log
        self.metrics = metrics
        self.providerName = providerName
        self.duration = duration
    }
}

// MARK: - PCB Summary

/// Lightweight board description used by `estimateTime(...)` so adapters
/// can quote an ETA without parsing the full .kicad_pcb.
public struct PCBSummary: Sendable, Equatable {
    public let componentCount: Int
    public let netCount: Int
    public let layerCount: Int
    /// Board outline bounding box in mm. Width × Height.
    public let boardSize: Size2D

    public init(componentCount: Int, netCount: Int, layerCount: Int, boardSize: Size2D) {
        self.componentCount = componentCount
        self.netCount = netCount
        self.layerCount = layerCount
        self.boardSize = boardSize
    }
}

/// 2D size (width × height) in mm.
public struct Size2D: Sendable, Equatable, Codable {
    public let width: Length
    public let height: Length

    public init(width: Length, height: Length) {
        self.width = width
        self.height = height
    }
}

// MARK: - Routing Provider

/// Protocol for PCB auto-routing engines. Implementations: Freerouting,
/// KiCad native router, future cloud adapters. Adapters translate their
/// vendor-native IO into RoutingResult at the adapter boundary so nothing
/// vendor-specific escapes the adapter module.
public protocol RoutingProvider: Sendable {
    /// Unique machine identifier (e.g., "freerouting"). Stable across
    /// releases — used as the registry partition key.
    var name: String { get }

    /// User-facing display name (e.g., "Freerouting"). Shown in the
    /// routing provider picker UI.
    var displayName: String { get }

    /// Capabilities this provider offers. Drives UI filtering and
    /// registry ordering ("prefer offline routers if no cloud credential").
    var capabilities: Set<RoutingCapability> { get }

    /// Current availability state. Async — may probe for the engine
    /// binary, network, or credentials before reporting. Polled by the
    /// registry on app launch and after Settings changes.
    var availability: ProviderAvailability { get async }

    /// Route a board. The provider MUST write the mutated .kicad_pcb to
    /// `pcbFile` (or a URL returned in RoutingResult), and write the
    /// router log to a URL returned in RoutingResult. May stream
    /// `RoutingProgress` via the optional `progress` closure.
    func route(
        pcbFile: URL,
        rules: RoutingRules,
        progress: (@Sendable (RoutingProgress) -> Void)?
    ) async throws -> RoutingResult

    /// Best-effort estimate of routing time for the given board summary.
    /// Returns nil if the provider cannot estimate (e.g., missing engine).
    func estimateTime(board: PCBSummary) -> TimeInterval?
}