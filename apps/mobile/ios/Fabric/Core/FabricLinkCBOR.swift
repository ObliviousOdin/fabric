import Foundation

/// The deliberately small CBOR value model used by Fabric Link.
///
/// Security-sensitive records are accepted only when their input bytes are
/// already the unique deterministic encoding of the decoded value. Re-encoding
/// rejects duplicate map keys, indefinite lengths, non-minimal integers and
/// floats, tags, unsupported simple values, and trailing bytes before any
/// protocol field is trusted.
indirect enum FabricLinkCBOR: Equatable {
    case unsigned(UInt64)
    case negative(Int64)
    case bytes(Data)
    case string(String)
    case array([FabricLinkCBOR])
    case map([String: FabricLinkCBOR])
    case bool(Bool)
    case null
    case float(Double)

    static func integer(_ value: Int) -> FabricLinkCBOR {
        value >= 0 ? .unsigned(UInt64(value)) : .negative(Int64(value))
    }

    var mapValue: [String: FabricLinkCBOR]? {
        guard case .map(let value) = self else { return nil }
        return value
    }

    var arrayValue: [FabricLinkCBOR]? {
        guard case .array(let value) = self else { return nil }
        return value
    }

    var dataValue: Data? {
        guard case .bytes(let value) = self else { return nil }
        return value
    }

    var stringValue: String? {
        guard case .string(let value) = self else { return nil }
        return value
    }

    var boolValue: Bool? {
        guard case .bool(let value) = self else { return nil }
        return value
    }

    var intValue: Int? {
        switch self {
        case .unsigned(let value):
            guard value <= UInt64(Int.max) else { return nil }
            return Int(value)
        case .negative(let value):
            guard value >= Int64(Int.min), value <= Int64(Int.max) else { return nil }
            return Int(value)
        default:
            return nil
        }
    }

    /// A bounded, non-secret presentation of an RPC result.
    func displayValue(depth: Int = 0) -> Any {
        guard depth <= 12 else { return "<too deep>" }
        switch self {
        case .unsigned(let value):
            return value <= UInt64(Int64.max) ? Int64(value) : String(value)
        case .negative(let value):
            return value
        case .bytes(let value):
            return "<\(value.count) bytes>"
        case .string(let value):
            return value
        case .array(let value):
            return value.map { $0.displayValue(depth: depth + 1) }
        case .map(let value):
            return value.mapValues { $0.displayValue(depth: depth + 1) }
        case .bool(let value):
            return value
        case .null:
            return NSNull()
        case .float(let value):
            return value
        }
    }
}

enum FabricLinkCBORError: Error, Equatable {
    case invalidSize
    case invalidEncoding
    case nonCanonical
    case unsupportedValue
    case tooDeep
}

enum FabricLinkCanonicalCBOR {
    static func encode(_ value: FabricLinkCBOR) throws -> Data {
        var output = Data()
        try encode(value, into: &output, depth: 0)
        return output
    }

    static func decode(
        _ encoded: Data,
        maximum: Int
    ) throws -> FabricLinkCBOR {
        guard !encoded.isEmpty, maximum > 0, encoded.count <= maximum else {
            throw FabricLinkCBORError.invalidSize
        }
        var decoder = Decoder(data: encoded)
        let value = try decoder.decode(depth: 0)
        guard decoder.isAtEnd else {
            throw FabricLinkCBORError.invalidEncoding
        }
        guard try encode(value) == encoded else {
            throw FabricLinkCBORError.nonCanonical
        }
        return value
    }

    private static func encode(
        _ value: FabricLinkCBOR,
        into output: inout Data,
        depth: Int
    ) throws {
        guard depth <= 24 else { throw FabricLinkCBORError.tooDeep }
        switch value {
        case .unsigned(let number):
            appendHeader(major: 0, value: number, to: &output)
        case .negative(let number):
            guard number < 0 else { throw FabricLinkCBORError.unsupportedValue }
            appendHeader(major: 1, value: UInt64(-(number + 1)), to: &output)
        case .bytes(let bytes):
            appendHeader(major: 2, value: UInt64(bytes.count), to: &output)
            output.append(bytes)
        case .string(let string):
            guard let bytes = string.data(using: .utf8) else {
                throw FabricLinkCBORError.unsupportedValue
            }
            appendHeader(major: 3, value: UInt64(bytes.count), to: &output)
            output.append(bytes)
        case .array(let values):
            appendHeader(major: 4, value: UInt64(values.count), to: &output)
            for item in values {
                try encode(item, into: &output, depth: depth + 1)
            }
        case .map(let values):
            var entries: [(key: Data, value: FabricLinkCBOR)] = []
            entries.reserveCapacity(values.count)
            for (key, item) in values {
                entries.append((try encode(.string(key)), item))
            }
            entries.sort {
                if $0.key.count != $1.key.count {
                    return $0.key.count < $1.key.count
                }
                return $0.key.lexicographicallyPrecedes($1.key)
            }
            appendHeader(major: 5, value: UInt64(entries.count), to: &output)
            for entry in entries {
                output.append(entry.key)
                try encode(entry.value, into: &output, depth: depth + 1)
            }
        case .bool(let value):
            output.append(value ? 0xf5 : 0xf4)
        case .null:
            output.append(0xf6)
        case .float(let value):
            guard value.isFinite else { throw FabricLinkCBORError.unsupportedValue }
            let half = Float16(value)
            if Double(half) == value {
                output.append(0xf9)
                output.appendBigEndian(half.bitPattern)
                return
            }
            let single = Float(value)
            if Double(single) == value {
                output.append(0xfa)
                output.appendBigEndian(single.bitPattern)
                return
            }
            output.append(0xfb)
            output.appendBigEndian(value.bitPattern)
        }
    }

    private static func appendHeader(
        major: UInt8,
        value: UInt64,
        to output: inout Data
    ) {
        let prefix = major << 5
        switch value {
        case 0..<24:
            output.append(prefix | UInt8(value))
        case 24...UInt64(UInt8.max):
            output.append(prefix | 24)
            output.append(UInt8(value))
        case (UInt64(UInt8.max) + 1)...UInt64(UInt16.max):
            output.append(prefix | 25)
            output.appendBigEndian(UInt16(value))
        case (UInt64(UInt16.max) + 1)...UInt64(UInt32.max):
            output.append(prefix | 26)
            output.appendBigEndian(UInt32(value))
        default:
            output.append(prefix | 27)
            output.appendBigEndian(value)
        }
    }

    private struct Decoder {
        let data: Data
        var offset = 0

        var isAtEnd: Bool { offset == data.count }

        mutating func decode(depth: Int) throws -> FabricLinkCBOR {
            guard depth <= 24 else { throw FabricLinkCBORError.tooDeep }
            let initial = try readByte()
            let major = initial >> 5
            let additional = initial & 0x1f

            switch major {
            case 0:
                return .unsigned(try readLength(additional))
            case 1:
                let encoded = try readLength(additional)
                guard encoded <= UInt64(Int64.max) else {
                    throw FabricLinkCBORError.unsupportedValue
                }
                return .negative(-1 - Int64(encoded))
            case 2:
                return .bytes(try readData(length: try boundedLength(additional)))
            case 3:
                let bytes = try readData(length: try boundedLength(additional))
                guard let string = String(data: bytes, encoding: .utf8) else {
                    throw FabricLinkCBORError.invalidEncoding
                }
                return .string(string)
            case 4:
                let count = try boundedLength(additional)
                var values: [FabricLinkCBOR] = []
                values.reserveCapacity(min(count, 4096))
                for _ in 0..<count {
                    values.append(try decode(depth: depth + 1))
                }
                return .array(values)
            case 5:
                let count = try boundedLength(additional)
                var values: [String: FabricLinkCBOR] = [:]
                values.reserveCapacity(min(count, 4096))
                for _ in 0..<count {
                    let keyValue = try decode(depth: depth + 1)
                    guard case .string(let key) = keyValue, values[key] == nil else {
                        throw FabricLinkCBORError.invalidEncoding
                    }
                    values[key] = try decode(depth: depth + 1)
                }
                return .map(values)
            case 6:
                throw FabricLinkCBORError.unsupportedValue
            case 7:
                switch additional {
                case 20:
                    return .bool(false)
                case 21:
                    return .bool(true)
                case 22:
                    return .null
                case 25:
                    let value = Double(Float16(bitPattern: try readInteger(UInt16.self)))
                    guard value.isFinite else { throw FabricLinkCBORError.unsupportedValue }
                    return .float(value)
                case 26:
                    let value = Double(Float(bitPattern: try readInteger(UInt32.self)))
                    guard value.isFinite else { throw FabricLinkCBORError.unsupportedValue }
                    return .float(value)
                case 27:
                    let value = Double(bitPattern: try readInteger(UInt64.self))
                    guard value.isFinite else { throw FabricLinkCBORError.unsupportedValue }
                    return .float(value)
                default:
                    throw FabricLinkCBORError.unsupportedValue
                }
            default:
                throw FabricLinkCBORError.invalidEncoding
            }
        }

        private mutating func boundedLength(_ additional: UInt8) throws -> Int {
            let value = try readLength(additional)
            guard value <= UInt64(Int.max), value <= UInt64(data.count) else {
                throw FabricLinkCBORError.invalidSize
            }
            return Int(value)
        }

        private mutating func readLength(_ additional: UInt8) throws -> UInt64 {
            switch additional {
            case 0..<24:
                return UInt64(additional)
            case 24:
                return UInt64(try readByte())
            case 25:
                return UInt64(try readInteger(UInt16.self))
            case 26:
                return UInt64(try readInteger(UInt32.self))
            case 27:
                return try readInteger(UInt64.self)
            default:
                // Includes indefinite-length additional information 31.
                throw FabricLinkCBORError.invalidEncoding
            }
        }

        private mutating func readByte() throws -> UInt8 {
            guard offset < data.count else {
                throw FabricLinkCBORError.invalidEncoding
            }
            defer { offset += 1 }
            return data[offset]
        }

        private mutating func readData(length: Int) throws -> Data {
            guard length >= 0, length <= data.count - offset else {
                throw FabricLinkCBORError.invalidEncoding
            }
            let range = offset..<(offset + length)
            offset += length
            return data.subdata(in: range)
        }

        private mutating func readInteger<T: FixedWidthInteger>(
            _ type: T.Type
        ) throws -> T {
            let bytes = try readData(length: MemoryLayout<T>.size)
            return bytes.reduce(T.zero) { partial, byte in
                (partial << 8) | T(byte)
            }
        }
    }
}

private extension Data {
    mutating func appendBigEndian<T: FixedWidthInteger>(_ value: T) {
        var bigEndian = value.bigEndian
        Swift.withUnsafeBytes(of: &bigEndian) { bytes in
            append(contentsOf: bytes)
        }
    }
}
