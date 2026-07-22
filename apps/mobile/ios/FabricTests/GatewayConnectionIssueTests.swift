import XCTest
@testable import Fabric

final class GatewayConnectionIssueTests: XCTestCase {
    private let gateway = SavedGateway(
        id: "gateway-1",
        label: "Studio Mac",
        baseURL: URL(string: "https://studio.example.test")!,
        authMode: .gated,
        username: "operator"
    )

    func testOfflineFailureHasConcreteRecoveryWithoutRawDiagnostic() {
        let error = URLError(.notConnectedToInternet, userInfo: [
            NSLocalizedDescriptionKey: "SECRET RAW NETWORK DETAIL",
        ])

        let message = GatewayConnectionIssue.message(for: error, gateway: gateway)

        XCTAssertEqual(
            message,
            "This iPhone is offline. Reconnect to Wi-Fi or your tailnet, then try again."
        )
        XCTAssertFalse(message.contains("SECRET"))
    }

    func testHTTPBodyNeverReachesConnectionCopy() {
        let error = GatewayAPIError.httpStatus(
            500,
            body: "token=do-not-render password=also-secret"
        )

        let message = GatewayConnectionIssue.message(for: error, gateway: gateway)

        XCTAssertEqual(
            message,
            "The Fabric gateway at studio.example.test returned an error. Check the gateway, then retry."
        )
        XCTAssertFalse(message.contains("token"))
        XCTAssertFalse(message.contains("password"))
    }

    func testAuthenticationFailuresRequestSignIn() {
        XCTAssertTrue(GatewayConnectionIssue.requiresSignIn(
            GatewayAPIError.httpStatus(401, body: "expired cookie")
        ))
        XCTAssertTrue(GatewayConnectionIssue.requiresSignIn(
            GatewayClientError.rpc(message: "Sign in to reconnect.")
        ))
        XCTAssertFalse(GatewayConnectionIssue.requiresSignIn(URLError(.timedOut)))
    }

    func testContractFailureUsesFixedCopyWithoutEchoingServerMessage() {
        let error = GatewayClientError.rpc(
            message: "Requires mobile contract 9; token=do-not-render"
        )

        let message = GatewayConnectionIssue.message(for: error, gateway: gateway)

        XCTAssertEqual(
            message,
            "This gateway requires a newer Fabric Mobile contract. Update Fabric Mobile before reconnecting."
        )
        XCTAssertFalse(message.contains("token"))
        XCTAssertFalse(message.contains("do-not-render"))
    }
}
