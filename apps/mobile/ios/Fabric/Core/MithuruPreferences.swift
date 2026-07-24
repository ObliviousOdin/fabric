import Foundation
import SwiftUI

enum MithuruInteractionMode: String, Codable, CaseIterable {
    case voiceAndText
    case textOnly
}

enum MithuruTextScale: String, Codable, CaseIterable {
    case large
    case extraLarge
    case maximum

    var dynamicTypeSize: DynamicTypeSize {
        switch self {
        case .large: return .large
        case .extraLarge: return .xxLarge
        case .maximum: return .accessibility3
        }
    }
}

struct MithuruPreferences: Codable, Equatable {
    var onboardingCompleted = false
    var simpleModeEnabled = true
    var locale = MithuruLocale.englishSriLanka
    var interactionMode = MithuruInteractionMode.voiceAndText
    var textScale = MithuruTextScale.large
    var speechRate = 1.0
    var caregiverConfigured = false
    var cloudSpeechAllowed = false
}

enum MithuruPreferencesStore {
    private static let prefix = "fabric.mobile.mithuru.v1"

    static func load(gatewayID: String?, defaults: UserDefaults = .standard) -> MithuruPreferences {
        guard let data = defaults.data(forKey: key(gatewayID)),
              let decoded = try? JSONDecoder().decode(MithuruPreferences.self, from: data) else {
            return MithuruPreferences()
        }
        return normalized(decoded)
    }

    static func save(
        _ preferences: MithuruPreferences,
        gatewayID: String?,
        defaults: UserDefaults = .standard
    ) {
        guard let data = try? JSONEncoder().encode(normalized(preferences)) else { return }
        defaults.set(data, forKey: key(gatewayID))
    }

    static func storageKey(gatewayID: String?) -> String { key(gatewayID) }

    static func loadStoredSessionID(gatewayID: String?, defaults: UserDefaults = .standard) -> String? {
        guard let value = defaults.string(forKey: sessionKey(gatewayID))?
            .trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty,
              value.count <= 512 else { return nil }
        return value
    }

    static func saveStoredSessionID(
        _ sessionID: String?,
        gatewayID: String?,
        defaults: UserDefaults = .standard
    ) {
        guard let value = sessionID?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty,
              value.count <= 512 else {
            defaults.removeObject(forKey: sessionKey(gatewayID))
            return
        }
        defaults.set(value, forKey: sessionKey(gatewayID))
    }

    private static func key(_ gatewayID: String?) -> String {
        let scope = gatewayID?.trimmingCharacters(in: .whitespacesAndNewlines)
        return "\(prefix):\(scope?.isEmpty == false ? scope! : "default")"
    }

    private static func sessionKey(_ gatewayID: String?) -> String {
        "\(key(gatewayID)).session"
    }

    private static func normalized(_ source: MithuruPreferences) -> MithuruPreferences {
        var result = source
        result.speechRate = min(1.0, max(0.5, source.speechRate))
        if result.interactionMode == .textOnly {
            result.cloudSpeechAllowed = false
        }
        return result
    }
}
