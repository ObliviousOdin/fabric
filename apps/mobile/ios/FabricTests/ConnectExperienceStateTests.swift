import AVFoundation
import XCTest
@testable import Fabric

final class ConnectExperienceStateTests: XCTestCase {
    func testRejectedScannerCodeRequiresExplicitVisibleRetryBeforeAnotherDelivery() {
        var feedback = PairingScannerFeedbackState()

        feedback.receive(.retry(message: "Scan a new Fabric code."))

        XCTAssertEqual(feedback.message, "Scan a new Fabric code.")
        XCTAssertEqual(feedback.scanGeneration, 0)

        feedback.retry()

        XCTAssertNil(feedback.message)
        XCTAssertEqual(feedback.scanGeneration, 1)
    }

    func testScannerDeliversOnlyOnceUntilVisibleRetryAdvancesGeneration() {
        var gate = PairingScannerDeliveryGate()

        XCTAssertTrue(gate.beginDelivery())
        XCTAssertFalse(gate.beginDelivery())

        gate.reset(to: 1)

        XCTAssertFalse(gate.hasDelivered)
        XCTAssertTrue(gate.beginDelivery())
        XCTAssertFalse(gate.beginDelivery())
    }

    func testSavedGatewayStateNeverClaimsUnverifiedReachability() {
        XCTAssertEqual(
            ConnectGatewayAvailability(authMode: .token, canAutoConnect: true),
            .ready
        )
        XCTAssertEqual(
            ConnectGatewayAvailability(authMode: .token, canAutoConnect: false),
            .credentialRequired
        )
        XCTAssertEqual(
            ConnectGatewayAvailability(
                authMode: .token,
                canAutoConnect: true,
                allowsTokenCredential: false
            ),
            .secureTransportRequired
        )
        XCTAssertEqual(
            ConnectGatewayAvailability(authMode: .gated, canAutoConnect: true),
            .savedSignIn
        )
        XCTAssertEqual(
            ConnectGatewayAvailability(
                authMode: .gated,
                canAutoConnect: false,
                hasStoredPassword: true
            ),
            .ready
        )

        for state in [
            ConnectGatewayAvailability.ready,
            .credentialRequired,
            .secureTransportRequired,
            .savedSignIn,
        ] {
            XCTAssertFalse(state.label.localizedCaseInsensitiveContains("online"))
            XCTAssertFalse(state.detail.localizedCaseInsensitiveContains("online"))
        }
    }

    func testLegacyPlaintextTokenRowExplainsSecureRepair() {
        let state = ConnectGatewayAvailability(
            authMode: .token,
            canAutoConnect: false,
            allowsTokenCredential: false
        )

        XCTAssertEqual(state.label, "Secure address required")
        XCTAssertTrue(state.detail.contains("HTTPS"))
        XCTAssertTrue(state.detail.contains("Re-pair"))
    }

    func testCameraAuthorizationMapsToExplicitUIStates() {
        XCTAssertEqual(ConnectCameraPermissionState(.notDetermined), .notDetermined)
        XCTAssertEqual(ConnectCameraPermissionState(.authorized), .authorized)
        XCTAssertEqual(ConnectCameraPermissionState(.denied), .denied)
        XCTAssertEqual(ConnectCameraPermissionState(.restricted), .restricted)
    }

    func testDeniedCameraOffersSettingsAndManualRecovery() {
        let copy = ConnectCameraRecoveryCopy.value(for: .denied)

        XCTAssertTrue(copy.showsSettingsAction)
        XCTAssertTrue(copy.message.contains("Settings"))
        XCTAssertFalse(copy.message.localizedCaseInsensitiveContains("required to continue"))
    }

    func testRestrictedAndUnavailableCameraDoNotPromiseSettingsCanFixIt() {
        for state in [ConnectCameraPermissionState.restricted, .unavailable] {
            let copy = ConnectCameraRecoveryCopy.value(for: state)
            XCTAssertFalse(copy.showsSettingsAction)
            XCTAssertTrue(copy.message.contains("Advanced setup"))
        }
    }

    func testRouteDiagnosisGivesSpecificOfflineRecoveryWithoutRawError() {
        let underlying = "credential-must-never-appear"
        let error = URLError(
            .notConnectedToInternet,
            userInfo: [NSLocalizedDescriptionKey: underlying]
        )

        let message = ConnectRouteDiagnosis.message(for: error)

        XCTAssertTrue(message.contains("offline"))
        XCTAssertTrue(message.contains("Wi-Fi"))
        XCTAssertFalse(message.contains(underlying))
    }

    func testUnknownRouteFailureUsesBoundedRecoveryCopy() {
        struct UnexpectedFailure: LocalizedError {
            let errorDescription: String? = "token=do-not-echo"
        }

        let message = ConnectRouteDiagnosis.message(for: UnexpectedFailure())

        XCTAssertTrue(message.contains("same network or tailnet"))
        XCTAssertFalse(message.contains("do-not-echo"))
    }

    func testEndpointRequestFenceRejectsStaleAndOutOfOrderDiscoveryResults() throws {
        let gatewayA = try XCTUnwrap(URL(string: "https://gateway-a.example.test"))
        let gatewayB = try XCTUnwrap(URL(string: "https://gateway-b.example.test"))
        var fence = GatewayEndpointRequestFence()

        let firstA = fence.begin(for: gatewayA)
        let requestB = fence.begin(for: gatewayB)

        XCTAssertFalse(fence.accepts(firstA, currentURL: gatewayB))
        XCTAssertTrue(fence.accepts(requestB, currentURL: gatewayB))

        // Returning to the same endpoint must not resurrect the first A
        // request after a newer generation has already started.
        let secondA = fence.begin(for: gatewayA)
        XCTAssertFalse(fence.accepts(firstA, currentURL: gatewayA))
        XCTAssertFalse(fence.accepts(requestB, currentURL: gatewayA))
        XCTAssertTrue(fence.accepts(secondA, currentURL: gatewayA))

        fence.invalidate()
        XCTAssertFalse(fence.accepts(secondA, currentURL: gatewayA))
        XCTAssertFalse(fence.accepts(secondA, currentURL: gatewayA, applicable: false))
    }

    func testEndpointChangeClearsEveryCredentialEvenWhenItsModeIsHidden() {
        var credentials = GatewayEndpointCredentialState(
            token: "token-for-a",
            username: "operator-a",
            password: "password-for-a",
            otp: "123456",
            scannedGatewayID: "saved-retry-a"
        )

        XCTAssertTrue(credentials.resetIfEndpointChanged(
            from: "https://gateway-a.example.test",
            to: "https://gateway-b.example.test"
        ))
        XCTAssertEqual(credentials, GatewayEndpointCredentialState())
    }

    func testCosmeticSameEndpointEditPreservesCredentialAuthority() {
        var credentials = GatewayEndpointCredentialState(
            token: "same-endpoint-token",
            username: "operator",
            password: "same-endpoint-password",
            otp: "654321",
            scannedGatewayID: "same-endpoint-retry"
        )
        let original = credentials

        XCTAssertFalse(credentials.resetIfEndpointChanged(
            from: "HTTPS://Gateway.Example.Test:443/fabric/",
            to: "https://gateway.example.test/fabric"
        ))
        XCTAssertEqual(credentials, original)
    }

    func testAmbiguousPartialEndpointEditFailsClosed() {
        var credentials = GatewayEndpointCredentialState(
            token: "must-clear",
            password: "must-clear-too"
        )

        XCTAssertTrue(credentials.resetIfEndpointChanged(
            from: "https://gateway-a.example.test",
            to: "https://"
        ))
        XCTAssertEqual(credentials, GatewayEndpointCredentialState())
    }

#if DEBUG
    func testDisposableE2EPairingLaunchAcceptsSeparatedArgument() throws {
        let expected = try XCTUnwrap(
            URL(string: "fabric://pair?v=1&url=http%3A%2F%2F127.0.0.1%3A9129&auth=token&token=disposable")
        )

        let parsed = FabricUIDebugPairingLaunch.requestedURL(
            arguments: ["Fabric", "-fabric-e2e-pairing-url", expected.absoluteString],
            environment: [:]
        )

        XCTAssertEqual(parsed, expected)
    }

    func testDisposableE2EPairingLaunchAcceptsSimulatorEnvironmentFallback() throws {
        let expected = try XCTUnwrap(
            URL(string: "fabric://pair?v=1&url=http%3A%2F%2F127.0.0.1%3A9129&auth=token&token=disposable")
        )

        let parsed = FabricUIDebugPairingLaunch.requestedURL(
            arguments: ["Fabric"],
            environment: ["FABRIC_E2E_PAIRING_URL": expected.absoluteString]
        )

        XCTAssertEqual(parsed, expected)
    }
#endif
}
