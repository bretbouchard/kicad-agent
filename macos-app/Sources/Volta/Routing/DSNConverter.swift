//
//  DSNConverter.swift
//  Volta
//
//  Phase 253 Task 2 — Specctra DSN Parser (tokenizer + summary extractor)
//
//  Minimal Specctra DSN parser. Two responsibilities:
//    1. Tokenization primitives used by the full DSN round-trip pipeline
//       (tokenize, findSection, validateBalance). These are the single
//       source of tokenization truth — SpecctraDSNReader, SpecctraDSNWriter,
//       and SegmentSplicer all share them.
//    2. RoutingMetrics-level summary extraction (wires, vias, unrouted nets,
//       layers, parser identity, resolution) for Freerouting's input/output
//       DSN files.
//
//  Format primer: Specctra DSN is S-expression based. Example minimal file:
//
//      (pcb "my_board"
//        (parser (host_cad "KiCad") (host_version "9.0"))
//        (resolution mm 1000000)
//        (structure (layer F.Cu (type signal)))
//        (network
//          (net "GND"
//            (wire (path GND 0 0 10 0) (type route))
//            (via GND 5 5)
//          )
//        )
//        (wiring (wires_failed (net "NET_X")))
//      )
//
//  ponytail: hand-rolled tokenizer. Writing a full S-expression parser
//  would balloon the file; the partial scan for `(section_name ...)` is
//  enough for the fields we need and keeps the module under 200 LOC.
//

import Foundation
import VoltaPCBCore

// MARK: - DSNSummary

/// Lightweight summary of a Specctra DSN file. Captures only the fields
/// RoutingMetrics needs (wire/via counts, unrouted nets) plus provenance
/// (parser host + version) and structural facts (layers, units per mm).
public struct DSNSummary: Sendable, Equatable {
    public let parser: String                       // "KiCad 9.0"
    public let unitsPerMM: Int                      // resolution scaling
    public let layers: [String]                     // ["F.Cu", "B.Cu", ...]
    public let netCount: Int
    public let wireCount: Int
    public let viaCount: Int
    public let unroutedNets: [String]

    public init(
        parser: String,
        unitsPerMM: Int,
        layers: [String],
        netCount: Int,
        wireCount: Int,
        viaCount: Int,
        unroutedNets: [String]
    ) {
        self.parser = parser
        self.unitsPerMM = unitsPerMM
        self.layers = layers
        self.netCount = netCount
        self.wireCount = wireCount
        self.viaCount = viaCount
        self.unroutedNets = unroutedNets
    }
}

// MARK: - DSNError

/// Errors raised by DSNConverter. Distinguishes syntactic issues
/// (missing root, unbalanced parens) from file IO problems.
public enum DSNError: Error, LocalizedError, Equatable {
    case empty
    case missingRoot
    case unbalancedParentheses(line: Int)
    case fileReadFailed(path: String, underlying: String)
    case invalidResolution

    public var errorDescription: String? {
        switch self {
        case .empty:
            return "DSN file is empty"
        case .missingRoot:
            return "DSN file is missing the required (pcb ...) root section"
        case .unbalancedParentheses(let line):
            return "DSN file has unbalanced parentheses near line \(line)"
        case .fileReadFailed(let path, let underlying):
            return "Could not read DSN file at \(path): \(underlying)"
        case .invalidResolution:
            return "DSN file has an invalid (resolution ...) value"
        }
    }
}

// MARK: - DSNConverter

/// Specctra DSN parser. Extracts RoutingMetrics-relevant fields from
/// Freerouting-compatible DSN files.
public enum DSNConverter {

    /// Parse a DSN string into a summary. Throws DSNError on syntactic
    /// failures (missing root, unbalanced parens, empty input).
    public static func parseSummary(_ text: String) throws -> DSNSummary {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw DSNError.empty }
        try validateBalance(trimmed)

        let tokens = tokenize(trimmed)
        guard let pcbRange = findSection(named: "pcb", in: tokens) else {
            throw DSNError.missingRoot
        }

        let parser = extractHostCad(in: tokens[pcbRange]) ?? "unknown"
        let unitsPerMM = extractResolution(in: tokens[pcbRange]) ?? 1_000_000
        let layers = extractLayers(in: tokens[pcbRange])
        let (netCount, wireCount, viaCount) = extractNetworkCounts(in: tokens[pcbRange])
        let unroutedNets = extractUnroutedNets(in: tokens[pcbRange])

        return DSNSummary(
            parser: parser,
            unitsPerMM: unitsPerMM,
            layers: layers,
            netCount: netCount,
            wireCount: wireCount,
            viaCount: viaCount,
            unroutedNets: unroutedNets
        )
    }

    /// Parse a DSN file from disk.
    public static func parseSummary(at url: URL) throws -> DSNSummary {
        do {
            let text = try String(contentsOf: url, encoding: .utf8)
            return try parseSummary(text)
        } catch let err as DSNError {
            throw err
        } catch {
            throw DSNError.fileReadFailed(path: url.path, underlying: error.localizedDescription)
        }
    }

    // MARK: - Tokenization

    /// Lightweight tokenizer. Returns the input split into raw s-expression
    /// tokens (parens + bare words + quoted strings).
    static func tokenize(_ text: String) -> [String] {
        var tokens: [String] = []
        var current = ""
        var inQuote = false
        let characters = Array(text)

        for index in characters.indices {
            let char = characters[index]
            let nextChar = index < characters.index(before: characters.endIndex)
                ? characters[characters.index(after: index)]
                : nil

            if char == "\"" {
                // Specctra declares its quote delimiter as `(string_quote ")`.
                // That standalone quote is a bare token, not the start of a
                // quoted string. All other quotes retain normal toggle rules.
                let isStringQuoteDirective = !inQuote && current.isEmpty && nextChar == ")"
                if !isStringQuoteDirective {
                    inQuote.toggle()
                }
                current.append(char)
            } else if !inQuote && (char == "(" || char == ")") {
                if !current.isEmpty {
                    tokens.append(current)
                    current = ""
                }
                tokens.append(String(char))
            } else if !inQuote && char.isWhitespace {
                if !current.isEmpty {
                    tokens.append(current)
                    current = ""
                }
            } else {
                current.append(char)
            }
        }
        if !current.isEmpty { tokens.append(current) }
        return tokens
    }

    /// Find the range of tokens covering a top-level `(name ...)`.
    /// Returns nil if no top-level section with that name exists.
    static func findSection(named name: String, in tokens: [String]) -> Range<Int>? {
        var depth = 0
        var startIndex: Int?
        for i in 0..<tokens.count {
            if tokens[i] == "(" {
                if depth == 0, i + 1 < tokens.count, tokens[i + 1] == name {
                    depth = 1
                    startIndex = i
                } else if startIndex != nil {
                    depth += 1
                }
            } else if tokens[i] == ")" {
                if startIndex != nil {
                    depth -= 1
                    if depth == 0 {
                        return startIndex!..<i
                    }
                }
            }
        }
        return nil
    }

    /// Verify that parens balance. Throws .unbalancedParentheses with the
    /// line number of the offending open paren if mismatched.
    static func validateBalance(_ text: String) throws {
        var depth = 0
        var line = 1
        var openLine = 0
        var inQuote = false
        let characters = Array(text)

        for index in characters.indices {
            let char = characters[index]
            let nextChar = index < characters.index(before: characters.endIndex)
                ? characters[characters.index(after: index)]
                : nil

            if char == "\n" { line += 1 }
            if char == "\"" {
                // Match tokenize(_:): `(string_quote ")` contains one bare
                // quote token and must not put the rest of the file in quote mode.
                if !inQuote && nextChar == ")" { continue }
                inQuote.toggle()
                continue
            }
            if inQuote { continue }
            if char == "(" {
                if depth == 0 { openLine = line }
                depth += 1
            } else if char == ")" {
                depth -= 1
                if depth < 0 {
                    throw DSNError.unbalancedParentheses(line: line)
                }
            }
        }
        if depth != 0 {
            throw DSNError.unbalancedParentheses(line: openLine)
        }
    }

    // MARK: - Field extractors

    /// Pull "(host_cad \"...\")" and "(host_version \"...\")" from the parser
    /// section and return them joined.
    static func extractHostCad(in tokens: ArraySlice<String>) -> String? {
        guard let parserRange = findSection(named: "parser", in: Array(tokens)) else {
            return nil
        }
        // Re-slice with absolute indices, then convert to a flat Array.
        // Array(tokens)[parserRange] preserves the lower bound as startIndex,
        // so iterating with `0..<count` and subscripting [i] would crash.
        // Array(...) flattens to startIndex=0 — safe for 0-based indexing.
        let parserTokens = Array(Array(tokens)[parserRange])
        var host = "unknown"
        var version = ""
        for i in 0..<parserTokens.count {
            if parserTokens[i] == "host_cad", i + 1 < parserTokens.count {
                host = stripQuotesAndUnescape(parserTokens[i + 1])
            } else if parserTokens[i] == "host_version", i + 1 < parserTokens.count {
                version = stripQuotesAndUnescape(parserTokens[i + 1])
            }
        }
        return version.isEmpty ? host : "\(host) \(version)"
    }

    /// Pull "(resolution mm <int>)" → units-per-mm scaling.
    static func extractResolution(in tokens: ArraySlice<String>) -> Int? {
        guard let r = findSection(named: "resolution", in: Array(tokens)) else {
            return nil
        }
        // Flatten to Array so the count-based subscript at the bottom is safe.
        let toks = Array(Array(tokens)[r])
        // (resolution mm <number>)
        if toks.count >= 4, let n = Int(toks[toks.count - 2]) {
            return n
        }
        return nil
    }

    /// Pull layer names from the (structure ...) section.
    static func extractLayers(in tokens: ArraySlice<String>) -> [String] {
        guard let r = findSection(named: "structure", in: Array(tokens)) else {
            return []
        }
        let toks = Array(Array(tokens)[r])
        var layers: [String] = []
        var i = 0
        while i < toks.count - 1 {
            if toks[i] == "(", toks[i + 1] == "layer", i + 2 < toks.count {
                layers.append(stripQuotesAndUnescape(toks[i + 2]))
            }
            i += 1
        }
        return layers
    }

    /// Count (net ...) entries and aggregate wires + vias from the network section.
    static func extractNetworkCounts(in tokens: ArraySlice<String>) -> (nets: Int, wires: Int, vias: Int) {
        guard let r = findSection(named: "network", in: Array(tokens)) else {
            return (0, 0, 0)
        }
        let toks = Array(Array(tokens)[r])
        var nets = 0
        var wires = 0
        var vias = 0
        var i = 0
        while i < toks.count {
            if toks[i] == "(", i + 1 < toks.count {
                if toks[i + 1] == "net" {
                    nets += 1
                } else if toks[i + 1] == "wire" {
                    wires += 1
                } else if toks[i + 1] == "via" {
                    vias += 1
                }
            }
            i += 1
        }
        return (nets, wires, vias)
    }

    /// Pull unrouted net names from (wiring (wires_failed (net "X") (net "Y") ...)).
    static func extractUnroutedNets(in tokens: ArraySlice<String>) -> [String] {
        guard let wiringRange = findSection(named: "wiring", in: Array(tokens)) else {
            return []
        }
        let toks = Array(Array(tokens)[wiringRange])
        guard let failedRange = findSection(named: "wires_failed", in: toks) else {
            return []
        }
        let failed = Array(toks[failedRange])
        var nets: [String] = []
        var i = 0
        while i < failed.count - 1 {
            if failed[i] == "(", failed[i + 1] == "net", i + 2 < failed.count {
                nets.append(stripQuotesAndUnescape(failed[i + 2]))
            }
            i += 1
        }
        return nets
    }

    // MARK: - Helpers

    /// Strip surrounding double quotes from a token, if present.
    ///
    /// Deprecated: use `stripQuotesAndUnescape(_:)` which also unescapes
    /// the Specctra DSN doubled-quote convention (`""` → `"`). Kept for
    /// one release for source compatibility with callers that don't yet
    /// deal with net names or pin names containing literal quotes.
    @available(*, deprecated, message: "Use stripQuotesAndUnescape() for Specctra DSN doubled-quote handling")
    static func stripQuotes(_ token: String) -> String {
        guard token.count >= 2, token.first == "\"", token.last == "\"" else {
            return token
        }
        return String(token.dropFirst().dropLast())
    }

    /// Strip surrounding double quotes AND unescape Specctra DSN doubled-quote
    /// sequences (`""` → `"`) per Council L-05 / WR-03. Used by
    /// SpecctraDSNReader for net name parsing and pin name extraction where
    /// a literal `"` in the source name has been encoded as `""`.
    ///
    /// Examples:
    ///   - `"plain"` → `plain`
    ///   - `"a""b"` → `a"b`
    ///   - `plain` → `plain` (no-op when no surrounding quotes)
    static func stripQuotesAndUnescape(_ token: String) -> String {
        // Step 1: strip outer quotes if both present.
        let stripped: String
        if token.count >= 2, token.first == "\"", token.last == "\"" {
            stripped = String(token.dropFirst().dropLast())
        } else {
            stripped = token
        }
        // Step 2: Specctra DSN doubled-quote escaping — `""` → `"`.
        // The escape sequence is two consecutive `"` characters inside the
        // already-unquoted string. We replace literal `""` with `"`.
        return stripped.replacingOccurrences(of: "\"\"", with: "\"")
    }
}
