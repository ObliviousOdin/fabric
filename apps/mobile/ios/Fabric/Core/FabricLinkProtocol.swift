import CryptoKit
import FabricLinkCore
import Foundation
import Security

enum FabricLinkError: LocalizedError, Equatable {
    case invalidPairingCode
    case pairingExpired
    case unsupportedProtocol
    case invalidRecord
    case invalidGrant
    case nativeCoreMismatch
    case protectedStateUnavailable
    case relayUnavailable
    case relayRejected(String)
    case pairingNotApproved
    case requestRejected(String)
    case requestTimedOut
    case requestInFlight
    case controllerRevoked

    var errorDescription: String? {
        switch self {
        case .invalidPairingCode:
            return "This is not a valid Fabric Link pairing code."
        case .pairingExpired:
            return "This pairing code expired. Create and scan a new code."
        case .unsupportedProtocol:
            return "This Fabric Link version is not supported by this app."
        case .invalidRecord:
            return "Fabric Link rejected an invalid or altered encrypted record."
        case .invalidGrant:
            return "The pairing requested an unsupported permission."
        case .nativeCoreMismatch:
            return "The installed Fabric Link cryptographic core does not match this app."
        case .protectedStateUnavailable:
            return "Fabric Link couldn't access protected state. Unlock this iPhone and try again."
        case .relayUnavailable:
            return "The blind relay is unavailable. Check the connection and try again."
        case .relayRejected(let code):
            return "The blind relay rejected this request (\(code))."
        case .pairingNotApproved:
            return "The computer did not approve pairing before the code expired."
        case .requestRejected(let code):
            return "The computer rejected this action (\(code))."
        case .requestTimedOut:
            return "The computer did not respond before this request expired."
        case .requestInFlight:
            return "Another Fabric Link request is still in progress."
        case .controllerRevoked:
            return "This iPhone's Fabric Link access was revoked on the computer."
        }
    }
}

enum FabricLinkWire {
    static let protocolVersion = 3
    static let relayProtocolVersion = 1
    static let ciphersuite = "MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519"
    static let grants = Set(["observe", "chat", "dispatch", "approve"])
    static let pairingTTL = 300
    static let requestTTL = 300
    static let maxEnrollmentRecord = 256 * 1024
    static let maxApplicationEnvelope = 1024 * 1024 + 64 * 1024 + 1024
    static let maxResponse = 1024 * 1024
    static let maxRelayFrame = maxApplicationEnvelope + 2048

    static func requireCore() throws {
        guard fabricLinkProtocolVersion() == UInt16(protocolVersion),
              fabricLinkCiphersuite() == ciphersuite else {
            throw FabricLinkError.nativeCoreMismatch
        }
    }

    static func randomBytes(count: Int) throws -> Data {
        guard count > 0 else { throw FabricLinkError.invalidRecord }
        var data = Data(count: count)
        let status = data.withUnsafeMutableBytes { bytes in
            SecRandomCopyBytes(kSecRandomDefault, count, bytes.baseAddress!)
        }
        guard status == errSecSuccess else {
            throw FabricLinkError.protectedStateUnavailable
        }
        return data
    }

    static func sha256(_ data: Data) -> Data {
        Data(SHA256.hash(data: data))
    }

    static func exactMap(
        _ value: FabricLinkCBOR,
        keys: Set<String>
    ) throws -> [String: FabricLinkCBOR] {
        guard let map = value.mapValue, Set(map.keys) == keys else {
            throw FabricLinkError.invalidRecord
        }
        return map
    }

    static func bytes(
        _ value: FabricLinkCBOR?,
        count: Int? = nil,
        allowEmpty: Bool = true
    ) throws -> Data {
        guard let data = value?.dataValue,
              (count == nil || data.count == count),
              allowEmpty || !data.isEmpty else {
            throw FabricLinkError.invalidRecord
        }
        return data
    }

    static func string(_ value: FabricLinkCBOR?) throws -> String {
        guard let string = value?.stringValue else {
            throw FabricLinkError.invalidRecord
        }
        return string
    }

    static func integer(_ value: FabricLinkCBOR?) throws -> Int {
        guard let number = value?.intValue else {
            throw FabricLinkError.invalidRecord
        }
        return number
    }

    static func bool(_ value: FabricLinkCBOR?) throws -> Bool {
        guard let result = value?.boolValue else {
            throw FabricLinkError.invalidRecord
        }
        return result
    }

    static func normalizedGrants(
        _ value: [String],
        allowEmpty: Bool = false
    ) throws -> [String] {
        guard value.allSatisfy(grants.contains) else {
            throw FabricLinkError.invalidGrant
        }
        let normalized = Array(Set(value)).sorted()
        guard allowEmpty || !normalized.isEmpty else {
            throw FabricLinkError.invalidGrant
        }
        return normalized
    }

    static func grantArray(_ value: FabricLinkCBOR?) throws -> [String] {
        guard let rows = value?.arrayValue else {
            throw FabricLinkError.invalidRecord
        }
        return try normalizedGrants(rows.map { try string($0) })
    }

    static func normalizedRelayOrigin(
        _ raw: String,
        allowLoopbackHTTP: Bool = false
    ) throws -> String {
        guard !raw.isEmpty,
              !raw.contains(where: \.isWhitespace),
              !raw.contains("?"),
              !raw.contains("#"),
              let components = URLComponents(string: raw),
              components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil,
              components.path.isEmpty || components.path == "/",
              let schemeValue = components.scheme?.lowercased(),
              let hostValue = components.host?.lowercased(),
              !hostValue.isEmpty else {
            throw FabricLinkError.invalidPairingCode
        }
        let loopback = hostValue == "localhost"
            || hostValue == "127.0.0.1"
            || hostValue == "::1"
        guard schemeValue == "https"
            || (allowLoopbackHTTP && schemeValue == "http" && loopback) else {
            throw FabricLinkError.invalidPairingCode
        }
        let defaultPort = schemeValue == "https" ? 443 : 80
        let host = hostValue.contains(":") ? "[\(hostValue)]" : hostValue
        let authority = components.port == nil || components.port == defaultPort
            ? host
            : "\(host):\(components.port!)"
        return "\(schemeValue)://\(authority)"
    }

    static func strictBase64URLDecode(_ value: String, maximum: Int) throws -> Data {
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        guard !value.isEmpty,
              !value.contains("="),
              value.unicodeScalars.allSatisfy(allowed.contains),
              let decoded = Data(
                base64Encoded: value
                    .replacingOccurrences(of: "-", with: "+")
                    .replacingOccurrences(of: "_", with: "/")
                    + String(repeating: "=", count: (4 - value.count % 4) % 4),
                options: []
              ),
              decoded.count <= maximum,
              strictBase64URLEncode(decoded) == value else {
            throw FabricLinkError.invalidPairingCode
        }
        return decoded
    }

    static func strictBase64URLEncode(_ value: Data) -> String {
        value.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    static func fingerprint(_ value: Data) -> String {
        let digest = sha256(value).prefix(10)
        let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        var accumulator = 0
        var bits = 0
        var output = ""
        for byte in digest {
            accumulator = (accumulator << 8) | Int(byte)
            bits += 8
            while bits >= 5 {
                bits -= 5
                output.append(alphabet[(accumulator >> bits) & 31])
            }
        }
        if bits > 0 {
            output.append(alphabet[(accumulator << (5 - bits)) & 31])
        }
        return stride(from: 0, to: output.count, by: 4).map { start in
            let lower = output.index(output.startIndex, offsetBy: start)
            let upper = output.index(lower, offsetBy: min(4, output.count - start))
            return String(output[lower..<upper])
        }.joined(separator: "-")
    }

    static func normalizedControllerName(_ value: String) throws -> String {
        let normalized = value.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard !normalized.isEmpty,
              normalized.lengthOfBytes(using: .utf8) <= 96,
              !normalized.unicodeScalars.contains(where: { $0.value < 32 }) else {
            throw FabricLinkError.invalidRecord
        }
        return normalized
    }

    static func validMethod(_ method: String) -> Bool {
        guard !method.isEmpty,
              method.utf8.count <= 96,
              let first = method.utf8.first,
              first >= Character("a").asciiValue!,
              first <= Character("z").asciiValue! else {
            return false
        }
        return method.utf8.allSatisfy {
            ($0 >= 97 && $0 <= 122)
                || ($0 >= 48 && $0 <= 57)
                || $0 == 95 || $0 == 46 || $0 == 45
        }
    }

    static func sealed(
        plaintext: Data,
        key: SymmetricKey,
        nonce: Data,
        aad: Data
    ) throws -> Data {
        let sealed = try AES.GCM.seal(
            plaintext,
            using: key,
            nonce: AES.GCM.Nonce(data: nonce),
            authenticating: aad
        )
        return sealed.ciphertext + sealed.tag
    }

    static func opened(
        ciphertextAndTag: Data,
        key: SymmetricKey,
        nonce: Data,
        aad: Data
    ) throws -> Data {
        guard ciphertextAndTag.count > 16 else {
            throw FabricLinkError.invalidRecord
        }
        let split = ciphertextAndTag.count - 16
        let box = try AES.GCM.SealedBox(
            nonce: AES.GCM.Nonce(data: nonce),
            ciphertext: ciphertextAndTag.prefix(split),
            tag: ciphertextAndTag.suffix(16)
        )
        return try AES.GCM.open(box, using: key, authenticating: aad)
    }
}

/// A short-lived, machine-authenticated Fabric Link v3 QR payload.
///
/// Its debug descriptions never reveal the one-time pairing secret or complete
/// URL. The raw payload exists only in this value and the protected pending
/// controller bundle.
struct FabricLinkPairing: Identifiable, Equatable, CustomStringConvertible, CustomDebugStringConvertible {
    let relayOrigin: String
    let routeID: Data
    let handle: Data
    private let secret: Data
    let machinePublicKey: Data
    let expiresAt: Int

    var id: String {
        FabricLinkWire.strictBase64URLEncode(handle)
    }

    var machineFingerprint: String {
        FabricLinkWire.fingerprint(machinePublicKey)
    }

    var description: String {
        "Fabric Link pairing for \(machineFingerprint) <secret redacted>"
    }

    var debugDescription: String { description }

    static func parse(
        _ raw: String,
        now: Int = Int(Date().timeIntervalSince1970),
        allowLoopbackHTTP: Bool = false
    ) throws -> FabricLinkPairing {
        guard !raw.contains(where: \.isWhitespace),
              !raw.contains("%"),
              let components = URLComponents(string: raw),
              components.path == "/link/pair",
              components.query == nil,
              let fragment = components.fragment,
              fragment.hasPrefix("pair="),
              fragment.filter({ $0 == "=" }).count == 1,
              !fragment.contains("&"),
              let scheme = components.scheme,
              let host = components.host else {
            throw FabricLinkError.invalidPairingCode
        }
        var originComponents = URLComponents()
        originComponents.scheme = scheme
        originComponents.host = host
        originComponents.port = components.port
        guard let outerRaw = originComponents.string else {
            throw FabricLinkError.invalidPairingCode
        }
        let outerOrigin = try FabricLinkWire.normalizedRelayOrigin(
            outerRaw,
            allowLoopbackHTTP: allowLoopbackHTTP
        )
        let encoded = String(fragment.dropFirst("pair=".count))
        let bytes = try FabricLinkWire.strictBase64URLDecode(encoded, maximum: 4096)
        let value = try FabricLinkCanonicalCBOR.decode(bytes, maximum: 4096)
        let map = try FabricLinkWire.exactMap(
            value,
            keys: ["v", "relay", "route", "handle", "secret", "machine_key", "expires_at"]
        )
        let version = try FabricLinkWire.integer(map["v"])
        guard version == FabricLinkWire.protocolVersion else {
            throw FabricLinkError.unsupportedProtocol
        }
        let relay = try FabricLinkWire.normalizedRelayOrigin(
            try FabricLinkWire.string(map["relay"]),
            allowLoopbackHTTP: allowLoopbackHTTP
        )
        guard relay == outerOrigin,
              relay == (try FabricLinkWire.string(map["relay"])) else {
            throw FabricLinkError.invalidPairingCode
        }
        let expiry = try FabricLinkWire.integer(map["expires_at"])
        guard expiry > now else { throw FabricLinkError.pairingExpired }
        guard expiry <= now + FabricLinkWire.pairingTTL else {
            throw FabricLinkError.invalidPairingCode
        }
        return FabricLinkPairing(
            relayOrigin: relay,
            routeID: try FabricLinkWire.bytes(map["route"], count: 32),
            handle: try FabricLinkWire.bytes(map["handle"], count: 32),
            secret: try FabricLinkWire.bytes(map["secret"], count: 32),
            machinePublicKey: try FabricLinkWire.bytes(map["machine_key"], count: 32),
            expiresAt: expiry
        )
    }

    func cbor() throws -> Data {
        try FabricLinkCanonicalCBOR.encode(.map([
            "v": .integer(FabricLinkWire.protocolVersion),
            "relay": .string(relayOrigin),
            "route": .bytes(routeID),
            "handle": .bytes(handle),
            "secret": .bytes(secret),
            "machine_key": .bytes(machinePublicKey),
            "expires_at": .integer(expiresAt),
        ]))
    }

    func enrollmentKey(response: Bool) throws -> SymmetricKey {
        let salt = FabricLinkWire.sha256(routeID + handle)
        let info = Data(
            (response
             ? "fabric-link-enrollment-response-key-v3"
             : "fabric-link-enrollment-request-key-v3").utf8
        )
        return HKDF<SHA256>.deriveKey(
            inputKeyMaterial: SymmetricKey(data: secret),
            salt: salt,
            info: info,
            outputByteCount: 32
        )
    }

    func enrollmentAAD(response: Bool) throws -> Data {
        Data(
            (response
             ? "fabric-link-enrollment-response-aad-v3\0"
             : "fabric-link-enrollment-request-aad-v3\0").utf8
        ) + FabricLinkWire.sha256(try cbor())
    }
}

struct FabricLinkEnrollmentRequest {
    let handle: Data
    let controllerNonce: Data
    let controllerName: String
    let platform: String
    let requestedGrants: [String]
    let relayPublicKey: Data
    let keyPackage: Data
    let credentialHash: Data
    let issuedAt: Int
    let expiresAt: Int

    func cbor() throws -> Data {
        try FabricLinkCanonicalCBOR.encode(.map([
            "v": .integer(FabricLinkWire.protocolVersion),
            "handle": .bytes(handle),
            "controller_nonce": .bytes(controllerNonce),
            "controller_name": .string(controllerName),
            "platform": .string(platform),
            "requested_grants": .array(requestedGrants.map(FabricLinkCBOR.string)),
            "relay_public_key": .bytes(relayPublicKey),
            "key_package": .bytes(keyPackage),
            "credential_hash": .bytes(credentialHash),
            "issued_at": .integer(issuedAt),
            "expires_at": .integer(expiresAt),
        ]))
    }

    static func decode(_ encoded: Data) throws -> FabricLinkEnrollmentRequest {
        let value = try FabricLinkCanonicalCBOR.decode(
            encoded,
            maximum: FabricLinkWire.maxEnrollmentRecord
        )
        let map = try FabricLinkWire.exactMap(
            value,
            keys: [
                "v", "handle", "controller_nonce", "controller_name", "platform",
                "requested_grants", "relay_public_key", "key_package",
                "credential_hash", "issued_at", "expires_at",
            ]
        )
        guard try FabricLinkWire.integer(map["v"]) == FabricLinkWire.protocolVersion else {
            throw FabricLinkError.unsupportedProtocol
        }
        let name = try FabricLinkWire.normalizedControllerName(
            try FabricLinkWire.string(map["controller_name"])
        )
        let platform = try FabricLinkWire.string(map["platform"])
        guard ["ios", "android", "web", "desktop", "cli"].contains(platform) else {
            throw FabricLinkError.invalidRecord
        }
        let grants = try FabricLinkWire.grantArray(map["requested_grants"])
        let keyPackage = try FabricLinkWire.bytes(
            map["key_package"],
            allowEmpty: false
        )
        guard keyPackage.count <= 128 * 1024 else {
            throw FabricLinkError.invalidRecord
        }
        let credentialHash = try FabricLinkWire.bytes(map["credential_hash"], count: 32)
        guard FabricLinkWire.sha256(keyPackage) == credentialHash else {
            throw FabricLinkError.invalidRecord
        }
        let issuedAt = try FabricLinkWire.integer(map["issued_at"])
        let expiresAt = try FabricLinkWire.integer(map["expires_at"])
        guard expiresAt > issuedAt,
              expiresAt - issuedAt <= FabricLinkWire.pairingTTL else {
            throw FabricLinkError.invalidRecord
        }
        return FabricLinkEnrollmentRequest(
            handle: try FabricLinkWire.bytes(map["handle"], count: 32),
            controllerNonce: try FabricLinkWire.bytes(map["controller_nonce"], count: 32),
            controllerName: name,
            platform: platform,
            requestedGrants: grants,
            relayPublicKey: try FabricLinkWire.bytes(map["relay_public_key"], count: 32),
            keyPackage: keyPackage,
            credentialHash: credentialHash,
            issuedAt: issuedAt,
            expiresAt: expiresAt
        )
    }

    static func make(
        pairing: FabricLinkPairing,
        name: String,
        grants: [String],
        relayPublicKey: Data,
        keyPackage: Data,
        now: Int
    ) throws -> FabricLinkEnrollmentRequest {
        let normalized = try FabricLinkWire.normalizedGrants(grants)
        let expiry = min(pairing.expiresAt, now + FabricLinkWire.pairingTTL)
        return FabricLinkEnrollmentRequest(
            handle: pairing.handle,
            controllerNonce: try FabricLinkWire.randomBytes(count: 32),
            controllerName: try FabricLinkWire.normalizedControllerName(name),
            platform: "ios",
            requestedGrants: normalized,
            relayPublicKey: relayPublicKey,
            keyPackage: keyPackage,
            credentialHash: FabricLinkWire.sha256(keyPackage),
            issuedAt: now,
            expiresAt: expiry
        )
    }

    func encryptedEnvelope(pairing: FabricLinkPairing) throws -> Data {
        let nonce = try FabricLinkWire.randomBytes(count: 12)
        let ciphertext = try FabricLinkWire.sealed(
            plaintext: cbor(),
            key: pairing.enrollmentKey(response: false),
            nonce: nonce,
            aad: pairing.enrollmentAAD(response: false)
        )
        let encoded = try FabricLinkCanonicalCBOR.encode(.map([
            "v": .integer(FabricLinkWire.protocolVersion),
            "handle": .bytes(handle),
            "nonce": .bytes(nonce),
            "ciphertext": .bytes(ciphertext),
        ]))
        guard encoded.count <= FabricLinkWire.maxEnrollmentRecord else {
            throw FabricLinkError.invalidRecord
        }
        return encoded
    }
}

struct FabricLinkEnrollmentResult {
    let welcome: Data
    let admissionCertificate: Data
    let credentialSerial: Data
    let grants: [String]
}

enum FabricLinkEnrollmentVerifier {
    private static let responseSignatureDomain = Data(
        "fabric-link-enrollment-response-signature-v3\0".utf8
    )
    private static let certificateSignatureDomain = Data(
        "fabric-link-relay-admission-certificate-v1\0".utf8
    )

    static func decrypt(
        pairing: FabricLinkPairing,
        request: FabricLinkEnrollmentRequest,
        encrypted: Data,
        now: Int
    ) throws -> FabricLinkEnrollmentResult {
        let envelopeValue = try FabricLinkCanonicalCBOR.decode(
            encrypted,
            maximum: FabricLinkWire.maxEnrollmentRecord
        )
        let envelope = try FabricLinkWire.exactMap(
            envelopeValue,
            keys: ["v", "handle", "nonce", "ciphertext"]
        )
        guard try FabricLinkWire.integer(envelope["v"]) == FabricLinkWire.protocolVersion,
              try FabricLinkWire.bytes(envelope["handle"], count: 32) == pairing.handle else {
            throw FabricLinkError.invalidRecord
        }
        let plaintext = try FabricLinkWire.opened(
            ciphertextAndTag: try FabricLinkWire.bytes(
                envelope["ciphertext"],
                allowEmpty: false
            ),
            key: pairing.enrollmentKey(response: true),
            nonce: try FabricLinkWire.bytes(envelope["nonce"], count: 12),
            aad: pairing.enrollmentAAD(response: true)
        )
        let responseValue = try FabricLinkCanonicalCBOR.decode(
            plaintext,
            maximum: FabricLinkWire.maxEnrollmentRecord
        )
        let response = try FabricLinkWire.exactMap(
            responseValue,
            keys: [
                "v", "handle", "group_id", "welcome", "admission_certificate",
                "approved_grants", "request_hash", "issued_at", "expires_at",
                "machine_signature",
            ]
        )
        let signature = try FabricLinkWire.bytes(
            response["machine_signature"],
            count: 64
        )
        var core = response
        core.removeValue(forKey: "machine_signature")
        let coreCBOR = try FabricLinkCanonicalCBOR.encode(.map(core))
        let requestCBOR = try request.cbor()
        let signatureInput = responseSignatureDomain
            + FabricLinkWire.sha256(try pairing.cbor())
            + FabricLinkWire.sha256(requestCBOR)
            + coreCBOR
        let machineKey = try Curve25519.Signing.PublicKey(
            rawRepresentation: pairing.machinePublicKey
        )
        guard machineKey.isValidSignature(signature, for: signatureInput) else {
            throw FabricLinkError.invalidRecord
        }
        let grants = try FabricLinkWire.grantArray(response["approved_grants"])
        let issuedAt = try FabricLinkWire.integer(response["issued_at"])
        let expiresAt = try FabricLinkWire.integer(response["expires_at"])
        guard try FabricLinkWire.integer(response["v"]) == FabricLinkWire.protocolVersion,
              try FabricLinkWire.bytes(response["handle"], count: 32) == pairing.handle,
              try FabricLinkWire.bytes(response["request_hash"], count: 32)
                == FabricLinkWire.sha256(requestCBOR),
              issuedAt <= now + 30,
              expiresAt > now,
              Set(grants).isSubset(of: Set(request.requestedGrants)) else {
            throw FabricLinkError.invalidRecord
        }
        _ = try FabricLinkWire.bytes(response["group_id"], count: 32)
        let welcome = try FabricLinkWire.bytes(response["welcome"], allowEmpty: false)
        guard welcome.count <= 128 * 1024 else {
            throw FabricLinkError.invalidRecord
        }
        let certificate = try FabricLinkWire.bytes(
            response["admission_certificate"],
            allowEmpty: false
        )
        let serial = try verifyCertificate(
            certificate,
            pairing: pairing,
            relayPublicKey: request.relayPublicKey,
            now: now
        )
        return FabricLinkEnrollmentResult(
            welcome: welcome,
            admissionCertificate: certificate,
            credentialSerial: serial,
            grants: grants
        )
    }

    private static func verifyCertificate(
        _ signedCertificate: Data,
        pairing: FabricLinkPairing,
        relayPublicKey: Data,
        now: Int
    ) throws -> Data {
        let signedValue = try FabricLinkCanonicalCBOR.decode(
            signedCertificate,
            maximum: 16 * 1024
        )
        let signed = try FabricLinkWire.exactMap(
            signedValue,
            keys: ["certificate", "signature"]
        )
        let certificateCBOR = try FabricLinkWire.bytes(
            signed["certificate"],
            allowEmpty: false
        )
        let signature = try FabricLinkWire.bytes(signed["signature"], count: 64)
        let machineKey = try Curve25519.Signing.PublicKey(
            rawRepresentation: pairing.machinePublicKey
        )
        guard machineKey.isValidSignature(
            signature,
            for: certificateSignatureDomain + certificateCBOR
        ) else {
            throw FabricLinkError.invalidRecord
        }
        let certificateValue = try FabricLinkCanonicalCBOR.decode(
            certificateCBOR,
            maximum: 4096
        )
        let certificate = try FabricLinkWire.exactMap(
            certificateValue,
            keys: [
                "v", "route_id", "relay_public_key", "credential_serial",
                "not_before", "not_after",
            ]
        )
        guard try FabricLinkWire.integer(certificate["v"]) == 1,
              try FabricLinkWire.bytes(certificate["route_id"], count: 32)
                == pairing.routeID,
              try FabricLinkWire.bytes(certificate["relay_public_key"], count: 32)
                == relayPublicKey,
              try FabricLinkWire.integer(certificate["not_before"]) <= now,
              try FabricLinkWire.integer(certificate["not_after"]) > now else {
            throw FabricLinkError.invalidRecord
        }
        return try FabricLinkWire.bytes(
            certificate["credential_serial"],
            count: 16
        )
    }

    static func shortAuthenticationString(
        pairing: FabricLinkPairing,
        request: FabricLinkEnrollmentRequest
    ) throws -> String {
        let digest = FabricLinkWire.sha256(try pairing.cbor() + request.cbor())
        let number = digest.prefix(4).reduce(UInt32.zero) {
            ($0 << 8) | UInt32($1)
        } % 1_000_000
        return String(format: "%06u", number)
    }
}

struct FabricLinkApplicationRequest {
    let requestID: Data
    let idempotencyKey: Data
    let issuedAt: Int
    let expiresAt: Int
    let method: String
    let paramsCBOR: Data

    func cbor() throws -> Data {
        guard requestID.count == 16,
              idempotencyKey.count == 16,
              FabricLinkWire.validMethod(method),
              expiresAt > issuedAt,
              expiresAt - issuedAt <= FabricLinkWire.requestTTL else {
            throw FabricLinkError.invalidRecord
        }
        _ = try FabricLinkCanonicalCBOR.decode(paramsCBOR, maximum: 240 * 1024)
        let encoded = try FabricLinkCanonicalCBOR.encode(.map([
            "v": .integer(FabricLinkWire.protocolVersion),
            "request_id": .bytes(requestID),
            "idempotency_key": .bytes(idempotencyKey),
            "issued_at": .integer(issuedAt),
            "expires_at": .integer(expiresAt),
            "method": .string(method),
            "params": .bytes(paramsCBOR),
        ]))
        guard encoded.count <= 256 * 1024 else {
            throw FabricLinkError.invalidRecord
        }
        return encoded
    }
}

struct FabricLinkApplicationResponse {
    let requestID: Data
    let completedAt: Int
    let ok: Bool
    let result: FabricLinkCBOR?
    let errorCode: String?

    static func decode(_ encoded: Data) throws -> FabricLinkApplicationResponse {
        let value = try FabricLinkCanonicalCBOR.decode(
            encoded,
            maximum: FabricLinkWire.maxResponse
        )
        let map = try FabricLinkWire.exactMap(
            value,
            keys: ["v", "request_id", "completed_at", "ok", "result", "error_code"]
        )
        guard try FabricLinkWire.integer(map["v"]) == FabricLinkWire.protocolVersion else {
            throw FabricLinkError.unsupportedProtocol
        }
        let ok = try FabricLinkWire.bool(map["ok"])
        let resultValue: FabricLinkCBOR?
        if case .bytes(let resultCBOR)? = map["result"] {
            resultValue = try FabricLinkCanonicalCBOR.decode(
                resultCBOR,
                maximum: FabricLinkWire.maxResponse
            )
        } else if case .null? = map["result"] {
            resultValue = nil
        } else {
            throw FabricLinkError.invalidRecord
        }
        let error: String?
        if case .string(let code)? = map["error_code"] {
            guard FabricLinkWire.validMethod(code) else {
                throw FabricLinkError.invalidRecord
            }
            error = code
        } else if case .null? = map["error_code"] {
            error = nil
        } else {
            throw FabricLinkError.invalidRecord
        }
        guard ok == (error == nil),
              ok == (resultValue != nil) else {
            throw FabricLinkError.invalidRecord
        }
        return FabricLinkApplicationResponse(
            requestID: try FabricLinkWire.bytes(map["request_id"], count: 16),
            completedAt: try FabricLinkWire.integer(map["completed_at"]),
            ok: ok,
            result: resultValue,
            errorCode: error
        )
    }
}

struct FabricLinkApplicationEnvelope {
    let routeID: Data
    let credentialSerial: Data
    let ciphertext: Data

    func cbor() throws -> Data {
        guard routeID.count == 32,
              credentialSerial.count == 16,
              !ciphertext.isEmpty,
              ciphertext.count <= FabricLinkWire.maxApplicationEnvelope else {
            throw FabricLinkError.invalidRecord
        }
        return try FabricLinkCanonicalCBOR.encode(.map([
            "v": .integer(FabricLinkWire.protocolVersion),
            "route": .bytes(routeID),
            "credential_serial": .bytes(credentialSerial),
            "ciphertext": .bytes(ciphertext),
        ]))
    }

    static func decode(_ encoded: Data) throws -> FabricLinkApplicationEnvelope {
        let value = try FabricLinkCanonicalCBOR.decode(
            encoded,
            maximum: FabricLinkWire.maxApplicationEnvelope
        )
        let map = try FabricLinkWire.exactMap(
            value,
            keys: ["v", "route", "credential_serial", "ciphertext"]
        )
        guard try FabricLinkWire.integer(map["v"]) == FabricLinkWire.protocolVersion else {
            throw FabricLinkError.unsupportedProtocol
        }
        return FabricLinkApplicationEnvelope(
            routeID: try FabricLinkWire.bytes(map["route"], count: 32),
            credentialSerial: try FabricLinkWire.bytes(
                map["credential_serial"],
                count: 16
            ),
            ciphertext: try FabricLinkWire.bytes(
                map["ciphertext"],
                allowEmpty: false
            )
        )
    }
}
