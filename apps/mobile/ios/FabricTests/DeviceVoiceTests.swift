import AVFoundation
import XCTest
@testable import Fabric

final class DeviceVoiceTests: XCTestCase {
    func testDictationMergesIntoExistingDraftWithoutSubmittingOrRewritingIt() {
        XCTAssertEqual(
            VoiceDraftComposer.merging(
                baseDraft: "Keep this exact draft:",
                transcript: "and add my words"
            ),
            "Keep this exact draft: and add my words"
        )
        XCTAssertEqual(
            VoiceDraftComposer.merging(baseDraft: "Already spaced ", transcript: "next"),
            "Already spaced next"
        )
        XCTAssertEqual(
            VoiceDraftComposer.merging(baseDraft: "", transcript: "A new message"),
            "A new message"
        )
        XCTAssertEqual(
            VoiceDraftComposer.merging(baseDraft: "Typed only", transcript: ""),
            "Typed only"
        )
    }

    func testSpeechTextReadsProseAndDoesNotSpellTechnicalBlocks() {
        let source = """
        ## Release **ready**

        - Tests passed

        ```swift
        let secret = "do not read this code"
        ```
        """

        let spoken = DeviceVoiceText.spokenText(from: source)

        XCTAssertTrue(spoken.contains("Release ready"))
        XCTAssertTrue(spoken.contains("Tests passed"))
        XCTAssertTrue(spoken.contains("Code block omitted."))
        XCTAssertFalse(spoken.contains("let secret"))
        XCTAssertFalse(spoken.contains("**"))
        XCTAssertFalse(spoken.contains("```"))
    }

    func testSpeechTextIsBounded() {
        let spoken = DeviceVoiceText.spokenText(
            from: String(repeating: "voice ", count: 10_000)
        )

        XCTAssertEqual(spoken.count, DeviceVoiceText.maximumCharacters)
        XCTAssertTrue(spoken.hasSuffix("…"))
    }

    func testPermissionIssuesOfferSettingsOnlyWhenRecoveryLivesThere() {
        XCTAssertTrue(DeviceVoiceIssue.microphonePermissionDenied.canOpenSettings)
        XCTAssertTrue(DeviceVoiceIssue.speechPermissionDenied.canOpenSettings)
        XCTAssertFalse(DeviceVoiceIssue.speechPermissionRestricted.canOpenSettings)
        XCTAssertFalse(DeviceVoiceIssue.speechUnavailable.canOpenSettings)
        XCTAssertFalse(DeviceVoiceIssue.recognitionFailed.canOpenSettings)
    }

    func testDictationStateLocksDraftUntilPermissionOrFinalizationEnds() {
        XCTAssertFalse(DeviceDictationState.idle.locksDraft)
        XCTAssertTrue(DeviceDictationState.requestingPermission.locksDraft)
        XCTAssertTrue(DeviceDictationState.listening.locksDraft)
        XCTAssertTrue(DeviceDictationState.finalizing.locksDraft)
        XCTAssertTrue(DeviceDictationState.listening.isListening)
        XCTAssertFalse(DeviceDictationState.finalizing.isListening)
        XCTAssertTrue(DeviceDictationState.finalizing.isActive)
    }

    func testDictationStopActionFinishesAudioBeforeCancellingRecognition() {
        XCTAssertEqual(DeviceDictationState.idle.stopAction, .none)
        XCTAssertEqual(DeviceDictationState.requestingPermission.stopAction, .cancel)
        XCTAssertEqual(DeviceDictationState.listening.stopAction, .finish)
        XCTAssertEqual(DeviceDictationState.finalizing.stopAction, .none)
    }

    func testRouteChangePolicyIgnoresOnlyAppControlledChanges() {
        XCTAssertFalse(DeviceVoiceRouteChangePolicy.invalidatesCurrentRoute(.categoryChange))
        XCTAssertFalse(DeviceVoiceRouteChangePolicy.invalidatesCurrentRoute(.override))
        XCTAssertTrue(DeviceVoiceRouteChangePolicy.invalidatesCurrentRoute(.oldDeviceUnavailable))
        XCTAssertTrue(DeviceVoiceRouteChangePolicy.invalidatesCurrentRoute(.newDeviceAvailable))
        XCTAssertTrue(DeviceVoiceRouteChangePolicy.invalidatesCurrentRoute(.routeConfigurationChange))
    }

    func testStaleVoicePreferenceFallsBackToBestInstalledVoice() {
        let options = [
            DeviceVoiceOption(
                identifier: "installed",
                name: "Installed",
                language: "en-US",
                quality: ""
            )
        ]

        XCTAssertEqual(
            DeviceVoicePreferences.normalizedIdentifier("installed", options: options),
            "installed"
        )
        XCTAssertEqual(
            DeviceVoicePreferences.normalizedIdentifier("removed", options: options),
            ""
        )
        XCTAssertEqual(DeviceVoicePreferences.normalizedIdentifier("", options: options), "")
    }
}
