import Foundation

// Visibility policy for the connected app shell's tab bar.
//
// The shell renders a fixed set of destinations. This file decides which of
// them are *visible* on a given gateway, combining two independent inputs:
//
//   1. Availability — whether the gateway's capability contract exposes the
//      page at all. Home, Sessions, Social, and Settings are always available;
//      optional pages (Work, once `durable_work` is advertised) plug in here and
//      stay dark until the server advertises them, matching the fail-closed rule
//      the content surfaces already use.
//   2. Preference — whether the user has hidden the page from the tab bar.
//
// Home and Settings are structural and can never be hidden; Sessions is the core
// conversation surface and stays fixed. Everything here is pure and synchronous
// so it can be unit-tested without a running gateway or SwiftUI.

extension ConnectedAppTab: CaseIterable {
    /// Canonical left-to-right display order for the tab bar.
    static var allCases: [ConnectedAppTab] {
        [.home, .sessions, .work, .social, .settings]
    }

    /// Human-facing tab-bar label. Centralized here so the shell and the
    /// Settings "Pages" toggles can never drift apart.
    var tabTitle: String {
        switch self {
        case .home: return "Home"
        case .sessions: return "Sessions"
        case .work: return "Work"
        case .social: return "Social"
        case .settings: return "Settings"
        }
    }

    /// SF Symbol shown in the tab item.
    var tabSystemImage: String {
        switch self {
        case .home: return "sparkles"
        case .sessions: return "bubble.left.and.bubble.right"
        case .work: return "checklist"
        case .social: return "megaphone"
        case .settings: return "gearshape"
        }
    }

    /// Stable accessibility identifier for UI tests.
    var tabAccessibilityIdentifier: String { "app-tab-\(rawValue)" }

    /// Whether the user may hide this page from the tab bar.
    var isHideable: Bool {
        switch self {
        case .home, .sessions, .settings: return false
        case .work, .social: return true
        }
    }
}

/// Device-local persistence for hidden tabs.
///
/// Stored as a comma-joined list of `ConnectedAppTab.rawValue` strings because
/// `@AppStorage` cannot hold a `Set`. Unknown identifiers are preserved on every
/// round-trip so a page hidden by a newer app version is not silently dropped
/// when an older build rewrites the string.
enum ConnectedAppTabPreferences {
    static let storageKey = "fabric.mobile.hidden-tabs.v1"

    static func parse(_ raw: String) -> Set<String> {
        Set(
            raw
                .split(separator: ",")
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
        )
    }

    static func serialize(_ identifiers: Set<String>) -> String {
        identifiers.sorted().joined(separator: ",")
    }

    /// Toggle one tab's hidden state, preserving any unknown identifiers.
    static func setHidden(_ hidden: Bool, tab: ConnectedAppTab, in raw: String) -> String {
        var identifiers = parse(raw)
        if hidden {
            identifiers.insert(tab.rawValue)
        } else {
            identifiers.remove(tab.rawValue)
        }
        return serialize(identifiers)
    }
}

/// Which tabs a given gateway exposes.
///
/// Optional pages appear only when the gateway's capability contract advertises
/// them. Phase 1 has no capability-gated tabs; Work plugs in here once
/// `durable_work` is advertised on a verified contract.
struct ConnectedAppTabAvailability: Equatable {
    var availableTabs: Set<ConnectedAppTab>

    func isAvailable(_ tab: ConnectedAppTab) -> Bool {
        availableTabs.contains(tab)
    }

    static func resolve(
        negotiation: GatewayCapabilityNegotiation?
    ) -> ConnectedAppTabAvailability {
        // Home, Sessions, Social, and Settings do not depend on an optional
        // capability family, so they are always available. Work appears only
        // when the gateway advertises the complete `durable_work` contract
        // (FMB-002), matching the fail-closed rule the content surfaces use.
        var tabs: Set<ConnectedAppTab> = [.home, .sessions, .social, .settings]
        if negotiation?.supportsDurableWork == true {
            tabs.insert(.work)
        }
        return ConnectedAppTabAvailability(availableTabs: tabs)
    }
}

enum ConnectedAppTabPolicy {
    /// The ordered tabs the shell should render, given hidden-tab preferences and
    /// gateway availability.
    static func visibleTabs(
        hidden: Set<String>,
        availability: ConnectedAppTabAvailability
    ) -> [ConnectedAppTab] {
        ConnectedAppTab.allCases.filter { tab in
            guard availability.isAvailable(tab) else { return false }
            if tab.isHideable && hidden.contains(tab.rawValue) {
                return false
            }
            return true
        }
    }

    /// Resolve a persisted tab selection against the currently visible tabs,
    /// falling back to Home when the stored tab is hidden, unavailable, or an
    /// unknown identifier. Home is always visible, so the fallback is always
    /// valid.
    static func resolvedSelection(
        stored: String,
        visible: [ConnectedAppTab]
    ) -> String {
        if visible.contains(where: { $0.rawValue == stored }) {
            return stored
        }
        return ConnectedAppTab.home.rawValue
    }

    /// The tabs a user may toggle on this gateway: hide-able *and* currently
    /// available. Drives the Settings "Pages" toggles so a page the server does
    /// not expose never shows a dead toggle.
    static func hideableTabs(
        availability: ConnectedAppTabAvailability
    ) -> [ConnectedAppTab] {
        ConnectedAppTab.allCases.filter {
            $0.isHideable && availability.isAvailable($0)
        }
    }
}
