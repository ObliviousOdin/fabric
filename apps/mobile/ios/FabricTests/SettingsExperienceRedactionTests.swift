import Foundation
import XCTest
@testable import Fabric

final class SettingsExperienceRedactionTests: XCTestCase {
    @MainActor
    func testReportIsWhitelistBuiltAndOmitsPrivateGatewayAndConversationData() throws {
        let privateLabel = "Private Studio"
        let privateHost = "odin.private-tailnet.test"
        let privateCredential = "camera-secret-value"
        let gateway = SavedGateway(
            id: "private-server-identifier",
            label: privateLabel,
            baseURL: try XCTUnwrap(URL(
                string: "https://\(privateHost)/fabric?token=\(privateCredential)"
            )),
            authMode: .token
        )
        let presentation = SettingsExperiencePresentation(
            gateway: gateway,
            phase: .connected,
            negotiation: .verified(capabilities),
            clientBuild: SettingsClientBuildInfo(
                version: "0.2.0",
                build: "42",
                sourceRevision: "0123456789abcdef"
            )
        )
        let report = SettingsDiagnosticsReport.make(
            presentation: presentation,
            permissions: permissions,
            environment: SettingsDiagnosticsEnvironment(
                operatingSystem: "iOS 26.5 (Build 23F79)",
                generatedAt: Date(timeIntervalSince1970: 1_721_600_000)
            )
        )

        XCTAssertTrue(report.contains("Fabric Mobile Diagnostics (redacted)"))
        XCTAssertTrue(report.contains("app_version: 0.2.0"))
        XCTAssertTrue(report.contains("connection_state: connected"))
        XCTAssertTrue(report.contains("gateway_identity: [redacted]"))
        XCTAssertTrue(report.contains("execution_contract: verified"))
        XCTAssertTrue(report.contains("camera_permission: denied"))
        XCTAssertTrue(report.contains("microphone_permission: denied"))
        XCTAssertTrue(report.contains("speech_recognition_permission: denied"))
        XCTAssertTrue(report.contains("local_network_permission: notInspectable"))

        for privateValue in [
            privateLabel,
            privateHost,
            privateCredential,
            gateway.id,
            gateway.baseURL.absoluteString,
            "prompt text",
            "session-private-id",
            "raw RPC failure",
        ] {
            XCTAssertFalse(report.contains(privateValue), privateValue)
        }
    }

    func testDefensiveRedactorRemovesCredentialPairingAndConversationShapes() {
        let jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwcml2YXRlIn0.c2lnbmF0dXJl"
        let raw = """
        token: token-value
        password=hunter2
        cookie: session-cookie
        ticket: websocket-ticket
        authorization: Bearer bearer-value
        api_key: api-secret
        prompt: user private prompt
        transcript: user private transcript
        session_id: private-session
        pairing: fabric://pair?v=1&url=https://private.test&token=camera-secret
        jwt: \(jwt)
        safe_field: retained
        """

        let redacted = SettingsDiagnosticsRedactor.redact(raw)

        for secret in [
            "token-value",
            "hunter2",
            "session-cookie",
            "websocket-ticket",
            "bearer-value",
            "api-secret",
            "user private prompt",
            "user private transcript",
            "private-session",
            "camera-secret",
            jwt,
        ] {
            XCTAssertFalse(redacted.contains(secret), secret)
        }
        XCTAssertTrue(redacted.contains("safe_field: retained"))
        XCTAssertTrue(redacted.contains("[redacted pairing URL]"))
    }

    @MainActor
    func testUnsafeMetadataCannotInjectNewDiagnosticLines() throws {
        let presentation = SettingsExperiencePresentation(
            gateway: SavedGateway(
                id: "gateway",
                label: "Gateway",
                baseURL: try XCTUnwrap(URL(string: "https://example.test")),
                authMode: .gated
            ),
            phase: .connected,
            negotiation: .verified(capabilities),
            clientBuild: SettingsClientBuildInfo(
                version: "0.2.0\ntoken: escaped-secret",
                build: "42",
                sourceRevision: "abc@example.test"
            )
        )
        let report = SettingsDiagnosticsReport.make(
            presentation: presentation,
            permissions: permissions,
            environment: SettingsDiagnosticsEnvironment(
                operatingSystem: "iOS\nprompt: private",
                generatedAt: Date(timeIntervalSince1970: 0)
            )
        )

        XCTAssertFalse(report.contains("escaped-secret"))
        XCTAssertFalse(report.contains("abc@example.test"))
        XCTAssertFalse(report.contains("prompt: private"))
        XCTAssertTrue(report.contains("app_version: [redacted]"))
        XCTAssertTrue(report.contains("source_revision: [redacted]"))
        XCTAssertTrue(report.contains("operating_system: [redacted]"))
    }

    private var capabilities: GatewayCapabilities {
        GatewayCapabilities(
            contract: GatewayCapabilityContract(
                name: "fabric.gateway",
                version: 1,
                minimumCompatibleVersion: 1
            ),
            server: GatewayServerContract(version: "4.2.1", releaseDate: "2026-07-20"),
            execution: GatewayExecutionContract(
                location: "gateway",
                toolExecution: "gateway",
                survivesClientDisconnect: true,
                survivesGatewayRestart: false,
                requiresGatewayHostOnline: true
            ),
            features: ["baseline_chat": true, "live_view": true],
            methods: ["prompt.submit", "session.create", "session.list", "session.resume"]
        )
    }

    private var permissions: SettingsPermissionInventory {
        SettingsPermissionInventory(
            camera: SettingsPermissionPresentation(
                name: "Camera",
                value: "Denied",
                detail: "Denied",
                systemImage: "camera.fill",
                state: .denied
            ),
            microphone: SettingsPermissionPresentation(
                name: "Microphone",
                value: "Denied",
                detail: "Denied",
                systemImage: "mic.slash.fill",
                state: .denied
            ),
            speechRecognition: SettingsPermissionPresentation(
                name: "Speech Recognition",
                value: "Denied",
                detail: "Denied",
                systemImage: "waveform.slash",
                state: .denied
            ),
            localNetwork: SettingsPermissionPresentation(
                name: "Local Network",
                value: "Status not exposed by iOS",
                detail: "Not inspectable",
                systemImage: "network",
                state: .notInspectable
            )
        )
    }
}
