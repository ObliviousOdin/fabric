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
    case readMessages
    case messageFamily
    case setReminder
    case explainLetter
    case appointments
    case documentConsent
    case chooseDocument
    case cancel
    case voiceUnavailable
    case connectionError
}

enum MithuruCopy {
    static func text(_ key: MithuruCopyKey, locale: MithuruLocale) -> String {
        catalogs[locale]?[key] ?? catalogs[.englishSriLanka]?[key] ?? key.rawValue
    }

    static func missingKeys(locale: MithuruLocale) -> [MithuruCopyKey] {
        MithuruCopyKey.allCases.filter { catalogs[locale]?[$0]?.isEmpty != false }
    }

    private static let catalogs: [MithuruLocale: [MithuruCopyKey: String]] = [
        .englishSriLanka: [
            .brand: "Mithuru", .welcome: "Welcome to Mithuru",
            .languageQuestion: "Which language would you like?",
            .interactionQuestion: "Would you like to speak, type, or use both?",
            .voiceAndText: "Speak and type", .textOnly: "Type only",
            .textSizeQuestion: "How large should the text be?",
            .large: "Large", .extraLarge: "Extra large", .maximum: "Maximum",
            .speechRateQuestion: "How fast should Mithuru speak?", .slow: "Slow", .normal: "Normal",
            .familyQuestion: "Is a family member helping with setup?",
            .familyPrivacy: "A helper can change setup choices, but cannot see conversations, recordings, documents, messages, health information, or location unless you explicitly share them.",
            .cloudQuestion: "May speech use Apple's online service when this iPhone cannot recognize the selected language on device?",
            .cloudExplanation: "If you choose Yes, microphone audio may leave this iPhone for speech recognition. Fabric still sends only the text transcript to your paired gateway.",
            .yes: "Yes", .no: "No", .back: "Back", .greeting: "How can I help?",
            .talk: "Talk", .stopListening: "Stop listening", .send: "Send",
            .repeatAnswer: "Repeat", .stopSpeaking: "Stop speaking",
            .editTranscript: "Correct what I heard", .typeRequest: "Type your request",
            .ready: "Ready", .listening: "Listening", .processing: "Working on it",
            .speaking: "Speaking", .offline: "This iPhone is offline",
            .needsConfirmation: "I need your confirmation",
            .confirmTitle: "Please confirm", .allowOnce: "Yes, allow once", .deny: "No, do not do this",
            .standardMode: "Standard Fabric", .openMithuru: "Open Mithuru",
            .help: "Help", .helpBody: "Tap Talk, speak naturally, then correct the text if needed and tap Send. No wake word is used.",
            .privacyLocal: "Speech stays on this iPhone", .privacyCloud: "Apple cloud speech allowed when needed",
            .readMessages: "Read my messages", .messageFamily: "Message family", .setReminder: "Set a reminder",
            .explainLetter: "Explain a letter", .appointments: "Check appointments",
            .documentConsent: "This document may be sent to your paired Fabric gateway and the selected AI provider. Continue?",
            .chooseDocument: "Choose document", .cancel: "Cancel",
            .voiceUnavailable: "Voice is not available for this language. You can keep typing.",
            .connectionError: "I couldn't reach your Fabric. Check the connection and try again."
        ],
        .sinhala: [
            .brand: "මිතුරු", .welcome: "මිතුරු වෙත සාදරයෙන් පිළිගනිමු",
            .languageQuestion: "ඔබ කැමති භාෂාව කුමක්ද?", .interactionQuestion: "ඔබ කතා කිරීමටද, ටයිප් කිරීමටද, දෙකමද කැමති?",
            .voiceAndText: "කතා කර ටයිප් කරන්න", .textOnly: "ටයිප් කිරීම පමණයි",
            .textSizeQuestion: "අකුරු කොතරම් විශාල විය යුතුද?", .large: "විශාල", .extraLarge: "ඉතා විශාල", .maximum: "උපරිම",
            .speechRateQuestion: "මිතුරු කොතරම් වේගයෙන් කතා කළ යුතුද?", .slow: "සෙමින්", .normal: "සාමාන්‍ය",
            .familyQuestion: "සැකසීමට පවුලේ කෙනෙක් උදව් කරනවාද?", .familyPrivacy: "උදව්කරුවෙකුට සැකසුම් වෙනස් කළ හැකි නමුත් ඔබ පැහැදිලිව බෙදා නොගන්නේ නම් සංවාද, පටිගත කිරීම්, ලේඛන, පණිවිඩ, සෞඛ්‍ය තොරතුරු හෝ ස්ථානය බැලිය නොහැක.",
            .cloudQuestion: "මෙම iPhone එකේම හඳුනාගත නොහැකි විට Apple අන්තර්ජාල කථන සේවාව භාවිතා කළ හැකිද?", .cloudExplanation: "ඔව් තෝරාගත්තොත් කථනය හඳුනාගැනීමට මයික්‍රොෆෝන් හඬ මෙම iPhone එකෙන් පිටතට යා හැක. Fabric ඔබගේ gateway වෙත යවන්නේ පෙළ පමණි.",
            .yes: "ඔව්", .no: "නැහැ", .back: "ආපසු", .greeting: "මම කෙසේ උදව් කරන්නද?",
            .talk: "කතා කරන්න", .stopListening: "ඇසීම නවතන්න", .send: "යවන්න", .repeatAnswer: "නැවත කියන්න", .stopSpeaking: "කතා කිරීම නවතන්න",
            .editTranscript: "ඇසූ දේ නිවැරදි කරන්න", .typeRequest: "ඔබේ ඉල්ලීම ටයිප් කරන්න", .ready: "සූදානම්", .listening: "අසමින්", .processing: "කරමින් සිටී", .speaking: "කතා කරමින්", .offline: "මෙම iPhone එක offline", .needsConfirmation: "ඔබගේ තහවුරු කිරීම අවශ්‍යයි",
            .confirmTitle: "කරුණාකර තහවුරු කරන්න", .allowOnce: "ඔව්, මෙවර පමණක්", .deny: "නැහැ, මෙය නොකරන්න", .standardMode: "සාමාන්‍ය Fabric", .openMithuru: "මිතුරු විවෘත කරන්න",
            .help: "උදව්", .helpBody: "කතා කරන්න ඔබා, ස්වභාවිකව කියන්න. අවශ්‍ය නම් පෙළ නිවැරදි කර යවන්න ඔබන්න. අවදි කිරීමේ වචනයක් නැත.",
            .privacyLocal: "කථනය මෙම iPhone එකේම පවතී", .privacyCloud: "අවශ්‍ය විට Apple cloud කථනයට අවසර ඇත",
            .readMessages: "මගේ පණිවිඩ කියවන්න", .messageFamily: "පවුලට පණිවිඩයක්", .setReminder: "මතක් කිරීමක්", .explainLetter: "ලිපියක් පැහැදිලි කරන්න", .appointments: "හමුවීම් බලන්න",
            .documentConsent: "මෙම ලේඛනය ඔබගේ Fabric gateway සහ තෝරාගත් AI සේවාව වෙත යැවිය හැක. ඉදිරියට යන්නද?", .chooseDocument: "ලේඛනය තෝරන්න", .cancel: "අවලංගු කරන්න",
            .voiceUnavailable: "මෙම භාෂාවට හඬ ලබාගත නොහැක. ඔබට ටයිප් කළ හැක.", .connectionError: "ඔබගේ Fabric වෙත සම්බන්ධ විය නොහැකි විය. සම්බන්ධතාව පරීක්ෂා කර නැවත උත්සාහ කරන්න."
        ],
        .tamil: [
            .brand: "மிதுரு", .welcome: "மிதுருவிற்கு வரவேற்கிறோம்",
            .languageQuestion: "எந்த மொழியை விரும்புகிறீர்கள்?", .interactionQuestion: "பேசவா, தட்டச்சு செய்யவா, இரண்டுமா?",
            .voiceAndText: "பேசவும் தட்டச்சு செய்யவும்", .textOnly: "தட்டச்சு மட்டும்",
            .textSizeQuestion: "எழுத்து எவ்வளவு பெரியதாக இருக்க வேண்டும்?", .large: "பெரியது", .extraLarge: "மிகப் பெரியது", .maximum: "அதிகபட்சம்",
            .speechRateQuestion: "மிதுரு எவ்வளவு வேகமாக பேச வேண்டும்?", .slow: "மெதுவாக", .normal: "இயல்பாக",
            .familyQuestion: "அமைப்பில் குடும்ப உறுப்பினர் உதவுகிறாரா?", .familyPrivacy: "உதவியாளர் அமைப்பை மாற்றலாம். ஆனால் நீங்கள் வெளிப்படையாகப் பகிராவிட்டால் உரையாடல்கள், பதிவுகள், ஆவணங்கள், செய்திகள், உடல்நல தகவல் அல்லது இருப்பிடத்தைப் பார்க்க முடியாது.",
            .cloudQuestion: "இந்த iPhone-இல் மொழியை அறிய முடியாதபோது Apple இணையப் பேச்சுச் சேவையைப் பயன்படுத்தலாமா?", .cloudExplanation: "ஆம் என்றால் பேச்சை அறிய மைக்ரோஃபோன் ஒலி இந்த iPhone-ஐ விட்டு வெளியேறலாம். Fabric உங்கள் gateway-க்கு உரையை மட்டுமே அனுப்பும்.",
            .yes: "ஆம்", .no: "இல்லை", .back: "பின்", .greeting: "நான் எப்படி உதவலாம்?",
            .talk: "பேசுங்கள்", .stopListening: "கேட்பதை நிறுத்து", .send: "அனுப்பு", .repeatAnswer: "மீண்டும் சொல்", .stopSpeaking: "பேசுவதை நிறுத்து",
            .editTranscript: "நான் கேட்டதைத் திருத்துங்கள்", .typeRequest: "உங்கள் கோரிக்கையைத் தட்டச்சு செய்யுங்கள்", .ready: "தயார்", .listening: "கேட்கிறேன்", .processing: "செய்கிறேன்", .speaking: "பேசுகிறேன்", .offline: "இந்த iPhone இணையமின்றி உள்ளது", .needsConfirmation: "உங்கள் உறுதிப்படுத்தல் தேவை",
            .confirmTitle: "உறுதிப்படுத்துங்கள்", .allowOnce: "ஆம், ஒருமுறை அனுமதி", .deny: "இல்லை, இதைச் செய்யாதே", .standardMode: "வழக்கமான Fabric", .openMithuru: "மிதுருவைத் திற",
            .help: "உதவி", .helpBody: "பேசுங்கள் என்பதைத் தொட்டு இயல்பாகப் பேசுங்கள். தேவையெனில் உரையைத் திருத்தி அனுப்பு என்பதைத் தொடுங்கள். விழிப்புச் சொல் இல்லை.",
            .privacyLocal: "பேச்சு இந்த iPhone-இலேயே இருக்கும்", .privacyCloud: "தேவைப்பட்டால் Apple cloud பேச்சுக்கு அனுமதி உண்டு",
            .readMessages: "என் செய்திகளை வாசி", .messageFamily: "குடும்பத்துக்கு செய்தி", .setReminder: "நினைவூட்டல் அமை", .explainLetter: "கடிதத்தை விளக்கு", .appointments: "சந்திப்புகளைப் பார்",
            .documentConsent: "இந்த ஆவணம் உங்கள் Fabric gateway மற்றும் தேர்ந்தெடுத்த AI சேவைக்கு அனுப்பப்படலாம். தொடரவா?", .chooseDocument: "ஆவணத்தைத் தேர்ந்தெடு", .cancel: "ரத்து",
            .voiceUnavailable: "இந்த மொழிக்கு குரல் கிடைக்கவில்லை. தொடர்ந்து தட்டச்சு செய்யலாம்.", .connectionError: "உங்கள் Fabric-ஐ அணுக முடியவில்லை. இணைப்பைச் சரிபார்த்து மீண்டும் முயலுங்கள்."
        ]
    ]
}
