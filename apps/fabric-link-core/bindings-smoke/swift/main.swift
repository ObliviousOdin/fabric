import Foundation
import CryptoKit

func bytes(_ value: String) -> Data {
    Data(value.utf8)
}

func hexData(_ value: String) -> Data {
    precondition(value.count.isMultiple(of: 2))
    var result = Data()
    var index = value.startIndex
    while index < value.endIndex {
        let next = value.index(index, offsetBy: 2)
        result.append(UInt8(value[index..<next], radix: 16)!)
        index = next
    }
    return result
}

func corpusString(_ corpus: [String: Any], _ key: String) -> String {
    guard let value = corpus[key] as? String else {
        fatalError("Missing v3 corpus field: \(key)")
    }
    return value
}

func verifyAesKnownAnswer(
    _ corpus: [String: Any],
    direction: String,
    plaintextKey: String
) throws {
    let ciphertextAndTag = hexData(
        corpusString(corpus, "enrollment_\(direction)_ciphertext_hex")
    )
    let tagStart = ciphertextAndTag.index(
        ciphertextAndTag.endIndex,
        offsetBy: -16
    )
    let sealed = try AES.GCM.SealedBox(
        nonce: try AES.GCM.Nonce(
            data: hexData(
                corpusString(corpus, "enrollment_\(direction)_nonce_hex")
            )
        ),
        ciphertext: Data(ciphertextAndTag[..<tagStart]),
        tag: Data(ciphertextAndTag[tagStart...])
    )
    let plaintext = try AES.GCM.open(
        sealed,
        using: SymmetricKey(
            data: hexData(
                corpusString(corpus, "enrollment_\(direction)_key_hex")
            )
        ),
        authenticating: hexData(
            corpusString(corpus, "enrollment_\(direction)_aad_hex")
        )
    )
    precondition(plaintext == hexData(corpusString(corpus, plaintextKey)))
}

guard let interopPath = ProcessInfo.processInfo.environment[
    "FABRIC_LINK_INTEROP_FIXTURE"
] else {
    fatalError("FABRIC_LINK_INTEROP_FIXTURE is required")
}
let interopData = try Data(contentsOf: URL(fileURLWithPath: interopPath))
let interop = try JSONSerialization.jsonObject(with: interopData) as! [String: Any]
precondition(interop["protocol_version"] as? Int == Int(fabricLinkProtocolVersion()))

for (valueKey, digestKey) in [
    ("pairing_cbor_hex", "pairing_cbor_sha256_hex"),
    ("link_request_cbor_hex", "link_request_sha256_hex"),
    ("enrollment_request_cbor_hex", "enrollment_request_sha256_hex"),
] {
    let digest = Data(SHA256.hash(data: hexData(corpusString(interop, valueKey))))
    precondition(digest == hexData(corpusString(interop, digestKey)))
}

let pairingDigest = Data(
    SHA256.hash(data: hexData(corpusString(interop, "pairing_cbor_hex")))
)
for (direction, domain) in [
    ("request", "fabric-link-enrollment-request-aad-v3"),
    ("response", "fabric-link-enrollment-response-aad-v3"),
] {
    let expectedAad = Data(domain.utf8) + Data([0]) + pairingDigest
    precondition(
        expectedAad
            == hexData(
                corpusString(
                    interop,
                    "enrollment_\(direction)_aad_hex"
                )
            )
    )
}

let pairingSalt = Data(
    SHA256.hash(
        data:
            hexData(corpusString(interop, "pairing_route_hex"))
            + hexData(corpusString(interop, "pairing_handle_hex"))
    )
)
for (info, expectedKey) in [
    (
        "fabric-link-enrollment-request-key-v3",
        "enrollment_request_key_hex"
    ),
    (
        "fabric-link-enrollment-response-key-v3",
        "enrollment_response_key_hex"
    ),
] {
    let key = HKDF<SHA256>.deriveKey(
        inputKeyMaterial: SymmetricKey(
            data: hexData(corpusString(interop, "pairing_secret_hex"))
        ),
        salt: pairingSalt,
        info: Data(info.utf8),
        outputByteCount: 32
    )
    let keyData = key.withUnsafeBytes { Data($0) }
    precondition(keyData == hexData(corpusString(interop, expectedKey)))
}
try verifyAesKnownAnswer(
    interop,
    direction: "request",
    plaintextKey: "enrollment_request_cbor_hex"
)
try verifyAesKnownAnswer(
    interop,
    direction: "response",
    plaintextKey: "enrollment_response_plaintext_cbor_hex"
)

let controller = try fabricLinkCreateController(identity: bytes("swift-controller"))
let restoredKeyPackage = try fabricLinkControllerKeyPackage(
    opaqueState: controller.opaqueState
)
precondition(restoredKeyPackage == controller.keyPackage)
let pair = try fabricLinkCreatePair(
    hostIdentity: bytes("swift-host"),
    groupId: bytes("swift-binding-pair"),
    controllerKeyPackage: controller.keyPackage
)
let controllerState = try fabricLinkControllerJoin(
    opaqueState: controller.opaqueState,
    welcome: pair.welcome
)
let encrypted = try fabricLinkHostEncrypt(
    opaqueState: pair.hostState,
    plaintext: bytes("swift fixture")
)
let decrypted = try fabricLinkControllerDecrypt(
    opaqueState: controllerState,
    message: encrypted.message
)
precondition(decrypted.plaintext == bytes("swift fixture"))

let controllerEncrypted = try fabricLinkControllerEncrypt(
    opaqueState: decrypted.opaqueState,
    plaintext: bytes("swift controller fixture")
)
let hostDecrypted = try fabricLinkHostDecrypt(
    opaqueState: encrypted.opaqueState,
    message: controllerEncrypted.message
)
precondition(hostDecrypted.plaintext == bytes("swift controller fixture"))

let removal = try fabricLinkHostRemoveController(opaqueState: hostDecrypted.opaqueState)
let removed = try fabricLinkControllerApplyCommit(
    opaqueState: controllerEncrypted.opaqueState,
    commit: removal.message
)
precondition(!removed.active)

if let fixturePath = ProcessInfo.processInfo.environment["FABRIC_LINK_FIXTURE_DIR"] {
    let fixture = URL(fileURLWithPath: fixturePath, isDirectory: true)
    let crossLanguage = try fabricLinkControllerDecrypt(
        opaqueState: Data(contentsOf: fixture.appendingPathComponent("controller-state.bin")),
        message: Data(contentsOf: fixture.appendingPathComponent("message.bin"))
    )
    let fixturePlaintext = try Data(
        contentsOf: fixture.appendingPathComponent("plaintext.bin")
    )
    precondition(crossLanguage.plaintext == fixturePlaintext)
}
print("PASS Swift UniFFI bidirectional pairing/restart/removal + v3 corpus")
