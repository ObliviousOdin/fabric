import Foundation

/// Stable locale identifiers shared with the desktop Mithuru contract.
enum MithuruLocale: String, CaseIterable, Codable, Identifiable {
    case sinhala = "si-LK"
    case tamil = "ta-LK"
    case englishSriLanka = "en-LK"

    var id: String { rawValue }
    var locale: Locale { Locale(identifier: rawValue) }

    var displayName: String {
        switch self {
        case .sinhala: return "සිංහල"
        case .tamil: return "தமிழ்"
        case .englishSriLanka: return "English (Sri Lanka)"
        }
    }
}

enum MithuruCopyKey: String, CaseIterable {
    case brand
    case welcome
    case languageQuestion
    case interactionQuestion
    case voiceAndText
    case textOnly
    case textSizeQuestion
    case large
    case extraLarge
    case maximum
    case speechRateQuestion
    case slow
    case normal
    case familyQuestion
    case familyPrivacy
    case cloudQuestion
    case cloudExplanation
    case yes
    case no
    case back
    case greeting
    case talk
    case stopListening
    case send
    case repeatAnswer
    case stopSpeaking
    case editTranscript
    case typeRequest
    case ready
    case listening
    case processing
    case speaking
    case offline
    case needsConfirmation
    case confirmTitle
    case allowOnce
    case deny
    case standardMode
    case openMithuru
    case help
    case helpBody
    case privacyLocal
    case privacyCloud
    case speechPrivacy
    case allowOnlineSpeech
    case disableOnlineSpeech
    case readMessages
    case messageFamily
    case setReminder
    case explainLetter
    case appointments
    case documentConsent
    case chooseDocument
    case documentsToSend
    case removeDocument
    case cancel
    case voiceUnavailable
    case voiceIssueTitle
    case voiceIssueMessage
    case connectionError
    case statusAccessibility
    case conversationAccessibility
    case suggestionsAccessibility
    case you
}

enum MithuruCopy {
    private static let tableName = "Mithuru"

    static func text(_ key: MithuruCopyKey, locale: MithuruLocale) -> String {
        String(
            localized: String.LocalizationValue(key.rawValue),
            table: tableName,
            bundle: .main,
            locale: locale.locale
        )
    }

    static func missingKeys(locale: MithuruLocale) -> [MithuruCopyKey] {
        MithuruCopyKey.allCases.filter { text($0, locale: locale) == $0.rawValue }
    }
}
