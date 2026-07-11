//
//  TopologyBuilder.swift
//  Phase 221 — Net Resolution via Union-Find
//
//  Resolves pin-to-net connectivity from the parsed schematic.
//  Groups pins, wire endpoints, and labels into electrically connected
//  clusters using a union-find data structure.
//
//  This is the Swift port of analysis/topology_builder.py _resolve_pin_nets().
//

import Foundation

/// Union-Find data structure for grouping electrically connected positions.
struct UnionFind {
    private var parent: [PositionKey: PositionKey] = [:]

    mutating func add(_ pos: PositionKey) {
        parent[pos] = pos
    }

    mutating func find(_ pos: PositionKey) -> PositionKey {
        var root = pos
        while parent[root] != root {
            root = parent[root]!
        }
        // Path compression
        var current = pos
        while parent[current] != root {
            let next = parent[current]!
            parent[current] = root
            current = next
        }
        return root
    }

    mutating func union(_ a: PositionKey, _ b: PositionKey) {
        let ra = find(a)
        let rb = find(b)
        if ra != rb {
            parent[ra] = rb
        }
    }
}

/// Rounded position key for consistent matching (avoids float drift).
struct PositionKey: Hashable, Sendable {
    let x100: Int
    let y100: Int
}

func roundPos(_ x: Double, _ y: Double, decimals: Int = 2) -> PositionKey {
    let mult = pow(10.0, Double(decimals))
    return PositionKey(x100: Int((x * mult).rounded()), y100: Int((y * mult).rounded()))
}

/// Resolves pin-to-net mapping from a parsed schematic.
struct TopologyBuilder {

    /// Result: maps (ref, pinNumber) -> netName
    typealias PinNets = [String: String]  // "ref.pin" -> "netName"

    /// Resolve all pins to their net names.
    ///
    /// Algorithm:
    /// 1. Build union-find over all pin positions, wire endpoints, label positions
    /// 2. Union wire endpoints (connecting start to end)
    /// 3. Union positions that share the same rounded coordinates
    /// 4. Group: each connected component gets a net name from its labels
    static func resolvePinNets(
        pins: [(ref: String, number: String, position: (Double, Double))],
        wires: [(start: (Double, Double), end: (Double, Double))],
        labels: [(name: String, position: (Double, Double))]
    ) -> PinNets {
        var uf = UnionFind()

        // Add all positions
        for pin in pins {
            let key = roundPos(pin.position.0, pin.position.1)
            uf.add(key)
        }
        for wire in wires {
            uf.add(roundPos(wire.start.0, wire.start.1))
            uf.add(roundPos(wire.end.0, wire.end.1))
        }
        for label in labels {
            uf.add(roundPos(label.position.0, label.position.1))
        }

        // Union wire endpoints
        for wire in wires {
            uf.union(
                roundPos(wire.start.0, wire.start.1),
                roundPos(wire.end.0, wire.end.1)
            )
        }

        // Build groups
        var groups: [PositionKey: Set<PositionKey>] = [:]
        for pin in pins {
            let key = roundPos(pin.position.0, pin.position.1)
            let root = uf.find(key)
            groups[root, default: []].insert(key)
        }
        for wire in wires {
            let s = roundPos(wire.start.0, wire.start.1)
            let e = roundPos(wire.end.0, wire.end.1)
            groups[uf.find(s), default: []].insert(s)
            groups[uf.find(e), default: []].insert(e)
        }

        // Map labels to groups
        var groupLabels: [PositionKey: [String]] = [:]
        for label in labels {
            let key = roundPos(label.position.0, label.position.1)
            let root = uf.find(key)
            groupLabels[root, default: []].append(label.name)
        }

        // Assign net names to pins
        var pinNets: PinNets = [:]
        var anonymousCounter = 0

        for pin in pins {
            let key = roundPos(pin.position.0, pin.position.1)
            let root = uf.find(key)

            // Check if pin connects to anything
            let group = groups[root] ?? []
            if group.count <= 1 {
                // Pin is alone — not connected to any wire
                continue
            }

            // Get net name from labels in this group
            let names = groupLabels[root] ?? []
            let netName: String
            if let first = names.first {
                netName = first
            } else {
                anonymousCounter += 1
                netName = "Net_\(anonymousCounter)"
            }

            pinNets["\(pin.ref).\(pin.number)"] = netName
        }

        return pinNets
    }
}
