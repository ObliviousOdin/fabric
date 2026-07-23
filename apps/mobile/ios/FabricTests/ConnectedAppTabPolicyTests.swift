import Foundation
import XCTest
@testable import Fabric

final class ConnectedAppTabPolicyTests: XCTestCase {
    private let allAvailable = ConnectedAppTabAvailability(
        availableTabs: [.home, .sessions, .social, .settings]
    )

    // MARK: - Preferences serialization

    func testSerializationRoundTrip() {
        let identifiers: Set<String> = ["social", "work"]
        let serialized = ConnectedAppTabPreferences.serialize(identifiers)
        XCTAssertEqual(ConnectedAppTabPreferences.parse(serialized), identifiers)
    }

    func testParseIgnoresWhitespaceAndEmptyEntries() {
        XCTAssertEqual(
            ConnectedAppTabPreferences.parse(" social , , sessions "),
            ["social", "sessions"]
        )
        XCTAssertEqual(ConnectedAppTabPreferences.parse(""), [])
    }

    func testSetHiddenPreservesUnknownIdentifiers() {
        // A newer app version may have hidden a page this build doesn't know
        // about. Toggling a known page must not drop that unknown identifier.
        let raw = "future_page"
        let hidden = ConnectedAppTabPreferences.setHidden(true, tab: .social, in: raw)
        XCTAssertEqual(ConnectedAppTabPreferences.parse(hidden), ["future_page", "social"])

        let shown = ConnectedAppTabPreferences.setHidden(false, tab: .social, in: hidden)
        XCTAssertEqual(ConnectedAppTabPreferences.parse(shown), ["future_page"])
    }

    func testSetHiddenIsIdempotent() {
        let once = ConnectedAppTabPreferences.setHidden(true, tab: .social, in: "")
        let twice = ConnectedAppTabPreferences.setHidden(true, tab: .social, in: once)
        XCTAssertEqual(
            ConnectedAppTabPreferences.parse(once),
            ConnectedAppTabPreferences.parse(twice)
        )
    }

    // MARK: - Hideability

    func testHomeAndSettingsAreNeverHideable() {
        XCTAssertFalse(ConnectedAppTab.home.isHideable)
        XCTAssertFalse(ConnectedAppTab.settings.isHideable)
        // Even if a preference string somehow lists them, they stay visible.
        let visible = ConnectedAppTabPolicy.visibleTabs(
            hidden: ["home", "settings"],
            availability: allAvailable
        )
        XCTAssertTrue(visible.contains(.home))
        XCTAssertTrue(visible.contains(.settings))
    }

    func testHideableTabsAreOnlyHideableAndAvailable() {
        XCTAssertEqual(
            ConnectedAppTabPolicy.hideableTabs(availability: allAvailable),
            [.social]
        )
        // Availability filters the list: an unavailable social page offers no
        // dead toggle.
        let withoutSocial = ConnectedAppTabAvailability(
            availableTabs: [.home, .sessions, .settings]
        )
        XCTAssertTrue(
            ConnectedAppTabPolicy.hideableTabs(availability: withoutSocial).isEmpty
        )
    }

    // MARK: - Visible tabs

    func testHidingSocialRemovesOnlySocial() {
        let visible = ConnectedAppTabPolicy.visibleTabs(
            hidden: ["social"],
            availability: allAvailable
        )
        XCTAssertEqual(visible, [.home, .sessions, .settings])
    }

    func testNoHiddenTabsShowsEveryAvailableTabInOrder() {
        let visible = ConnectedAppTabPolicy.visibleTabs(
            hidden: [],
            availability: allAvailable
        )
        XCTAssertEqual(visible, [.home, .sessions, .social, .settings])
    }

    func testUnavailableTabIsHiddenEvenWhenNotInPreferences() {
        let availability = ConnectedAppTabAvailability(
            availableTabs: [.home, .sessions, .settings]
        )
        let visible = ConnectedAppTabPolicy.visibleTabs(
            hidden: [],
            availability: availability
        )
        XCTAssertFalse(visible.contains(.social))
    }

    // MARK: - Selection fallback

    func testResolvedSelectionKeepsVisibleSelection() {
        let visible = ConnectedAppTabPolicy.visibleTabs(hidden: [], availability: allAvailable)
        XCTAssertEqual(
            ConnectedAppTabPolicy.resolvedSelection(stored: "sessions", visible: visible),
            "sessions"
        )
    }

    func testResolvedSelectionFallsBackToHomeWhenStoredTabHidden() {
        let visible = ConnectedAppTabPolicy.visibleTabs(
            hidden: ["social"],
            availability: allAvailable
        )
        XCTAssertEqual(
            ConnectedAppTabPolicy.resolvedSelection(stored: "social", visible: visible),
            "home"
        )
    }

    func testResolvedSelectionFallsBackToHomeForUnknownStoredValue() {
        let visible = ConnectedAppTabPolicy.visibleTabs(hidden: [], availability: allAvailable)
        XCTAssertEqual(
            ConnectedAppTabPolicy.resolvedSelection(stored: "garbage", visible: visible),
            "home"
        )
        XCTAssertEqual(
            ConnectedAppTabPolicy.resolvedSelection(stored: "", visible: visible),
            "home"
        )
    }

    // MARK: - Availability resolution

    func testAvailabilityAlwaysExposesStructuralAndSocialTabs() {
        // Regardless of negotiation state, the Phase 1 tab set is always
        // available (no capability-gated tabs yet).
        for negotiation: GatewayCapabilityNegotiation? in [
            nil, .negotiating, .legacy, .invalid(reason: "x")
        ] {
            let availability = ConnectedAppTabAvailability.resolve(negotiation: negotiation)
            XCTAssertEqual(
                availability.availableTabs,
                [.home, .sessions, .social, .settings]
            )
        }
    }
}
