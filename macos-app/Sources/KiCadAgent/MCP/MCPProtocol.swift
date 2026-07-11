#if os(macOS)
//
//  MCPProtocol.swift
//  KiCadAgent
//
//  Phase 167 — Stdio MCP Client
//
//  JSON-RPC 2.0 protocol envelopes for the Model Context Protocol transport
//  that lives between the Swift app and the bundled Python daemon.
//
//  Wire format (line-delimited over stdio, UTF-8, '\n' separator):
//
//      Request:        {"jsonrpc":"2.0","id":42,"method":"kicad.add_component","params":{...}}
//      Response:       {"jsonrpc":"2.0","id":42,"result":{...}}
//      Error:          {"jsonrpc":"2.0","id":42,"error":{"code":-32601,"message":"..."}}
//      Notification:   {"jsonrpc":"2.0","method":"heartbeat","params":{...}}
//                      (no id — fire-and-forget daemon → app)
//
//  Method namespacing (per Phase 167 plan):
//      kicad.<op_name>     — kicad-agent operations (151 registered ops)
//      tools/list          — MCP lifecycle (returns all kicad.* as MCP tools)
//      tools/call          — MCP lifecycle (dispatches a kicad.* op)
//      initialize          — MCP handshake (capability exchange)
//      initialized         — MCP handshake (client → server notification)
//      ping / list_operations / health / shutdown — pre-MCP RPCs (still supported)
//      heartbeat           — daemon → app liveness notification (no id)
//
//  Error codes (JSON-RPC 2.0 reserved table, mirror of protocol.py):
//      -32700  PARSE_ERROR
//      -32600  INVALID_REQUEST
//      -32601  METHOD_NOT_FOUND
//      -32602  INVALID_PARAMS
//      -32603  INTERNAL_ERROR
//
//  Spec: https://www.jsonrpc.org/specification
//  MCP:  https://modelcontextprotocol.io/specification
//

import Foundation

// MARK: - JSON-RPC error codes (spec-defined, mirror protocol.py)

enum MCPErrorCode {
    static let parseError: Int = -32700
    static let invalidRequest: Int = -32600
    static let methodNotFound: Int = -32601
    static let invalidParams: Int = -32602
    static let internalError: Int = -32603
}

// MARK: - MCPError

/// Errors raised by the MCP client layer.
///
/// `MCPError` is the single error type surfaced to callers of `MCPClient`.
/// It wraps both transport-level failures (broken pipe, timeout) and
/// protocol-level failures (daemon-side JSON-RPC errors).
enum MCPError: LocalizedError, Equatable {
    case transport(message: String)
    case daemonError(code: Int, message: String)
    case timeout
    case malformedResponse(payload: String)
    case decodingFailed(message: String)
    case notConnected

    public var errorDescription: String? {
        switch self {
        case .transport(let message):
            return "MCP transport error: \(message)"
        case .daemonError(let code, let message):
            return "Daemon error [\(code)]: \(message)"
        case .timeout:
            return "MCP request timed out (no response within watchdog window)."
        case .malformedResponse(let payload):
            return "Malformed MCP response: \(payload.prefix(200))"
        case .decodingFailed(let message):
            return "Failed to decode MCP response: \(message)"
        case .notConnected:
            return "MCP client not connected to daemon."
        }
    }
}

// MARK: - JSON-RPC 2.0 envelopes (Codable)

/// JSON-RPC 2.0 envelope — covers request, response, error, notification.
///
/// Codable parsing strategy: every field is optional because a single
/// envelope type cleanly handles all four wire shapes (request, response,
/// error, notification). The consumer inspects `id`, `method`, `result`,
/// and `error` to discriminate.
struct JSONRPCEnvelope: Codable, Equatable, Sendable {
    public var jsonrpc: String = "2.0"
    /// JSON-RPC id. Nil for notifications, present for requests/responses.
    /// Per MCP spec, ids may be Int or String. Swift's JSONDecoder accepts
    /// either when the field is typed as `AnyCodable`; we keep it permissive.
    public var id: AnyCodable?
    public var method: String?
    public var params: AnyCodable?
    public var result: AnyCodable?
    public var error: JSONRPCError?

    public init(
        jsonrpc: String = "2.0",
        id: AnyCodable? = nil,
        method: String? = nil,
        params: AnyCodable? = nil,
        result: AnyCodable? = nil,
        error: JSONRPCError? = nil
    ) {
        self.jsonrpc = jsonrpc
        self.id = id
        self.method = method
        self.params = params
        self.result = result
        self.error = error
    }

    /// Discriminator: is this a response (has id + result/error, no method)?
    public var isResponse: Bool {
        id != nil && method == nil && (result != nil || error != nil)
    }

    /// Discriminator: is this a request (has id + method, no result/error)?
    public var isRequest: Bool {
        id != nil && method != nil && result == nil && error == nil
    }

    /// Discriminator: is this a notification (no id, has method)?
    public var isNotification: Bool {
        id == nil && method != nil
    }

    /// Discriminator: is this an error response?
    public var isError: Bool {
        error != nil
    }
}

/// JSON-RPC 2.0 error object (lives inside the envelope's `error` field).
struct JSONRPCError: Codable, Equatable, Sendable {
    public var code: Int
    public var message: String
    public var data: AnyCodable?

    public init(code: Int, message: String, data: AnyCodable? = nil) {
        self.code = code
        self.message = message
        self.data = data
    }
}

// MARK: - AnyCodable (type-erased JSON value)

/// Type-erased Codable JSON value. Used because JSON-RPC params and results
/// are heterogeneous — `Any` cannot be Codable, and writing a specific
/// struct for every method defeats the purpose of the generic `call<T>`
/// client API.
///
/// `AnyCodable` round-trips through JSONSerialization intact, supporting
/// every JSON type: null, bool, number, string, array, object. The stored
/// value is a value-type (`[String: Any]`, `String`, `NSNumber`, `NSNull`,
/// `[Any]`) — safe to mark `@unchecked Sendable`.
struct AnyCodable: Codable, Equatable, @unchecked Sendable {
    public let value: Any

    public init(_ value: Any) {
        self.value = value
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self.value = NSNull()
        } else if let bool = try? container.decode(Bool.self) {
            self.value = NSNumber(value: bool)
        } else if let number = try? container.decode(Double.self) {
            self.value = NSNumber(value: number)
        } else if let string = try? container.decode(String.self) {
            self.value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            self.value = array.map { $0.value }
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            self.value = dict.mapValues { $0.value }
        } else {
            self.value = NSNull()
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try AnyCodable.encodeValue(value, into: &container)
    }

    private static func encodeValue(_ value: Any, into container: inout SingleValueEncodingContainer) throws {
        switch value {
        case is NSNull:
            try container.encodeNil()
        case let bool as Bool:
            try container.encode(bool)
        case let number as NSNumber:
            // Preserve int vs double on encode by inspecting objCType.
            // "q" = long long (int64), "d" = double, "f" = float.
            // Anything else falls back to double — JSON-safe either way.
            let typeChar = String(cString: number.objCType)
            if typeChar == "q" || typeChar == "i" || typeChar == "l" || typeChar == "s" {
                try container.encode(number.intValue)
            } else {
                try container.encode(number.doubleValue)
            }
        case let string as String:
            try container.encode(string)
        case let array as [Any]:
            try container.encode(array.map { AnyCodable($0) })
        case let dict as [String: Any]:
            try container.encode(dict.mapValues { AnyCodable($0) })
        default:
            try container.encodeNil()
        }
    }

    public func asDictionary() -> [String: Any]? {
        value as? [String: Any]
    }

    public func asArray() -> [Any]? {
        value as? [Any]
    }

    static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        // Compare via JSON round-trip — most reliable Any equality check.
        let l = try? JSONSerialization.data(withJSONObject: [lhs.value])
        let r = try? JSONSerialization.data(withJSONObject: [rhs.value])
        return l == r
    }
}

// MARK: - Envelope construction helpers

extension JSONRPCEnvelope {
    /// Build a request envelope with an incrementing Int id.
    static func request(id: Int, method: String, params: [String: Any] = [:]) -> JSONRPCEnvelope {
        var env = JSONRPCEnvelope(
            id: AnyCodable(id),
            method: method
        )
        if !params.isEmpty {
            env.params = AnyCodable(params)
        }
        return env
    }

    /// Build a notification envelope (no id).
    static func notification(method: String, params: [String: Any] = [:]) -> JSONRPCEnvelope {
        var env = JSONRPCEnvelope(method: method)
        if !params.isEmpty {
            env.params = AnyCodable(params)
        }
        return env
    }

    /// Serialize to a line-delimited JSON string for stdin write.
    public func toJSONLine() throws -> String {
        let data = try JSONEncoder().encode(self)
        guard var line = String(data: data, encoding: .utf8) else {
            throw MCPError.transport(message: "failed to encode envelope as utf-8")
        }
        line += "\n"
        return line
    }
}

// MARK: - NSNumber int/double discriminator
//
// The objCType-based distinction in encodeValue is best-effort. If a
// payload contains a non-int/non-double NSNumber, we fall back to double
// encoding — JSON-safe either way. Bool is matched first (before NSNumber)
// because Bool is bridged to NSNumber by the ObjC runtime.

#endif // os(macOS)
