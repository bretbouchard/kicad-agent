import Foundation
import GSAModeledWorld

/// Lossless `Codable` ↔ `WorldValue` conversion over JSON, so Volta's
/// KiCad-model documents (all `Codable`) migrate into the Modeled World
/// without a parallel schema definition. The encoded payload is the
/// canonical document; the world stores it verbatim.
///
/// Same proven shape as WhiteRoomGSA's codec (M2.1) — shared verbatim
/// because it is domain-agnostic.
public enum WorldValueCodec {
    public enum CodecError: Error, Equatable {
        case notJSONCompatible(String)
    }

    /// Encodes any `Encodable` domain value into a JSON-shaped `WorldValue`.
    public static func encode<T: Encodable>(_ value: T) throws -> WorldValue {
        let data = try JSONEncoder().encode(value)
        let json = try JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed])
        return try fromJSON(json)
    }

    /// Decodes a `WorldValue` produced by `encode(_:)` back into the domain type.
    public static func decode<T: Decodable>(_ type: T.Type, from value: WorldValue) throws -> T {
        let json = try toJSON(value)
        let data = try JSONSerialization.data(withJSONObject: json, options: [.fragmentsAllowed])
        return try JSONDecoder().decode(type, from: data)
    }

    /// Bridges a `JSONSerialization` object graph into a `WorldValue` tree.
    static func fromJSON(_ json: Any) throws -> WorldValue {
        switch json {
        case let number as NSNumber:
            // JSONSerialization boxes booleans as NSNumber; distinguish via
            // the CoreFoundation boolean type so true/false survive as .bool.
            if CFGetTypeID(number) == CFBooleanGetTypeID() {
                return .bool(number.boolValue)
            }
            let double = number.doubleValue
            if double.rounded() == double, abs(double) < 9_007_199_254_740_992 {
                return .int(Int(double))
            }
            return .double(double)
        case let string as String:
            return .string(string)
        case let array as [Any]:
            return .array(try array.map(fromJSON))
        case let object as [String: Any]:
            var fields: [String: WorldValue] = [:]
            fields.reserveCapacity(object.count)
            for (key, value) in object {
                fields[key] = try fromJSON(value)
            }
            return .object(fields)
        case is NSNull:
            return .null
        default:
            throw CodecError.notJSONCompatible(String(describing: json))
        }
    }

    /// Mirrors `fromJSON(_:)`: a `WorldValue` tree back into Foundation objects.
    static func toJSON(_ value: WorldValue) throws -> Any {
        switch value {
        case .null: return NSNull()
        case .bool(let bool): return bool
        case .int(let int): return int
        case .double(let double): return double
        case .string(let string): return string
        case .array(let values): return try values.map(toJSON)
        case .object(let fields):
            var object: [String: Any] = [:]
            object.reserveCapacity(fields.count)
            for (key, value) in fields {
                object[key] = try toJSON(value)
            }
            return object
        }
    }
}
