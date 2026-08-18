//
//  PlacementConstraints.swift
//  Volta
//
//  volta-24 follow-on: contextual placement constraints — Swift mirror.
//
//  Codable model matching the flat LLM/operation JSON shape
//  (GenerationIntent.placement_constraints / AutoPlaceOp.constraints),
//  plus the pure gate math (penalty + validation) ported from
//  volta.placement.constraints so the app can gate placements without a
//  daemon round-trip.
//

import Foundation

// MARK: - Model

enum PlacementRuleType: String, Codable, Sendable, CaseIterable {
    case edgeAffinity = "edge_affinity"
    case region
    case avoid
    case approach
    case orientation
}

enum PlacementRuleSource: String, Codable, Sendable {
    case explicit, inferred, learned, imported
}

enum PlacementEdge: String, Codable, Sendable, CaseIterable {
    case top, bottom, left, right
}

/// One natural-language placement intent, in the flat spec shape the LLM
/// fills and the ops carry. `refs` are component references; the
/// type-specific fields apply per `ruleType`.
struct PlacementConstraint: Codable, Sendable, Equatable, Identifiable {
    var id: String { ruleId }
    var ruleId: String
    var ruleType: PlacementRuleType
    var refs: [String]
    var refsB: [String]?
    var mm: Double?
    var edge: PlacementEdge?
    var region: [Double]?
    var regionName: String?
    var rotation: Double?
    var source: PlacementRuleSource
    var rationale: String

    enum CodingKeys: String, CodingKey {
        case ruleId = "rule_id"
        case ruleType = "rule_type"
        case refs
        case refsB = "refs_b"
        case mm
        case edge
        case region
        case regionName = "name"
        case rotation
        case source
        case rationale
    }

    init(
        ruleId: String? = nil,
        ruleType: PlacementRuleType,
        refs: [String],
        refsB: [String]? = nil,
        mm: Double? = nil,
        edge: PlacementEdge? = nil,
        region: [Double]? = nil,
        regionName: String? = nil,
        rotation: Double? = nil,
        source: PlacementRuleSource = .explicit,
        rationale: String = ""
    ) {
        self.ruleId = ruleId ?? "rule-\(ruleType.rawValue)-\(refs.joined(separator: "-"))"
        self.ruleType = ruleType
        self.refs = refs
        self.refsB = refsB
        self.mm = mm
        self.edge = edge
        self.region = region
        self.regionName = regionName
        self.rotation = rotation
        self.source = source
        self.rationale = rationale
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ruleId = try c.decodeIfPresent(String.self, forKey: .ruleId)
            ?? "rule-unset"
        ruleType = try c.decode(PlacementRuleType.self, forKey: .ruleType)
        refs = try c.decode([String].self, forKey: .refs)
        refsB = try c.decodeIfPresent([String].self, forKey: .refsB)
        mm = try c.decodeIfPresent(Double.self, forKey: .mm)
        edge = try c.decodeIfPresent(PlacementEdge.self, forKey: .edge)
        region = try c.decodeIfPresent([Double].self, forKey: .region)
        regionName = try c.decodeIfPresent(String.self, forKey: .regionName)
        rotation = try c.decodeIfPresent(Double.self, forKey: .rotation)
        source = try c.decodeIfPresent(PlacementRuleSource.self, forKey: .source) ?? .explicit
        rationale = try c.decodeIfPresent(String.self, forKey: .rationale) ?? ""
    }

    /// Cross-field validation, mirroring the Python model.
    func validated() throws -> PlacementConstraint {
        switch ruleType {
        case .avoid, .approach:
            guard let refsB, !refsB.isEmpty, let mm, mm > 0 else {
                throw PlacementConstraintError.malformed(
                    "\(ruleType.rawValue): requires refs_b and a positive mm"
                )
            }
        case .edgeAffinity:
            guard edge != nil else {
                throw PlacementConstraintError.malformed("edge_affinity: requires edge")
            }
        case .region:
            guard let region, region.count == 4, region[2] > region[0], region[3] > region[1] else {
                throw PlacementConstraintError.malformed(
                    "region: requires [x1, y1, x2, y2] with x2/y2 exceeding x1/y1"
                )
            }
        case .orientation:
            guard rotation != nil else {
                throw PlacementConstraintError.malformed("orientation: requires rotation")
            }
        }
        return self
    }
}

enum PlacementConstraintError: Error, LocalizedError, Equatable {
    case malformed(String)

    var errorDescription: String? {
        switch self {
        case .malformed(let message):
            return message
        }
    }
}

// MARK: - Gate math (ported from volta.placement.constraints)

/// ref -> (x, y, rotation)
typealias PlacementPositions = [String: (x: Double, y: Double, rotation: Double)]

struct PlacementRuleViolation: Equatable, Sendable {
    let ruleId: String
    let ruleType: PlacementRuleType
    let ref: String
    let message: String
    let actualMM: Double?
    let requiredMM: Double?
}

enum PlacementConstraints {

    /// Squared-mm penalty for the SA-style objective (same scale as the
    /// Python clearance terms).
    static func penalty(
        _ constraints: [PlacementConstraint],
        positions: PlacementPositions,
        boardWidth: Double,
        boardHeight: Double
    ) -> Double {
        var total = 0.0
        for rule in constraints {
            switch rule.ruleType {
            case .avoid, .approach:
                guard let mm = rule.mm else { continue }
                for a in rule.refs {
                    guard let pa = positions[a] else { continue }
                    for b in rule.refsB ?? [] {
                        guard let pb = positions[b] else { continue }
                        let d = hypot(pa.x - pb.x, pa.y - pb.y)
                        if rule.ruleType == .avoid {
                            total += max(0, mm - d) * max(0, mm - d)
                        } else {
                            total += max(0, d - mm) * max(0, d - mm)
                        }
                    }
                }
            case .edgeAffinity:
                let mm = rule.mm ?? 5.0
                for ref in rule.refs {
                    guard let p = positions[ref], let edge = rule.edge else { continue }
                    let dist: Double
                    switch edge {
                    case .bottom: dist = p.y
                    case .top: dist = boardHeight - p.y
                    case .left: dist = p.x
                    case .right: dist = boardWidth - p.x
                    }
                    if dist > mm { total += (dist - mm) * (dist - mm) }
                }
            case .region:
                guard let r = rule.region, r.count == 4 else { continue }
                for ref in rule.refs {
                    guard let p = positions[ref] else { continue }
                    let dx = max(0, r[0] - p.x, p.x - r[2])
                    let dy = max(0, r[1] - p.y, p.y - r[3])
                    total += dx * dx + dy * dy
                }
            case .orientation:
                guard let want = rule.rotation else { continue }
                for ref in rule.refs {
                    guard let p = positions[ref] else { continue }
                    let diff = abs((p.rotation - want + 180).truncatingRemainder(dividingBy: 360) - 180)
                    total += diff * diff
                }
            }
        }
        return total
    }

    /// Post-placement gate: structured violations with concrete numbers.
    static func validate(
        _ constraints: [PlacementConstraint],
        positions: PlacementPositions,
        boardWidth: Double,
        boardHeight: Double
    ) -> [PlacementRuleViolation] {
        var violations: [PlacementRuleViolation] = []
        for rule in constraints {
            switch rule.ruleType {
            case .avoid, .approach:
                guard let mm = rule.mm else { continue }
                for a in rule.refs {
                    guard let pa = positions[a] else { continue }
                    for b in rule.refsB ?? [] {
                        guard let pb = positions[b] else { continue }
                        let d = hypot(pa.x - pb.x, pa.y - pb.y)
                        let bad = rule.ruleType == .avoid ? d < mm : d > mm
                        if bad {
                            let word = rule.ruleType == .avoid ? "closer" : "further"
                            violations.append(PlacementRuleViolation(
                                ruleId: rule.ruleId,
                                ruleType: rule.ruleType,
                                ref: a,
                                message: "\(a) is \(String(format: "%.1f", d))mm from \(b) — rule requires \(word) than \(String(format: "%.1f", mm))mm",
                                actualMM: d,
                                requiredMM: mm
                            ))
                        }
                    }
                }
            case .edgeAffinity:
                let mm = rule.mm ?? 5.0
                for ref in rule.refs {
                    guard let p = positions[ref], let edge = rule.edge else { continue }
                    let dist: Double
                    switch edge {
                    case .bottom: dist = p.y
                    case .top: dist = boardHeight - p.y
                    case .left: dist = p.x
                    case .right: dist = boardWidth - p.x
                    }
                    if dist > mm {
                        violations.append(PlacementRuleViolation(
                            ruleId: rule.ruleId,
                            ruleType: rule.ruleType,
                            ref: ref,
                            message: "\(ref) is \(String(format: "%.1f", dist))mm from the \(edge.rawValue) edge — rule allows \(String(format: "%.1f", mm))mm",
                            actualMM: dist,
                            requiredMM: mm
                        ))
                    }
                }
            case .region:
                guard let r = rule.region, r.count == 4 else { continue }
                let name = rule.regionName ?? "region"
                for ref in rule.refs {
                    guard let p = positions[ref] else { continue }
                    if !(r[0]...r[2]).contains(p.x) || !(r[1]...r[3]).contains(p.y) {
                        violations.append(PlacementRuleViolation(
                            ruleId: rule.ruleId,
                            ruleType: rule.ruleType,
                            ref: ref,
                            message: "\(ref) at (\(String(format: "%.1f", p.x)), \(String(format: "%.1f", p.y))) is outside region '\(name)'",
                            actualMM: nil,
                            requiredMM: nil
                        ))
                    }
                }
            case .orientation:
                guard let want = rule.rotation else { continue }
                for ref in rule.refs {
                    guard let p = positions[ref] else { continue }
                    let diff = abs((p.rotation - want + 180).truncatingRemainder(dividingBy: 360) - 180)
                    if diff > 1e-6 {
                        violations.append(PlacementRuleViolation(
                            ruleId: rule.ruleId,
                            ruleType: rule.ruleType,
                            ref: ref,
                            message: "\(ref) rotated \(Int(p.rotation))° — rule requires \(Int(want))°",
                            actualMM: nil,
                            requiredMM: nil
                        ))
                    }
                }
            }
        }
        return violations
    }
}
