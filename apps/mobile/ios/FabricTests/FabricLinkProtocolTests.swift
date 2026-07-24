import CryptoKit
import FabricLinkCore
import XCTest
@testable import Fabric

final class FabricLinkProtocolTests: XCTestCase {
    func testSharedV3CorpusMatchesSwiftPairingAndEnrollmentCrypto() throws {
        let fixture = try fixture()
        let now = try XCTUnwrap(fixture["pairing_now"] as? Int)
        let pairingURL = try XCTUnwrap(fixture["pairing_url"] as? String)
        let pairing = try FabricLinkPairing.parse(pairingURL, now: now)

        XCTAssertEqual(
            try pairing.cbor(),
            try hex(fixture, "pairing_cbor_hex")
        )
        XCTAssertEqual(
            FabricLinkWire.sha256(try pairing.cbor()),
            try hex(fixture, "pairing_cbor_sha256_hex")
        )
        XCTAssertEqual(pairing.relayOrigin, fixture["relay_origin"] as? String)
        XCTAssertEqual(pairing.routeID, try hex(fixture, "pairing_route_hex"))
        XCTAssertEqual(pairing.handle, try hex(fixture, "pairing_handle_hex"))
        XCTAssertEqual(
            pairing.machinePublicKey,
            try hex(fixture, "pairing_machine_key_hex")
        )

        let requestKey = try pairing.enrollmentKey(response: false)
        XCTAssertEqual(
            requestKey.withUnsafeBytes { Data($0) },
            try hex(fixture, "enrollment_request_key_hex")
        )
        XCTAssertEqual(
            try pairing.enrollmentAAD(response: false),
            try hex(fixture, "enrollment_request_aad_hex")
        )

        let requestCBOR = try hex(fixture, "enrollment_request_cbor_hex")
        let request = try FabricLinkEnrollmentRequest.decode(requestCBOR)
        XCTAssertEqual(try request.cbor(), requestCBOR)
        XCTAssertEqual(
            FabricLinkWire.sha256(requestCBOR),
            try hex(fixture, "enrollment_request_sha256_hex")
        )
        XCTAssertEqual(
            try FabricLinkWire.sealed(
                plaintext: requestCBOR,
                key: requestKey,
                nonce: try hex(fixture, "enrollment_request_nonce_hex"),
                aad: try pairing.enrollmentAAD(response: false)
            ),
            try hex(fixture, "enrollment_request_ciphertext_hex")
        )

        let responseKey = try pairing.enrollmentKey(response: true)
        XCTAssertEqual(
            responseKey.withUnsafeBytes { Data($0) },
            try hex(fixture, "enrollment_response_key_hex")
        )
        XCTAssertEqual(
            try pairing.enrollmentAAD(response: true),
            try hex(fixture, "enrollment_response_aad_hex")
        )
        XCTAssertEqual(
            try FabricLinkWire.opened(
                ciphertextAndTag: try hex(
                    fixture,
                    "enrollment_response_ciphertext_hex"
                ),
                key: responseKey,
                nonce: try hex(fixture, "enrollment_response_nonce_hex"),
                aad: try pairing.enrollmentAAD(response: true)
            ),
            try hex(fixture, "enrollment_response_plaintext_cbor_hex")
        )
    }

    func testCanonicalDecoderRejectsAlternateOrAmbiguousEncodings() throws {
        // Integer 1 encoded non-minimally with one following byte.
        XCTAssertThrowsError(
            try FabricLinkCanonicalCBOR.decode(
                Data([0x18, 0x01]),
                maximum: 16
            )
        ) { error in
            XCTAssertEqual(error as? FabricLinkCBORError, .nonCanonical)
        }

        // Duplicate "a" keys are rejected while parsing, before dictionary
        // construction could silently overwrite the first value.
        XCTAssertThrowsError(
            try FabricLinkCanonicalCBOR.decode(
                Data([0xa2, 0x61, 0x61, 0x01, 0x61, 0x61, 0x02]),
                maximum: 32
            )
        )

        // Indefinite-length arrays are never part of the protocol.
        XCTAssertThrowsError(
            try FabricLinkCanonicalCBOR.decode(
                Data([0x9f, 0x01, 0xff]),
                maximum: 16
            )
        )
    }

    func testGeneratedOpenMLSCoreMatchesProtocolContract() {
        XCTAssertEqual(
            fabricLinkProtocolVersion(),
            UInt16(FabricLinkWire.protocolVersion)
        )
        XCTAssertEqual(
            fabricLinkCiphersuite(),
            FabricLinkWire.ciphersuite
        )
        XCTAssertEqual(
            fabricLinkBuildInfo().cryptoBackend,
            "OpenMLS/RustCrypto"
        )
    }

    func testLinkPairingDescriptionsNeverRevealQRSecret() throws {
        let fixture = try fixture()
        let pairing = try FabricLinkPairing.parse(
            try XCTUnwrap(fixture["pairing_url"] as? String),
            now: try XCTUnwrap(fixture["pairing_now"] as? Int)
        )
        let secret = try XCTUnwrap(fixture["pairing_secret_hex"] as? String)

        XCTAssertFalse(String(describing: pairing).contains(secret))
        XCTAssertFalse(String(reflecting: pairing).contains(secret))
        XCTAssertFalse(String(describing: pairing).contains("pair="))
    }

    func testRelayCursorDoesNotSkipRowsBeyondOneBoundedPage() {
        XCTAssertEqual(
            fabricLinkAdvanceBoundedCursor(
                afterSequence: 0,
                deliveredSequences: Array(1...10),
                highWatermark: 11
            ),
            10
        )
        XCTAssertEqual(
            fabricLinkAdvanceBoundedCursor(
                afterSequence: 10,
                deliveredSequences: [],
                highWatermark: 11
            ),
            11
        )
    }

    private func fixture() throws -> [String: Any] {
        let url = try XCTUnwrap(
            Bundle(for: Self.self).url(
                forResource: "v3-interoperability",
                withExtension: "json"
            )
        )
        let object = try JSONSerialization.jsonObject(
            with: Data(contentsOf: url)
        )
        return try XCTUnwrap(object as? [String: Any])
    }

    private func hex(
        _ fixture: [String: Any],
        _ key: String
    ) throws -> Data {
        let value = try XCTUnwrap(fixture[key] as? String)
        guard value.count.isMultiple(of: 2) else {
            throw FabricLinkError.invalidRecord
        }
        var data = Data()
        data.reserveCapacity(value.count / 2)
        var index = value.startIndex
        while index < value.endIndex {
            let next = value.index(index, offsetBy: 2)
            guard let byte = UInt8(value[index..<next], radix: 16) else {
                throw FabricLinkError.invalidRecord
            }
            data.append(byte)
            index = next
        }
        return data
    }
}
