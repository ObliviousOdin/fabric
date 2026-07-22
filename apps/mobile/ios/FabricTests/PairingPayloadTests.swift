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

    func testRejectsDirectServerAddresses() {
        XCTAssertNil(PairingPayload.parse("https://agent.example.test"))
        XCTAssertNil(PairingPayload.parse("https://agent.example.test?token=secret"))
    }

    func testRejectsMissingOrContradictoryAuthenticationPayloads() {
        let invalid = [
            "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=token",
            "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=gated&token=unexpected",
            "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=other",
            "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test",
        ]

        for pairing in invalid {
            XCTAssertNil(PairingPayload.parse(pairing))
        }
    }

    func testRecognizesStrictV2EnrollmentWithoutCreatingALegacyCredential() throws {
        let handle = String(repeating: "A", count: 43)
        let payload = try XCTUnwrap(PairingPayload.parse(
            "fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test&enrollment=\(handle)&auth=browser"
        ))

        XCTAssertNil(payload.token)
        XCTAssertFalse(payload.gated)
        XCTAssertEqual(payload.enrollment?.handle, handle)
        XCTAssertEqual(payload.enrollment?.auth, .browser)
    }

    func testAgreesWithCanonicalV2PairingCorpus() throws {
        let fixtureURL = try pairingV2FixtureURL()
        let fixture = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: fixtureURL)) as? [String: Any]
        )
        let cases = try XCTUnwrap(fixture["cases"] as? [[String: Any]])

        for fixtureCase in cases {
            let id = try XCTUnwrap(fixtureCase["id"] as? String)
            let raw = try XCTUnwrap(fixtureCase["payload"] as? String)
            let valid = try XCTUnwrap(fixtureCase["valid"] as? Bool)
            let parsed = PairingPayload.parse(raw)
            if valid {
                XCTAssertNotNil(parsed?.enrollment, id)
                XCTAssertNil(parsed?.token, id)
            } else {
                XCTAssertNil(parsed, id)
            }
        }
    }

    private func pairingV2FixtureURL() throws -> URL {
        if let bundled = Bundle(for: Self.self).url(
            forResource: "fabric-pairing-v2",
            withExtension: "json"
        ) {
            return bundled
        }

        // The XcodeGen manifest bundles this fixture in CI. The source fallback
        // keeps a local `xcodebuild` run deterministic when XcodeGen is not
        // installed and the derived project has not yet been regenerated.
        let sourceFixture = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("contracts/fabric-pairing-v2.json")
        guard FileManager.default.fileExists(atPath: sourceFixture.path) else {
            throw NSError(
                domain: "FabricTests",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Missing canonical v2 pairing fixture"]
            )
        }
        return sourceFixture
    }

    func testRejectsUnknownVersionAndCredentialBearingGatewayURL() {
        let validEnrollment = String(repeating: "A", count: 43)
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test"
        ))
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair?v=2&url=http%3A%2F%2Fagent.example.test&enrollment=\(validEnrollment)&auth=browser"
        ))
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test&enrollment=short&auth=browser"
        ))
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test&enrollment=\(validEnrollment)&auth=browser&token=unexpected"
        ))
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair/?v=2&url=https%3A%2F%2Fagent.example.test&enrollment=\(validEnrollment)&auth=browser"
        ))
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test%2F%2F%2F&enrollment=\(validEnrollment)&auth=browser"
        ))
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair?v=1&url=https%3A%2F%2Fuser%3Apass%40agent.example.test"
        ))
    }

    func testValidatesManualServerAddressesSeparately() {
        XCTAssertEqual(
            GatewayBaseURL.parse(" https://agent.example.test/fabric/ ")?.absoluteString,
            "https://agent.example.test/fabric/"
        )
        XCTAssertNil(GatewayBaseURL.parse("fabric://pair?v=1"))
        XCTAssertNil(GatewayBaseURL.parse("https://user:pass@agent.example.test"))
        XCTAssertNil(GatewayBaseURL.parse("https://agent.example.test?token=secret"))
        XCTAssertNil(GatewayBaseURL.parse("https://agent.example.test/#fragment"))
    }

    func testTokenPairingRejectsPlaintextNetworkHostsButAllowsLoopbackDevelopment() {
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair?v=1&url=http%3A%2F%2F192.168.1.20%3A9119&auth=token&token=secret"
        ))
        XCTAssertNotNil(PairingPayload.parse(
            "fabric://pair?v=1&url=http%3A%2F%2F127.0.0.1%3A9119&auth=token&token=secret"
        ))
        XCTAssertNotNil(PairingPayload.parse(
            "fabric://pair?v=1&url=https%3A%2F%2Ffabric.example.test&auth=token&token=secret"
        ))
    }

    func testLoopbackClassificationRequiresAnActualCanonicalLoopbackAddress() throws {
        for value in [
            "http://localhost:9119",
            "http://[::1]:9119",
            "http://127.0.0.1:9119",
            "http://127.255.255.255:9119",
        ] {
            let url = try XCTUnwrap(URL(string: value))
            XCTAssertTrue(GatewayBaseURL.isLoopback(url), value)
        }

        for value in [
            "http://127.attacker.example:9119",
            "http://localhost.attacker.example:9119",
            "http://127.0.0:9119",
            "http://127.0.0.1.2:9119",
            "http://127..0.1:9119",
            "http://127.00.0.1:9119",
            "http://127.0.0.256:9119",
            "http://128.0.0.1:9119",
        ] {
            let url = try XCTUnwrap(URL(string: value))
            XCTAssertFalse(GatewayBaseURL.isLoopback(url), value)
        }
    }

    func testTokenTransportPolicyIsSharedAcrossSavedAndPairingPaths() throws {
        for value in [
            "https://fabric.example.test",
            "http://localhost:9119",
            "http://127.0.0.1:9119",
            "http://[::1]:9119",
        ] {
            XCTAssertTrue(
                GatewayBaseURL.allowsTokenCredential(try XCTUnwrap(URL(string: value))),
                value
            )
        }

        for value in [
            "http://192.168.1.20:9119",
            "http://127.attacker.example:9119",
            "ftp://localhost:9119",
        ] {
            XCTAssertFalse(
                GatewayBaseURL.allowsTokenCredential(try XCTUnwrap(URL(string: value))),
                value
            )
        }
    }

    func testTokenWebSocketBuilderRejectsRemotePlaintextWithoutLeakingCredential() throws {
        let baseURL = try XCTUnwrap(URL(string: "http://192.168.1.20:9119"))
        let credential = "top-secret-upgrade-token"

        XCTAssertThrowsError(try GatewayAPI.websocketURL(baseURL: baseURL, token: credential)) { error in
            XCTAssertEqual(error as? GatewayTokenTransportError, .secureTransportRequired)
            XCTAssertFalse(error.localizedDescription.contains(credential))
            XCTAssertTrue(error.localizedDescription.contains("HTTPS"))
        }
    }

    func testTokenWebSocketBuilderStillAllowsHTTPSAndLoopbackDevelopment() throws {
        let https = try GatewayAPI.websocketURL(
            baseURL: try XCTUnwrap(URL(string: "https://fabric.example.test/prefix")),
            token: "https-token"
        )
        let loopback = try GatewayAPI.websocketURL(
            baseURL: try XCTUnwrap(URL(string: "http://127.0.0.1:9119")),
            token: "loopback-token"
        )

        XCTAssertEqual(https.scheme, "wss")
        XCTAssertEqual(https.path, "/prefix/api/ws")
        XCTAssertEqual(loopback.scheme, "ws")
        XCTAssertEqual(loopback.host(), "127.0.0.1")
    }

    func testWebSocketBuilderNormalizesAcceptedSchemeCase() throws {
        let tokenURL = try GatewayAPI.websocketURL(
            baseURL: try XCTUnwrap(URL(string: "HTTPS://fabric.example.test")),
            token: "uppercase-token"
        )
        let ticketURL = try GatewayAPI.websocketURL(
            baseURL: try XCTUnwrap(URL(string: "HTTP://fabric.example.test")),
            ticket: "single-use-ticket"
        )

        XCTAssertEqual(tokenURL.scheme, "wss")
        XCTAssertEqual(ticketURL.scheme, "ws")
        XCTAssertEqual(ticketURL.host(), "fabric.example.test")
    }

    func testRemotePlaintextRejectsReusableTokenButKeepsTicketBuilderContract() throws {
        let baseURL = try XCTUnwrap(URL(string: "http://fabric.example.test"))

        XCTAssertThrowsError(try GatewayAPI.websocketURL(baseURL: baseURL, token: "reusable-token")) {
            XCTAssertEqual($0 as? GatewayTokenTransportError, .secureTransportRequired)
        }
        let ticketURL = try GatewayAPI.websocketURL(baseURL: baseURL, ticket: "single-use-ticket")
        XCTAssertEqual(ticketURL.absoluteString, "ws://fabric.example.test/api/ws?ticket=single-use-ticket")
    }

    func testDeceptive127PrefixCannotCarryTokenOverPlaintextHTTP() {
        XCTAssertNil(PairingPayload.parse(
            "fabric://pair?v=1&url=http%3A%2F%2F127.attacker.example%3A9119&auth=token&token=secret"
        ))
    }
}
