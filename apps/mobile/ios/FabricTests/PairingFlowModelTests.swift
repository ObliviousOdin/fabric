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
        guard case .gated(let target) = outcome else {
            return XCTFail("Expected gated re-pair")
        }
        XCTAssertEqual(target.existingUsername(in: [existing]), "")
    }

    func testGatedEntryPointsShareSavedUsernameAndClearNewEndpointState() throws {
        let existing = SavedGateway(
            id: "existing-gateway",
            label: "Existing",
            baseURL: try XCTUnwrap(URL(string: "https://agent.example.test")),
            authMode: .gated,
            username: "operator"
        )
        let model = PairingFlowModel(gateways: [existing])
        let raw = gatedPairing()

        guard
            case .gated(let scanTarget) = model.accept(.scan(raw)),
            case .gated(let deepLinkTarget) = model.accept(
                .deepLink(try XCTUnwrap(URL(string: raw)))
            )
        else { return XCTFail("Expected gated pairing targets") }

        XCTAssertEqual(scanTarget, deepLinkTarget)
        XCTAssertEqual(scanTarget.existingUsername(in: [existing]), "operator")
        XCTAssertEqual(
            PairingFlowTarget.new(
                baseURL: try XCTUnwrap(URL(string: "https://new.example.test"))
            ).existingUsername(in: [existing]),
            ""
        )
    }

    func testCameraAndDeepLinkUseTheSameClassifier() throws {
        let raw = tokenPairing(token: "same-one-time-input")
        let model = PairingFlowModel(gateways: [])

        let cameraOutcome = model.accept(.scan(raw))
        let deepLinkOutcome = model.accept(.deepLink(try XCTUnwrap(URL(string: raw))))

        XCTAssertEqual(cameraOutcome, deepLinkOutcome)
    }

    func testExecutionGateRejectsConcurrentDuplicateEndpointThenAllowsRetry() async throws {
        let target = PairingFlowTarget.new(
            baseURL: try XCTUnwrap(URL(string: "https://agent.example.test"))
        )
        let cosmeticDuplicate = PairingFlowTarget.rePair(
            existingGatewayID: "existing",
            baseURL: try XCTUnwrap(URL(string: "HTTPS://AGENT.EXAMPLE.TEST:443/"))
        )
        let gateway = SavedGateway(
            label: "Agent",
            baseURL: target.baseURL,
            authMode: .token
        )
        let gate = PairingFlowExecutionGate()
        var nestedResult: PairingTokenConnectResult?

        let outerResult = await gate.execute(target) {
            nestedResult = await gate.execute(cosmeticDuplicate) {
                XCTFail("Duplicate endpoint operation must not execute")
                return .attempted(gateway)
            }
            return .attempted(gateway)
        }
        XCTAssertEqual(outerResult, .attempted(gateway))
        XCTAssertEqual(nestedResult, .alreadyInFlight)

        let retryResult = await gate.execute(cosmeticDuplicate) {
            .attempted(gateway)
        }
        XCTAssertEqual(retryResult, .attempted(gateway))
    }

    func testExecutionGateCleanupAllowsRetryAfterFailure() async throws {
        enum ExpectedFailure: Error { case storage }

        let target = PairingFlowTarget.new(
            baseURL: try XCTUnwrap(URL(string: "https://agent.example.test"))
        )
        let gateway = SavedGateway(
            label: "Agent",
            baseURL: target.baseURL,
            authMode: .token
        )
        let gate = PairingFlowExecutionGate()

        do {
            _ = try await gate.execute(target) {
                throw ExpectedFailure.storage
            }
            XCTFail("Expected storage failure")
        } catch ExpectedFailure.storage {
            // Expected. The retry below proves the production defer released
            // the endpoint permit on the throwing path.
        }

        let retryResult = await gate.execute(target) {
            .attempted(gateway)
        }
        XCTAssertEqual(retryResult, .attempted(gateway))
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
