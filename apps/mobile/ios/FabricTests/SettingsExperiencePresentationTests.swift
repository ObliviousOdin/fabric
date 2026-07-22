import AVFoundation
import Foundation
import Speech
import XCTest
@testable import Fabric

final class SettingsExperiencePresentationTests: XCTestCase {
    @MainActor
    func testConnectedPresentationNamesServerAndStatesVerifiedExecutionTruth() throws {
        let presentation = SettingsExperiencePresentation(
            gateway: SavedGateway(
                id: "gateway-1",
                label: "Studio Mac",
                baseURL: try XCTUnwrap(URL(string: "https://studio.example.test:9443/fabric")),
                authMode: .token
            ),
            phase: .connected,
            negotiation: .verified(verifiedCapabilities()),
            clientBuild: clientBuild
        )

        XCTAssertEqual(presentation.connection.title, "Connected")
        XCTAssertTrue(presentation.connection.detail.contains("Studio Mac"))
        XCTAssertEqual(presentation.connection.tone, .success)
        XCTAssertEqual(presentation.gateway?.label, "Studio Mac")
        XCTAssertEqual(presentation.gateway?.authentication, "Credential protected in Keychain")
        XCTAssertEqual(presentation.gateway?.transport, "HTTPS encrypted transport")
        XCTAssertNil(presentation.gateway?.transportWarning)
        XCTAssertEqual(presentation.execution.title, "Runs on your gateway")
        XCTAssertTrue(presentation.execution.detail.contains("not on this iPhone"))
        XCTAssertTrue(presentation.execution.detail.contains("continues if this phone disconnects"))
        XCTAssertTrue(presentation.execution.detail.contains("gateway restart interrupts"))
        XCTAssertTrue(presentation.execution.detail.contains("Keep the gateway host online"))
    }

    @MainActor
    func testReconnectingAndDisconnectedStatesStayLabeled() throws {
        let gateway = SavedGateway(
            id: "gateway-1",
            label: "Studio Mac",
            baseURL: try XCTUnwrap(URL(string: "https://studio.example.test")),
            authMode: .gated
        )

        let reconnecting = SettingsExperiencePresentation(
            gateway: gateway,
            phase: .reconnecting,
            negotiation: .negotiating,
            clientBuild: clientBuild
        )
        XCTAssertEqual(reconnecting.connection.title, "Reconnecting")
        XCTAssertEqual(reconnecting.connection.tone, .warning)
        XCTAssertEqual(reconnecting.gateway?.authentication, "Password protected; password is not saved")
        XCTAssertEqual(reconnecting.execution.title, "Verifying execution")

        // A gateway whose user opted into keeping the password must say so —
        // the no-storage claim would otherwise be untrue.
        let keptPassword = SettingsExperiencePresentation(
            gateway: gateway,
            phase: .reconnecting,
            negotiation: .negotiating,
            clientBuild: clientBuild,
            hasStoredPassword: true
        )
        XCTAssertEqual(
            keptPassword.gateway?.authentication,
            "Password protected; password saved in Keychain on this iPhone"
        )

        let disconnected = SettingsExperiencePresentation(
            gateway: nil,
            phase: .disconnected,
            negotiation: nil,
            clientBuild: clientBuild
        )
        XCTAssertEqual(disconnected.connection.title, "Not connected")
        XCTAssertNil(disconnected.gateway)
        XCTAssertEqual(disconnected.execution.title, "Execution not verified")
    }

    func testDisplayEndpointRemovesURLCredentialsQueryAndFragment() throws {
        let endpoint = SettingsGatewayIdentity.displayEndpoint(
            try XCTUnwrap(URL(string: "https://operator:password@example.test:9443/fabric?token=secret#private"))
        )

        XCTAssertEqual(endpoint, "https://example.test:9443/fabric")
        XCTAssertFalse(endpoint.contains("operator"))
        XCTAssertFalse(endpoint.contains("password"))
        XCTAssertFalse(endpoint.contains("token"))
        XCTAssertFalse(endpoint.contains("secret"))
        XCTAssertFalse(endpoint.contains("private"))
    }

    func testPlainHTTPTransportIsNeverPresentedAsSecure() throws {
        let gateway = SavedGateway(
            id: "gateway-http",
            label: "Tailnet Mac",
            baseURL: try XCTUnwrap(URL(string: "http://100.64.0.8:9119")),
            authMode: .gated
        )
        let presentation = SettingsExperiencePresentation(
            gateway: gateway,
            phase: .connecting,
            negotiation: .negotiating,
            clientBuild: clientBuild
        )

        XCTAssertEqual(
            presentation.gateway?.transport,
            "HTTP transport over a private encrypted network only"
        )
        XCTAssertNotNil(presentation.gateway?.transportWarning)
        XCTAssertFalse(presentation.connection.detail.lowercased().contains("secure"))
        XCTAssertTrue(presentation.gateway?.transportWarning?.contains("never over the public internet") == true)
    }

    func testCapabilitySummarySeparatesGatewayAdvertisementFromMobileAvailability() {
        let summary = SettingsGatewayContractPresentation.make(
            negotiation: .verified(verifiedCapabilities())
        )

        XCTAssertEqual(summary.serverVersion, "4.2.1")
        XCTAssertEqual(summary.serverReleaseDate, "2026-07-20")
        XCTAssertEqual(summary.contractVersion, "1")
        XCTAssertEqual(summary.baselineStatus, "Verified")
        XCTAssertEqual(summary.advertisedFeatureCount, 4)
        XCTAssertEqual(summary.publishedMethodCount, 11)
        XCTAssertEqual(
            summary.advertisedFeatures,
            ["Background work", "Conversations", "Live View", "Pets"]
        )
    }

    func testLegacyAndInvalidContractsNeverClaimVerifiedExecution() {
        let legacy = SettingsGatewayContractPresentation.make(negotiation: .legacy)
        XCTAssertEqual(legacy.baselineStatus, "Compatibility mode")
        XCTAssertEqual(legacy.serverVersion, "Not reported")
        XCTAssertNil(legacy.advertisedFeatureCount)

        let invalid = SettingsGatewayContractPresentation.make(
            negotiation: .invalid(reason: "contradiction")
        )
        XCTAssertEqual(invalid.baselineStatus, "Disabled for safety")
        XCTAssertEqual(invalid.contractVersion, "Invalid response")
    }

    func testPermissionInventoryMapsCameraVoicePermissionsAndDoesNotGuessLocalNetworkStatus() {
        let allowed = SettingsPermissionInventory.cameraPermission(.authorized)
        let denied = SettingsPermissionInventory.cameraPermission(.denied)
        let notRequested = SettingsPermissionInventory.cameraPermission(.notDetermined)

        XCTAssertEqual(allowed.state, .allowed)
        XCTAssertEqual(allowed.value, "Allowed")
        XCTAssertEqual(denied.state, .denied)
        XCTAssertTrue(denied.detail.contains("iOS Settings"))
        XCTAssertEqual(notRequested.state, .notRequested)
        XCTAssertTrue(notRequested.detail.contains("asks only"))

        XCTAssertEqual(
            SettingsPermissionInventory.microphonePermission(.granted).state,
            .allowed
        )
        XCTAssertEqual(
            SettingsPermissionInventory.microphonePermission(.denied).state,
            .denied
        )
        XCTAssertEqual(
            SettingsPermissionInventory.speechRecognitionPermission(.authorized).state,
            .allowed
        )
        XCTAssertEqual(
            SettingsPermissionInventory.speechRecognitionPermission(.restricted).state,
            .restricted
        )

        let inventory = SettingsPermissionInventory.current()
        XCTAssertEqual(inventory.localNetwork.state, .notInspectable)
        XCTAssertEqual(inventory.localNetwork.value, "Status not exposed by iOS")
    }

    func testLocalResetCopyIsExplicitDestructiveAndNeverClaimsGatewayDeletion() {
        let reset = SettingsServerManagementAction.resetLocalApp

        XCTAssertEqual(reset.confirmationTitle, "Reset Fabric on this iPhone?")
        XCTAssertEqual(reset.confirmationButtonTitle, "Reset Fabric")
        XCTAssertTrue(reset.isDestructive)
        XCTAssertTrue(reset.confirmationMessage.contains("all saved servers and credentials"))
        XCTAssertTrue(reset.confirmationMessage.contains("device-only presentation state"))
        XCTAssertTrue(reset.confirmationMessage.contains("not deleted"))

        XCTAssertTrue(SettingsServerManagementAction.forgetServer.isDestructive)
        XCTAssertFalse(SettingsServerManagementAction.switchServer.isDestructive)
        XCTAssertFalse(SettingsServerManagementAction.repairServer.isDestructive)
        XCTAssertFalse(SettingsServerManagementAction.clearCachedPresentationData.isDestructive)
    }

    func testSwitchServerConfirmationFollowsVerifiedDisconnectPosture() throws {
        let gateway = SavedGateway(
            id: "gateway-1",
            label: "Studio Mac",
            baseURL: try XCTUnwrap(URL(string: "https://studio.example.test")),
            authMode: .token
        )
        let continues = SettingsExperiencePresentation(
            gateway: gateway,
            phase: .connected,
            negotiation: .verified(verifiedCapabilities(survivesClientDisconnect: true)),
            clientBuild: clientBuild
        )
        let mayStop = SettingsExperiencePresentation(
            gateway: gateway,
            phase: .connected,
            negotiation: .verified(verifiedCapabilities(survivesClientDisconnect: false)),
            clientBuild: clientBuild
        )

        let continuesMessage = SettingsServerManagementAction.switchServer
            .confirmationMessage(disconnectPosture: continues.clientDisconnectPosture)
        XCTAssertTrue(continuesMessage.contains("active work continues"))

        let mayStopMessage = SettingsServerManagementAction.switchServer
            .confirmationMessage(disconnectPosture: mayStop.clientDisconnectPosture)
        XCTAssertTrue(mayStopMessage.contains("active work may stop"))
        XCTAssertFalse(mayStopMessage.contains("work continues"))
    }

    func testSwitchServerConfirmationNeverPromisesContinuityForLegacyOrUnknown() {
        for negotiation: GatewayCapabilityNegotiation? in [.legacy, .negotiating, nil] {
            let presentation = SettingsExperiencePresentation(
                gateway: nil,
                phase: .disconnected,
                negotiation: negotiation,
                clientBuild: clientBuild
            )
            let message = SettingsServerManagementAction.switchServer
                .confirmationMessage(disconnectPosture: presentation.clientDisconnectPosture)

            XCTAssertEqual(presentation.clientDisconnectPosture, .unverified)
            XCTAssertTrue(message.contains("cannot verify"))
            XCTAssertFalse(message.contains("work continues"))
        }
    }

    func testClearCacheCopyPreservesServersCredentialsAndGatewayData() {
        let clear = SettingsServerManagementAction.clearCachedPresentationData

        XCTAssertEqual(clear.confirmationTitle, "Clear cached presentation data?")
        XCTAssertEqual(clear.confirmationButtonTitle, "Clear Cache")
        XCTAssertFalse(clear.isDestructive)
        XCTAssertTrue(clear.confirmationMessage.contains("Home and conversation"))
        XCTAssertTrue(clear.confirmationMessage.contains("Saved servers, credentials"))
        XCTAssertTrue(clear.confirmationMessage.contains("gateway data are not changed"))

        XCTAssertTrue(SettingsLocalDataAlert.cacheCleared.message.contains("were not changed"))
        XCTAssertTrue(SettingsLocalDataAlert.cacheClearFailed.message.contains("were not changed"))
        XCTAssertEqual(SettingsLocalDataAlert.forgetGatewayFailed.title, "Couldn't forget server")
        XCTAssertTrue(SettingsLocalDataAlert.forgetGatewayFailed.message.contains("still saved"))
        XCTAssertFalse(SettingsLocalDataAlert.forgetGatewayFailed.message.contains("OSStatus"))
        XCTAssertTrue(SettingsLocalDataAlert.resetFailed.message.contains("may still be present"))
    }

    func testPetPresentationCoversEveryAvailabilityStateHonestly() {
        let unsupported = SettingsPetPresentation.make(supportsPets: false, state: .unsupported)
        XCTAssertEqual(unsupported.title, "Pets")
        XCTAssertEqual(unsupported.systemImage, "pawprint.fill")
        XCTAssertTrue(unsupported.detail.contains("doesn't advertise pets yet"))
        XCTAssertEqual(unsupported.tone, .neutral)
        XCTAssertFalse(unsupported.showsControls)

        // Supported but not yet refreshed must read as loading, never as a
        // false "gateway lacks pets" claim.
        let checking = SettingsPetPresentation.make(supportsPets: true, state: .unsupported)
        XCTAssertEqual(checking.tone, .info)
        XCTAssertFalse(checking.showsControls)
        XCTAssertFalse(checking.detail.contains("doesn't advertise"))

        let loading = SettingsPetPresentation.make(supportsPets: true, state: .loading)
        XCTAssertEqual(loading.tone, .info)
        XCTAssertFalse(loading.showsControls)

        let disabled = SettingsPetPresentation.make(supportsPets: true, state: .disabled)
        XCTAssertTrue(disabled.detail.contains("animated companion"))
        XCTAssertEqual(disabled.tone, .neutral)
        XCTAssertTrue(disabled.showsControls)

        let active = SettingsPetPresentation.make(
            supportsPets: true,
            state: .active(PetDisplay(sheet: petSheet))
        )
        XCTAssertEqual(active.detail, "Bandit")
        XCTAssertTrue(active.showsControls)

        let unavailable = SettingsPetPresentation.make(
            supportsPets: true,
            state: .unavailable("Pets are advertised but unreachable right now.")
        )
        XCTAssertEqual(unavailable.detail, "Pets are advertised but unreachable right now.")
        XCTAssertEqual(unavailable.tone, .warning)
        XCTAssertFalse(unavailable.showsControls)
    }

    func testVoicePresentationNamesNativePhoneVoiceAndSelectedVoice() {
        let voice = SettingsVoicePresentation.make(selectedVoiceName: "Samantha · en-US")

        XCTAssertEqual(voice.title, "Voice")
        XCTAssertEqual(voice.systemImage, "waveform")
        XCTAssertEqual(voice.tone, .success)
        XCTAssertTrue(voice.detail.contains("this iPhone"))
        XCTAssertTrue(voice.detail.contains("on-device recognition"))
        XCTAssertTrue(voice.detail.contains("Samantha · en-US"))
        XCTAssertFalse(voice.detail.contains("gateway host"))
    }

    func testLocalDataAlertReusesTheThrownErrorCopyForForgetFailures() {
        XCTAssertEqual(
            SettingsLocalDataAlert.forgetGatewayFailed.message,
            AppLocalDataError.forgetGatewayUnavailable.localizedDescription
        )
    }

    private var petSheet: PetSpriteSheet {
        PetSpriteSheet(
            slug: "bandit",
            displayName: "Bandit",
            mime: "image/webp",
            spritesheetRevision: "1721600000:2048",
            spritesheetBase64: "AA==",
            frameW: 192,
            frameH: 208,
            framesPerState: 4,
            framesByState: ["idle": 4],
            framesByRow: ["idle": 4],
            loopMs: 800,
            stateRows: ["idle"]
        )
    }

    private var clientBuild: SettingsClientBuildInfo {
        SettingsClientBuildInfo(
            version: "0.2.0",
            build: "42",
            sourceRevision: "0123456789abcdef"
        )
    }

    private func verifiedCapabilities(
        survivesClientDisconnect: Bool = true
    ) -> GatewayCapabilities {
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
                survivesClientDisconnect: survivesClientDisconnect,
                survivesGatewayRestart: false,
                requiresGatewayHostOnline: true
            ),
            features: [
                "background_work": true,
                "baseline_chat": true,
                "files": false,
                "live_view": true,
                "pets": true,
            ],
            methods: [
                "pet.disable",
                "pet.gallery",
                "pet.info",
                "pet.info.meta",
                "pet.select",
                "pet.thumb",
                "prompt.background",
                "prompt.submit",
                "session.create",
                "session.list",
                "session.resume",
            ]
        )
    }
}
