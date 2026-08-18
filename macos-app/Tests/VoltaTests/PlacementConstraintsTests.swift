//
//  PlacementConstraintsTests.swift
//  VoltaTests
//
//  volta-24 follow-on: Swift mirror of the Python constraint contract —
//  Codable round-trip (flat LLM/ops JSON), validation, penalty, gate.
//

import Testing
import Foundation
@testable import Volta

@Suite("Placement Constraints", .serialized)
struct PlacementConstraintsTests {

    // MARK: - Codable

    @Test("Decodes flat LLM/ops JSON with snake_case keys")
    func decodesFlatJSON() throws {
        let json = """
        {
          "rule_type": "avoid",
          "refs": ["U3"],
          "refs_b": ["U1"],
          "mm": 25.0,
          "source": "explicit",
          "rationale": "EMI separation"
        }
        """.data(using: .utf8)!
        let rule = try JSONDecoder().decode(PlacementConstraint.self, from: json)
        #expect(rule.ruleType == .avoid)
        #expect(rule.refsB == ["U1"])
        #expect(rule.mm == 25.0)
        #expect(rule.rationale == "EMI separation")
        #expect(rule.source == .explicit)
    }

    @Test("Round-trips through encode/decode")
    func roundTrip() throws {
        let rule = PlacementConstraint(
            ruleType: .edgeAffinity, refs: ["J1"], mm: 4.0, edge: .bottom,
            rationale: "connector on the bottom edge"
        )
        let data = try JSONEncoder().encode(rule)
        let back = try JSONDecoder().decode(PlacementConstraint.self, from: data)
        #expect(back == rule)
    }

    // MARK: - Validation

    @Test("avoid without refs_b is rejected")
    func avoidRequiresRefsB() {
        let rule = PlacementConstraint(ruleType: .avoid, refs: ["A"], mm: 10.0)
        #expect(throws: PlacementConstraintError.self) {
            _ = try rule.validated()
        }
    }

    @Test("non-positive mm is rejected")
    func positiveMM() {
        let rule = PlacementConstraint(
            ruleType: .approach, refs: ["C4"], refsB: ["U3"], mm: -1.0
        )
        #expect(throws: PlacementConstraintError.self) {
            _ = try rule.validated()
        }
    }

    @Test("region with inverted bbox is rejected")
    func regionBBox() {
        let rule = PlacementConstraint(
            ruleType: .region, refs: ["U2"], region: [50, 40, 0, 0]
        )
        #expect(throws: PlacementConstraintError.self) {
            _ = try rule.validated()
        }
    }

    @Test("well-formed rules validate")
    func wellFormed() throws {
        let rule = PlacementConstraint(
            ruleType: .orientation, refs: ["LED1"], rotation: 90.0
        )
        #expect(try rule.validated() == rule)
    }

    // MARK: - Penalty + gate (parity with Python tests)

    @Test("avoid satisfied is zero penalty; violated is squared shortfall")
    func avoidPenalty() {
        let rule = PlacementConstraint(
            ruleType: .avoid, refs: ["U3"], refsB: ["U1"], mm: 25.0
        )
        let far: PlacementPositions = [
            "U1": (10, 10, 0), "U3": (80, 60, 0),
        ]
        let near: PlacementPositions = [
            "U1": (10, 10, 0), "U3": (12, 10, 0),
        ]
        #expect(PlacementConstraints.penalty([rule], positions: far, boardWidth: 100, boardHeight: 80) == 0)
        let p = PlacementConstraints.penalty([rule], positions: near, boardWidth: 100, boardHeight: 80)
        #expect(abs(p - (25.0 - 2.0) * (25.0 - 2.0)) < 1e-9)
    }

    @Test("approach penalizes only when too far")
    func approachPenalty() {
        let rule = PlacementConstraint(
            ruleType: .approach, refs: ["C4"], refsB: ["U3"], mm: 5.0
        )
        let far: PlacementPositions = ["C4": (10, 10, 0), "U3": (80, 60, 0)]
        let near: PlacementPositions = ["C4": (40, 60, 0), "U3": (42, 60, 0)]
        #expect(PlacementConstraints.penalty([rule], positions: far, boardWidth: 100, boardHeight: 80) > 0)
        #expect(PlacementConstraints.penalty([rule], positions: near, boardWidth: 100, boardHeight: 80) == 0)
    }

    @Test("gate reports violation with rule id and distances")
    func gateReports() {
        let rule = PlacementConstraint(
            ruleId: "keep-apart",
            ruleType: .avoid, refs: ["R1"], refsB: ["R2"], mm: 30.0
        )
        let pos: PlacementPositions = ["R1": (10, 10, 0), "R2": (12, 10, 0)]
        let violations = PlacementConstraints.validate(
            [rule], positions: pos, boardWidth: 100, boardHeight: 80
        )
        #expect(violations.count == 1)
        #expect(violations[0].ruleId == "keep-apart")
        #expect(violations[0].ref == "R1")
        #expect(violations[0].actualMM! < 30.0)
    }

    @Test("edge affinity gate")
    func edgeGate() {
        let rule = PlacementConstraint(
            ruleType: .edgeAffinity, refs: ["J1"], mm: 5.0, edge: .bottom
        )
        let mid: PlacementPositions = ["J1": (50, 40, 0)]
        let edge: PlacementPositions = ["J1": (50, 3, 0)]
        #expect(PlacementConstraints.validate([rule], positions: mid, boardWidth: 100, boardHeight: 80).count == 1)
        #expect(PlacementConstraints.validate([rule], positions: edge, boardWidth: 100, boardHeight: 80).isEmpty)
    }

    @Test("missing refs never crash")
    func missingRefs() {
        let rule = PlacementConstraint(
            ruleType: .avoid, refs: ["U3"], refsB: ["U1"], mm: 25.0
        )
        #expect(PlacementConstraints.penalty([rule], positions: ["U1": (1, 1, 0)], boardWidth: 100, boardHeight: 80) == 0)
        #expect(PlacementConstraints.validate([rule], positions: [:], boardWidth: 100, boardHeight: 80).isEmpty)
    }
}

// MARK: - View instantiation

extension PlacementConstraintsTests {
    @Test("PlacementConstraintsView instantiates with rules")
    @MainActor
    func viewInstantiates() {
        let rules: [PlacementConstraint] = [
            PlacementConstraint(
                ruleType: .avoid, refs: ["U3"], refsB: ["U1"], mm: 25.0,
                rationale: "EMI separation"
            ),
            PlacementConstraint(
                ruleType: .edgeAffinity, refs: ["J1"], mm: 4.0, edge: .bottom,
                rationale: "connector access"
            ),
        ]
        let view = PlacementConstraintsView(constraints: .constant(rules))
        #expect(view != nil)
    }
}
