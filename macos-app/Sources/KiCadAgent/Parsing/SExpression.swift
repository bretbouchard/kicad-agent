//
//  SExpression.swift
//  Phase 221 — Swift S-Expression Parser
//
//  Parses KiCad's S-expression file format. Foundation for daemon elimination.
//  ponytail: recursive descent, ~150 LOC. No external deps.
//

import Foundation

indirect enum SExpr: Equatable, CustomStringConvertible, Sendable {
    case atom(String)
    case string(String)
    case list(String, [SExpr])

    var description: String {
        switch self {
        case .atom(let s): return s
        case .string(let s): return "\"\(s)\""
        case .list(let head, let children):
            return "(\(head) \(children.map(\.description).joined(separator: " ")))"
        }
    }

    var head: String? {
        if case .list(let h, _) = self { return h }
        return nil
    }

    var children: [SExpr] {
        if case .list(_, let c) = self { return c }
        return []
    }

    var stringValue: String? {
        switch self {
        case .string(let s): return s
        case .atom(let s): return s
        default: return nil
        }
    }

    var doubleValue: Double? {
        if case .atom(let s) = self { return Double(s) }
        return nil
    }

    func find(_ symbol: String) -> SExpr? {
        for child in children {
            if child.head == symbol { return child }
        }
        return nil
    }

    func findAll(_ symbol: String) -> [SExpr] {
        children.filter { $0.head == symbol }
    }

    func childString(_ index: Int) -> String? {
        guard index < children.count else { return nil }
        return children[index].stringValue
    }

    func childDouble(_ index: Int) -> Double? {
        guard index < children.count else { return nil }
        return children[index].doubleValue
    }

    static func parse(fileURL: URL) throws -> SExpr {
        let content = try String(contentsOf: fileURL, encoding: .utf8)
        return try parse(content)
    }

    static func parse(_ text: String) throws -> SExpr {
        var parser = SExprParser(Array(text))
        parser.skipWhitespace()
        guard parser.peek() == "(" else { throw SExprError.expectedOpenParen }
        return try parser.parseList()
    }
}

struct SExprParser {
    private let src: [Character]
    private(set) var pos: Int = 0

    init(_ src: [Character]) { self.src = src }

    mutating func parseList() throws -> SExpr {
        skipWhitespace()
        guard peek() == "(" else { throw SExprError.expectedOpenParen }
        advance()

        skipWhitespace()
        let head = parseToken()
        var children: [SExpr] = []

        while pos < src.count {
            skipWhitespace()
            guard pos < src.count else { throw SExprError.unexpectedEOF }
            let ch = peek()!
            if ch == ")" { advance(); break }
            if ch == "(" { children.append(try parseList()) }
            else if ch == "\"" { children.append(.string(parseQuoted())) }
            else { children.append(.atom(parseToken())) }
        }
        return .list(head, children)
    }

    private mutating func parseToken() -> String {
        var s = ""
        while pos < src.count {
            let c = src[pos]
            if c == " " || c == "\t" || c == "\n" || c == "\r" || c == "(" || c == ")" { break }
            s.append(c); advance()
        }
        return s
    }

    private mutating func parseQuoted() -> String {
        advance()
        var s = ""
        while pos < src.count {
            let c = src[pos]
            if c == "\\" && pos + 1 < src.count {
                advance(); s.append(src[pos]); advance()
            } else if c == "\"" { advance(); break }
            else { s.append(c); advance() }
        }
        return s
    }

    mutating func skipWhitespace() {
        while pos < src.count {
            let c = src[pos]
            if c == " " || c == "\t" || c == "\n" || c == "\r" { advance() }
            else { break }
        }
    }

    func peek() -> Character? { pos < src.count ? src[pos] : nil }
    mutating func advance() { pos += 1 }
}

enum SExprError: Error {
    case expectedOpenParen, unexpectedEOF
}
