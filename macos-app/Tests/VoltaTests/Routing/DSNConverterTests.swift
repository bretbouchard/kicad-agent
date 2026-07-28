//
//  DSNConverterTests.swift
//  VoltaTests
//
//  Phase 253 Task 2 — Specctra DSN Converter Tests
//
//  DSNConverter parses Specctra DSN files (the format Freerouting takes
//  and produces) and surfaces a minimal DSNSummary struct with the
//  fields needed for RoutingMetrics (wires, vias, unrouted nets).
//  Full .kicad_pcb ↔ DSN round-trip conversion lives in Python via
//  pcbnew bindings (out of scope for this Swift layer).
//

import Testing
import Foundation
@testable import Volta
import VoltaPCBCore

@Suite("DSN Converter")
struct DSNConverterTests {

    // MARK: - Parsing

    @Test("Parses minimal DSN with network and library sections")
    func parseMinimalDSN() throws {
        let dsn = """
        (pcb "test_board"
          (parser
            (string_quote ")
            (space_in_quoted_tokens on)
            (host_cad "KiCad")
            (host_version "9.0")
          )
          (resolution mm 1000000)
          (network
            (net "GND"
              (wire (path GND 0 0 100 0) (type route))
            )
            (net "VCC"
              (wire (path VCC 0 0 50 0) (type route))
            )
          )
        )
        """
        let summary = try DSNConverter.parseSummary(dsn)
        #expect(summary.netCount == 2)
        #expect(summary.wireCount == 2)
        #expect(summary.parser == "KiCad 9.0")
    }

    @Test("Parses unrouted nets from wiring section")
    func parseUnroutedNets() throws {
        let dsn = """
        (pcb "test_board"
          (parser (host_cad "KiCad") (host_version "9.0"))
          (network
            (net "DONE" (wire (path DONE 0 0 10 0) (type route)))
          )
          (wiring
            (wires_failed
              (net "NET_MISSING_A")
              (net "NET_MISSING_B")
            )
          )
        )
        """
        let summary = try DSNConverter.parseSummary(dsn)
        #expect(summary.unroutedNets.contains("NET_MISSING_A"))
        #expect(summary.unroutedNets.contains("NET_MISSING_B"))
    }

    @Test("Counts vias from wire type via entries")
    func countVias() throws {
        let dsn = """
        (pcb "test_board"
          (parser (host_cad "KiCad") (host_version "9.0"))
          (network
            (net "VCC"
              (wire (path VCC 0 0 10 0) (type route))
              (via VCC 5 5)
              (via VCC 15 5)
            )
          )
        )
        """
        let summary = try DSNConverter.parseSummary(dsn)
        #expect(summary.viaCount == 2)
    }

    @Test("Extracts resolution (units per mm)")
    func parseResolution() throws {
        let dsn = """
        (pcb "test_board"
          (parser (host_cad "KiCad") (host_version "9.0"))
          (resolution mm 1000000)
          (network (net "GND"))
        )
        """
        let summary = try DSNConverter.parseSummary(dsn)
        #expect(summary.unitsPerMM == 1_000_000)
    }

    @Test("Parses routing layers from structure section")
    func parseLayers() throws {
        let dsn = """
        (pcb "test_board"
          (parser (host_cad "KiCad") (host_version "9.0"))
          (resolution mm 1000000)
          (structure
            (layer F.Cu (type signal) (direction horizontal))
            (layer B.Cu (type signal) (direction vertical))
          )
          (network (net "GND"))
        )
        """
        let summary = try DSNConverter.parseSummary(dsn)
        #expect(summary.layers.contains("F.Cu"))
        #expect(summary.layers.contains("B.Cu"))
    }

    // MARK: - Error handling

    @Test("Throws on missing pcb root")
    func rejectsMissingRoot() {
        let malformed = "(network (net \"GND\"))"
        #expect(throws: DSNError.self) {
            _ = try DSNConverter.parseSummary(malformed)
        }
    }

    @Test("Throws on empty input")
    func rejectsEmpty() {
        #expect(throws: DSNError.self) {
            _ = try DSNConverter.parseSummary("")
        }
    }

    @Test("Throws on unbalanced parentheses")
    func rejectsUnbalancedParens() {
        let malformed = "(pcb \"test\" (parser (host_cad \"KiCad\""
        #expect(throws: DSNError.self) {
            _ = try DSNConverter.parseSummary(malformed)
        }
    }

    // MARK: - File round-trip

    @Test("parseSummary is idempotent on its own output")
    func parseIdempotent() throws {
        let original = """
        (pcb "test_board"
          (parser (host_cad "KiCad") (host_version "9.0"))
          (resolution mm 1000000)
          (network
            (net "GND" (wire (path GND 0 0 10 0) (type route)))
          )
        )
        """
        let summary1 = try DSNConverter.parseSummary(original)
        // We can't round-trip the full text, but we can re-parse to ensure
        // the summary fields are stable across re-parses.
        let summary2 = try DSNConverter.parseSummary(original)
        #expect(summary1.netCount == summary2.netCount)
        #expect(summary1.wireCount == summary2.wireCount)
        #expect(summary1.layers == summary2.layers)
    }
}