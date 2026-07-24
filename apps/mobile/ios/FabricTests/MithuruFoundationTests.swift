import XCTest
@testable import Fabric

final class MithuruFoundationTests: XCTestCase {
    func testEverySupportedLocaleHasEveryMithuruKey() {
        for locale in MithuruLocale.allCases {
            XCTAssertEqual(MithuruCopy.missingKeys(locale: locale), [], "Missing Mithuru copy for \(locale.rawValue)")
        }
    }

    func testPreferencesAreScopedByGatewayAndSpeechRateIsNormalized() {
        let suiteName = "MithuruFoundationTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }

        var first = MithuruPreferences()
        first.onboardingCompleted = true
        first.locale = .tamil
        first.speechRate = 9
        first.interactionMode = .textOnly
        first.cloudSpeechAllowed = true

        MithuruPreferencesStore.save(first, gatewayID: "gateway-a", defaults: defaults)

        let loaded = MithuruPreferencesStore.load(gatewayID: "gateway-a", defaults: defaults)
        XCTAssertEqual(loaded.locale, .tamil)
        XCTAssertEqual(loaded.speechRate, 1)
        XCTAssertFalse(loaded.cloudSpeechAllowed)
        XCTAssertFalse(MithuruPreferencesStore.load(gatewayID: "gateway-b", defaults: defaults).onboardingCompleted)
    }

    func testCloudFallbackFailureHasNonTechnicalRecoveryCopy() {
        let issue = DeviceVoiceIssue.onDeviceSpeechUnavailable
        XCTAssertTrue(issue.title.contains("On-device"))
        XCTAssertTrue(issue.message.contains("type"))
        XCTAssertFalse(issue.message.localizedCaseInsensitiveContains("SFSpeechRecognizer"))
    }
}
