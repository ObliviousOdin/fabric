import XCTest
@testable import Fabric

final class ConnectedGatewayIntroPresentationTests: XCTestCase {
    func testCompletingIntroAlwaysSelectsHomeForTheConnectedShell() throws {
        let suiteName = "ConnectedAppShellSelectionTests-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        defaults.set(ConnectedAppTab.settings.rawValue, forKey: ConnectedAppShellSelection.storageKey)

        ConnectedAppShellSelection.resetForCompletedIntro(defaults: defaults)

        XCTAssertEqual(
            defaults.string(forKey: ConnectedAppShellSelection.storageKey),
            ConnectedAppTab.home.rawValue
        )
    }

    func testSessionExecutionSummaryUsesEveryNegotiatedExecutionField() {
        let negotiation = GatewayCapabilityNegotiation.verified(
            GatewayCapabilities(
                contract: GatewayCapabilityContract(
                    name: "fabric.gateway",
                    version: 1,
                    minimumCompatibleVersion: 1
                ),
                server: GatewayServerContract(version: "9.1.0", releaseDate: "2026-07-21"),
                execution: GatewayExecutionContract(
                    location: "unknown",
                    toolExecution: "unknown",
                    survivesClientDisconnect: false,
                    survivesGatewayRestart: true,
                    requiresGatewayHostOnline: false
                ),
                features: [:],
                methods: legacyMobileMethods
            )
        )

        let summary = SessionGatewayExecutionPresentation.value(for: negotiation)

        XCTAssertEqual(summary.title, "Execution location not verified")
        XCTAssertTrue(summary.body.contains("did not provide a verified execution location"))
        XCTAssertTrue(summary.body.contains("may stop when this iPhone disconnects"))
        XCTAssertTrue(summary.body.contains("survives a gateway restart"))
        XCTAssertTrue(summary.body.contains("Server 9.1.0"))
        XCTAssertFalse(summary.body.contains("Active work continues"))
        XCTAssertFalse(summary.body.contains("Keep the gateway host online"))
    }


    func testLegacyGatewayNeverClaimsVerifiedExecutionOrContinuity() {
        let facts = ConnectedGatewayIntroPresentation.executionFacts(for: .legacy)
        let copy = facts.map { "\($0.title) \($0.detail)" }.joined(separator: " ")

        XCTAssertTrue(copy.contains("not verified"))
        XCTAssertFalse(copy.contains("Fabric runs on this gateway"))
        XCTAssertFalse(copy.contains("You can leave the app"))
        XCTAssertFalse(copy.contains("can continue after this client disconnects"))
    }

    func testVerifiedGatewayUsesAdvertisedExecutionBooleans() {
        let negotiation = GatewayCapabilityNegotiation.verified(GatewayCapabilities(
            contract: GatewayCapabilityContract(
                name: "fabric.gateway",
                version: 1,
                minimumCompatibleVersion: 1
            ),
            server: GatewayServerContract(version: "1.0.0", releaseDate: "2026-07-21"),
            execution: GatewayExecutionContract(
                location: "gateway",
                toolExecution: "gateway",
                survivesClientDisconnect: false,
                survivesGatewayRestart: true,
                requiresGatewayHostOnline: false
            ),
            features: [:],
            methods: legacyMobileMethods
        ))

        let facts = ConnectedGatewayIntroPresentation.executionFacts(for: negotiation)

        XCTAssertEqual(facts[0].title, "Fabric runs on this gateway")
        XCTAssertEqual(facts[1].title, "Stay connected while work runs")
        XCTAssertTrue(facts[2].detail.contains("survives a gateway restart"))
    }
}
