import XCTest
@testable import Fabric

final class PairingFlowModelTests: XCTestCase {
    func testAcceptsTokenPairingWithoutExposingCredentialInDescriptions() throws {
        let credential = "camera-secret/value"
        let raw = tokenPairing(token: credential)
        let input = PairingFlowInput.scan(raw)
        let outcome = PairingFlowModel(gateways: []).accept(input)

        guard case .token(let acceptance) = outcome else {
            return XCTFail("Expected token acceptance, got \(outcome)")
        }
        XCTAssertEqual(
            acceptance.target,
            .new(baseURL: try XCTUnwrap(URL(string: "https://agent.example.test")))
        )
        XCTAssertEqual(acceptance.withUnsafeToken { $0 }, credential)

        for description in [
            String(describing: input),
            String(reflecting: input),
            String(describing: acceptance),
            String(reflecting: acceptance),
            String(describing: outcome),
            String(reflecting: outcome),
        ] {
            XCTAssertFalse(description.contains(credential), description)
            XCTAssertFalse(description.contains("fabric://"), description)
        }
    }

    func testAcceptsGatedPairingWithoutInventingACredential() throws {
        let outcome = PairingFlowModel(gateways: []).accept(.scan(gatedPairing()))

        XCTAssertEqual(
            outcome,
            .gated(.new(baseURL: try XCTUnwrap(URL(string: "https://agent.example.test"))))
        )
    }

    func testInvalidPayloadFailsClosedWithoutEchoingRawInput() {
        let credential = "must-not-be-echoed"
        let input = PairingFlowInput.scan(
            "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&token=\(credential)"
        )
        let outcome = PairingFlowModel(gateways: []).accept(input)

        XCTAssertEqual(outcome, .invalid)
        XCTAssertFalse(String(describing: input).contains(credential))
        XCTAssertFalse(String(reflecting: input).contains(credential))
        XCTAssertFalse(String(describing: outcome).contains(credential))
    }

    func testV2EnrollmentFailsClosedWithoutRetainingOpaqueHandle() throws {
        let handle = String(repeating: "E", count: 43)
        let raw = "fabric://pair?v=2&url=https%3A%2F%2Fagent.example.test&enrollment=\(handle)&auth=browser"
        let outcome = PairingFlowModel(gateways: []).accept(.scan(raw))

        XCTAssertEqual(
            outcome,
            .unsupportedEnrollment(
                .new(baseURL: try XCTUnwrap(URL(string: "https://agent.example.test")))
            )
        )
        XCTAssertFalse(String(describing: outcome).contains(handle))
        XCTAssertFalse(String(reflecting: outcome).contains(handle))
    }

    func testKnownEndpointBecomesExplicitTokenRePair() throws {
        let existing = SavedGateway(
            id: "existing-gateway",
            label: "Existing",
            baseURL: try XCTUnwrap(URL(string: "HTTPS://Agent.Example.Test:443/")),
            authMode: .gated,
            username: "operator"
        )
        let outcome = PairingFlowModel(gateways: [existing]).accept(
            .scan(tokenPairing(token: "replacement-token"))
        )

        guard case .token(let acceptance) = outcome else {
            return XCTFail("Expected token re-pair, got \(outcome)")
        }
        XCTAssertEqual(acceptance.target.existingGatewayID, existing.id)
        XCTAssertEqual(acceptance.target.baseURL.absoluteString, "https://agent.example.test")
    }

    func testKnownEndpointBecomesExplicitGatedRePair() throws {
        let existing = SavedGateway(
            id: "existing-gateway",
            label: "Existing",
            baseURL: try XCTUnwrap(URL(string: "https://agent.example.test/")),
            authMode: .token
        )
        let outcome = PairingFlowModel(gateways: [existing]).accept(.scan(gatedPairing()))

        XCTAssertEqual(
            outcome,
            .gated(
                .rePair(
                    existingGatewayID: existing.id,
                    baseURL: try XCTUnwrap(URL(string: "https://agent.example.test"))
                )
            )
        )
    }

    func testCameraAndDeepLinkUseTheSameClassifier() throws {
        let raw = tokenPairing(token: "same-one-time-input")
        let model = PairingFlowModel(gateways: [])

        let cameraOutcome = model.accept(.scan(raw))
        let deepLinkOutcome = model.accept(.deepLink(try XCTUnwrap(URL(string: raw))))

        XCTAssertEqual(cameraOutcome, deepLinkOutcome)
    }

    func testExecutionGateRejectsConcurrentDuplicateEndpointThenAllowsRetry() throws {
        let target = PairingFlowTarget.new(
            baseURL: try XCTUnwrap(URL(string: "https://agent.example.test"))
        )
        let cosmeticDuplicate = PairingFlowTarget.rePair(
            existingGatewayID: "existing",
            baseURL: try XCTUnwrap(URL(string: "HTTPS://AGENT.EXAMPLE.TEST:443/"))
        )
        var gate = PairingFlowExecutionGate()

        XCTAssertTrue(gate.begin(target))
        XCTAssertFalse(gate.begin(cosmeticDuplicate))

        gate.finish(target)
        XCTAssertTrue(gate.begin(cosmeticDuplicate))
    }

    private func tokenPairing(token: String) -> String {
        var components = URLComponents()
        components.scheme = "fabric"
        components.host = "pair"
        components.queryItems = [
            URLQueryItem(name: "v", value: "1"),
            URLQueryItem(name: "url", value: "https://agent.example.test"),
            URLQueryItem(name: "auth", value: "token"),
            URLQueryItem(name: "token", value: token),
        ]
        return components.string!
    }

    private func gatedPairing() -> String {
        "fabric://pair?v=1&url=https%3A%2F%2Fagent.example.test&auth=gated"
    }
}
