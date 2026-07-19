import XCTest
@testable import Fabric

final class PairingPayloadTests: XCTestCase {
    func testParsesBrowserLandingURLWithoutChangingPayload() throws {
        let pairing = "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=token&token=secret%2Fvalue"
        let encoded = pairing.addingPercentEncoding(withAllowedCharacters: .alphanumerics)!

        let payload = try XCTUnwrap(PairingPayload.parse("https://agent.example.test/mobile/pair#pair=\(encoded)"))

        XCTAssertEqual(payload.baseURL.absoluteString, "https://agent.example.test")
        XCTAssertEqual(payload.token, "secret/value")
    }

    func testRejectsLandingURLOutsideMobilePairRoute() {
        let pairing = "fabric%3A%2F%2Fpair%3Fv%3D1%26url%3Dhttps%253A%252F%252Fagent.example.test"
        XCTAssertNil(PairingPayload.parse("https://agent.example.test/other#pair=\(pairing)"))
    }

    func testRejectsUnknownVersionAndCredentialBearingGatewayURL() {
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test"
        ))
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair?v=1&url=https%3A%2F%2Fuser%3Apass%40agent.example.test"
        ))
    }
}
