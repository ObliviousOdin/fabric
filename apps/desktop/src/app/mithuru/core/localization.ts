export const MITHURU_LOCALES = ['si-LK', 'ta-LK', 'en-LK', 'en'] as const
export type MithuruLocale = (typeof MITHURU_LOCALES)[number]

export const MITHURU_LOCALE_NAMES: Record<MithuruLocale, string> = {
  'si-LK': 'සිංහල',
  'ta-LK': 'தமிழ்',
  'en-LK': 'English (Sri Lanka)',
  en: 'English'
}

const en = {
  'brand.name': 'Mithuru',
  'brand.reviewNote': 'The Sinhala and Tamil brand spellings need native-language review before release.',
  'nav.home': 'Home',
  'nav.help': 'Help',
  'nav.language': 'Language',
  'nav.settings': 'Settings',
  'nav.standardMode': 'Standard Fabric',
  'onboarding.title': 'Welcome to Mithuru',
  'onboarding.language.title': 'Which language would you like?',
  'onboarding.interaction.title': 'How would you like to use Mithuru?',
  'onboarding.interaction.voice': 'Speak and listen',
  'onboarding.interaction.text': 'Read and type',
  'onboarding.interaction.both': 'Both',
  'onboarding.textSize.title': 'Choose a text size',
  'onboarding.textSize.large': 'Large',
  'onboarding.textSize.extraLarge': 'Extra large',
  'onboarding.textSize.maximum': 'Maximum',
  'onboarding.speechRate.title': 'Choose the speaking speed',
  'onboarding.speechRate.slow': 'Slow',
  'onboarding.speechRate.normal': 'Normal',
  'onboarding.family.title': 'Is a family member helping with setup?',
  'onboarding.family.yes': 'Yes',
  'onboarding.family.no': 'No',
  'onboarding.cloud.title': 'May Mithuru use an online speech service?',
  'onboarding.cloud.explanation':
    'If you allow this, a recording of what you say may leave this device. Mithuru will show you when an online service is used. You can choose text instead.',
  'onboarding.continue': 'Continue',
  'onboarding.back': 'Back',
  'onboarding.finish': 'Start using Mithuru',
  'home.greeting': 'How can I help?',
  'home.talk': 'Talk',
  'home.stopListening': 'Stop listening',
  'home.typeInstead': 'Type instead',
  'home.repeat': 'Repeat',
  'home.stopSpeaking': 'Stop speaking',
  'home.cancel': 'Cancel',
  'home.retry': 'Try again',
  'home.send': 'Send',
  'home.editTranscript': 'Correct what I heard',
  'home.transcriptPlaceholder': 'Your conversation will appear here.',
  'home.inputPlaceholder': 'Type your request',
  'home.privacy.local': 'Microphone audio stays on this device until you choose to send text.',
  'home.privacy.cloud': 'Online speech may send audio to the selected speech service.',
  'privacy.manage': 'Speech privacy',
  'privacy.turnOffOnline': 'Turn off online speech',
  'privacy.turnOnOnline': 'Allow online speech',
  'state.idle': 'Ready',
  'state.listening': 'Listening. Tap again when you finish.',
  'state.processing': 'Working on your request.',
  'state.speaking': 'Speaking. Tap Stop to interrupt.',
  'state.needsConfirmation': 'Please confirm before I continue.',
  'state.offline': 'The internet connection is unavailable. You can still type.',
  'state.error': 'Something went wrong. Nothing was changed.',
  'suggest.messages': 'Read my messages',
  'suggest.family': 'Call or message family',
  'suggest.reminder': 'Set a reminder',
  'suggest.document': 'Explain a letter',
  'suggest.appointments': 'Check my appointments',
  'suggest.question': 'Ask a question',
  'confirm.title': 'Please check before continuing',
  'confirm.send': 'You asked me to send this message to {recipient}. Shall I send it?',
  'confirm.delete': 'This will delete {item}. Do you want me to continue?',
  'confirm.share': 'This may share your information with another service. Continue?',
  'confirm.schedule': 'Set this for {dateTime}?',
  'confirm.command': 'Command',
  'confirm.location': 'Location',
  'confirm.yes': 'Yes, continue',
  'confirm.no': 'No, cancel',
  'confirm.allowOnce': 'Allow once',
  'confirm.deny': 'Deny',
  'error.hearing': 'I could not hear clearly. Please try again. Nothing was sent.',
  'error.offline': 'The internet connection is unavailable. You can still type. Nothing was sent.',
  'error.speechUnsupported': 'This language is not available for speech on this device. You can type instead.',
  'error.onlineSpeechOff':
    'Online speech is off, so no audio was uploaded. Turn it on under Speech privacy or type instead.',
  'error.disconnected': 'Your device is no longer connected to Fabric. Open Pairing to reconnect.',
  'error.notSent': 'I did not send the message. Please try again.',
  'error.permission': 'Microphone access is off. Open system settings, or type instead.',
  'error.advanced': 'Advanced details',
  'help.title': 'Help',
  'help.body':
    'Tap Talk and speak. Tap again when you finish. You can type, correct the words, or ask Mithuru to repeat.',
  'family.title': 'Family Helper',
  'family.privacy':
    'This choice only records that a helper is present. It does not create separate access to conversations, recordings, documents, messages, health information, or location.',
  'family.contact': 'Contact my trusted helper',
  'document.choose': 'Choose a photo or document',
  'document.cloudConsent': 'This item may leave your device for explanation. Continue?',
  'document.attachments': 'Documents to send',
  'document.review': 'Review and include these documents',
  'document.reviewed': 'Documents reviewed',
  'document.remove': 'Remove {item}',
  'document.clearAll': 'Remove all',
  'document.uploading': 'Uploading',
  'document.error': 'Upload failed',
  'reminder.exactTime': 'Please check the exact date and time',
  'voice.provider.local': 'On this device',
  'voice.provider.cloud': 'Online service',
  'voice.provider.textOnly': 'Text only',
  'voice.unavailable': 'Speech is unavailable for this language. Text input still works.',
  'accessibility.talkHint': 'Starts microphone recording only after permission is granted',
  'accessibility.status': 'Mithuru status'
} as const

export type MithuruMessageKey = keyof typeof en
type Catalog = Record<MithuruMessageKey, string>

const si: Catalog = {
  'brand.name': 'මිතුරු',
  'brand.reviewNote':
    'නිකුත් කිරීමට පෙර සිංහල සහ දෙමළ වෙළඳ නාම අක්ෂර වින්‍යාසය ස්වදේශීය භාෂා විශේෂඥයෙකු විසින් සමාලෝචනය කළ යුතුය.',
  'nav.home': 'මුල් පිටුව',
  'nav.help': 'උදව්',
  'nav.language': 'භාෂාව',
  'nav.settings': 'සැකසුම්',
  'nav.standardMode': 'සාමාන්‍ය Fabric',
  'onboarding.title': 'මිතුරු වෙත සාදරයෙන් පිළිගනිමු',
  'onboarding.language.title': 'ඔබ කැමති භාෂාව කුමක්ද?',
  'onboarding.interaction.title': 'මිතුරු භාවිත කිරීමට ඔබ කැමති කෙසේද?',
  'onboarding.interaction.voice': 'කතා කර අසන්න',
  'onboarding.interaction.text': 'කියවා ටයිප් කරන්න',
  'onboarding.interaction.both': 'දෙකම',
  'onboarding.textSize.title': 'අකුරු ප්‍රමාණය තෝරන්න',
  'onboarding.textSize.large': 'විශාල',
  'onboarding.textSize.extraLarge': 'ඉතා විශාල',
  'onboarding.textSize.maximum': 'උපරිම',
  'onboarding.speechRate.title': 'කතා කිරීමේ වේගය තෝරන්න',
  'onboarding.speechRate.slow': 'මන්දගාමී',
  'onboarding.speechRate.normal': 'සාමාන්‍ය',
  'onboarding.family.title': 'පවුලේ අයෙකු සැකසුමට උදව් කරනවාද?',
  'onboarding.family.yes': 'ඔව්',
  'onboarding.family.no': 'නැහැ',
  'onboarding.cloud.title': 'මිතුරුට අන්තර්ජාල කථන සේවාවක් භාවිත කළ හැකිද?',
  'onboarding.cloud.explanation':
    'ඔබ ඉඩ දුන්නොත්, ඔබ කතා කරන හඬ පටිගත කිරීමක් මෙම උපාංගයෙන් පිටතට යා හැක. අන්තර්ජාල සේවාවක් භාවිත කරන විට මිතුරු ඔබට පෙන්වයි. ඔබට ටයිප් කිරීම තෝරාගත හැක.',
  'onboarding.continue': 'ඉදිරියට',
  'onboarding.back': 'ආපසු',
  'onboarding.finish': 'මිතුරු භාවිත කරන්න',
  'home.greeting': 'මම කෙසේ උදව් කරන්නද?',
  'home.talk': 'කතා කරන්න',
  'home.stopListening': 'අසන එක නවත්වන්න',
  'home.typeInstead': 'ටයිප් කරන්න',
  'home.repeat': 'නැවත කියන්න',
  'home.stopSpeaking': 'කතා කිරීම නවත්වන්න',
  'home.cancel': 'අවලංගු කරන්න',
  'home.retry': 'නැවත උත්සාහ කරන්න',
  'home.send': 'යවන්න',
  'home.editTranscript': 'ඇසුණු දේ නිවැරදි කරන්න',
  'home.transcriptPlaceholder': 'ඔබගේ සංවාදය මෙහි පෙන්වයි.',
  'home.inputPlaceholder': 'ඔබගේ ඉල්ලීම ටයිප් කරන්න',
  'home.privacy.local': 'ඔබ පෙළ යැවීමට තෝරාගන්නා තෙක් මයික්‍රොෆෝන හඬ මෙම උපාංගයේ රැඳේ.',
  'home.privacy.cloud': 'අන්තර්ජාල කථන සේවාවට හඬ යැවිය හැක.',
  'privacy.manage': 'කථන පෞද්ගලිකත්වය',
  'privacy.turnOffOnline': 'අන්තර්ජාල කථනය අක්‍රිය කරන්න',
  'privacy.turnOnOnline': 'අන්තර්ජාල කථනයට ඉඩ දෙන්න',
  'state.idle': 'සූදානම්',
  'state.listening': 'අසමින් සිටී. අවසන් වූ විට නැවත තට්ටු කරන්න.',
  'state.processing': 'ඔබගේ ඉල්ලීම සකසමින් සිටී.',
  'state.speaking': 'කතා කරමින් සිටී. නවත්වන්න තට්ටු කරන්න.',
  'state.needsConfirmation': 'ඉදිරියට යාමට පෙර තහවුරු කරන්න.',
  'state.offline': 'අන්තර්ජාල සම්බන්ධතාව නැත. ඔබට තවමත් ටයිප් කළ හැක.',
  'state.error': 'දෝෂයක් ඇති විය. කිසිවක් වෙනස් කළේ නැත.',
  'suggest.messages': 'මගේ පණිවිඩ කියවන්න',
  'suggest.family': 'පවුලට අමතන්න හෝ පණිවිඩයක් යවන්න',
  'suggest.reminder': 'මතක් කිරීමක් සකසන්න',
  'suggest.document': 'ලිපියක් පැහැදිලි කරන්න',
  'suggest.appointments': 'මගේ හමුවීම් බලන්න',
  'suggest.question': 'ප්‍රශ්නයක් අසන්න',
  'confirm.title': 'ඉදිරියට යාමට පෙර පරීක්ෂා කරන්න',
  'confirm.send': 'ඔබ {recipient} වෙත මෙම පණිවිඩය යැවීමට ඉල්ලා ඇත. යවන්නද?',
  'confirm.delete': 'මෙයින් {item} මකනු ඇත. ඉදිරියට යන්නද?',
  'confirm.share': 'මෙය ඔබගේ තොරතුරු වෙනත් සේවාවක් සමඟ බෙදා ගත හැක. ඉදිරියට යන්නද?',
  'confirm.schedule': 'මෙය {dateTime} සඳහා සකසන්නද?',
  'confirm.command': 'විධානය',
  'confirm.location': 'ස්ථානය',
  'confirm.yes': 'ඔව්, ඉදිරියට',
  'confirm.no': 'නැහැ, අවලංගු කරන්න',
  'confirm.allowOnce': 'එක් වරක් ඉඩ දෙන්න',
  'confirm.deny': 'ප්‍රතික්ෂේප කරන්න',
  'error.hearing': 'මට පැහැදිලිව ඇසුණේ නැත. නැවත උත්සාහ කරන්න. කිසිවක් යැව්වේ නැත.',
  'error.offline': 'අන්තර්ජාල සම්බන්ධතාව නැත. ඔබට ටයිප් කළ හැක. කිසිවක් යැව්වේ නැත.',
  'error.speechUnsupported': 'මෙම උපාංගයේ මෙම භාෂාවට කථනය නොමැත. ඔබට ටයිප් කළ හැක.',
  'error.onlineSpeechOff':
    'අන්තර්ජාල කථනය අක්‍රියයි, එබැවින් හඬ යැව්වේ නැත. කථන පෞද්ගලිකත්වය යටතේ එය සක්‍රිය කරන්න හෝ ටයිප් කරන්න.',
  'error.disconnected': 'ඔබගේ උපාංගය Fabric සමඟ සම්බන්ධ නැත. නැවත සම්බන්ධ වීමට Pairing විවෘත කරන්න.',
  'error.notSent': 'මම පණිවිඩය යැව්වේ නැත. නැවත උත්සාහ කරන්න.',
  'error.permission': 'මයික්‍රොෆෝන අවසරය අක්‍රියයි. පද්ධති සැකසුම් විවෘත කරන්න හෝ ටයිප් කරන්න.',
  'error.advanced': 'තාක්ෂණික විස්තර',
  'help.title': 'උදව්',
  'help.body':
    'කතා කරන්න තට්ටු කර කතා කරන්න. අවසන් වූ විට නැවත තට්ටු කරන්න. ඔබට ටයිප් කිරීමට, වචන නිවැරදි කිරීමට හෝ නැවත කියන්න කියා ඉල්ලීමට හැක.',
  'family.title': 'පවුලේ සහායකයා',
  'family.privacy':
    'මෙම තේරීම සහායකයෙකු සිටින බව පමණක් සටහන් කරයි. එය සංවාද, හඬ, ලේඛන, පණිවිඩ, සෞඛ්‍ය තොරතුරු හෝ ස්ථානයට වෙනම ප්‍රවේශයක් ලබා නොදේ.',
  'family.contact': 'විශ්වාසවන්ත සහායකයා අමතන්න',
  'document.choose': 'ඡායාරූපයක් හෝ ලේඛනයක් තෝරන්න',
  'document.cloudConsent': 'පැහැදිලි කිරීම සඳහා මෙය ඔබගේ උපාංගයෙන් පිටතට යා හැක. ඉදිරියට යන්නද?',
  'document.attachments': 'යැවීමට ඇති ලේඛන',
  'document.review': 'මෙම ලේඛන පරීක්ෂා කර ඇතුළත් කරන්න',
  'document.reviewed': 'ලේඛන පරීක්ෂා කර ඇත',
  'document.remove': '{item} ඉවත් කරන්න',
  'document.clearAll': 'සියල්ල ඉවත් කරන්න',
  'document.uploading': 'උඩුගත කරමින්',
  'document.error': 'උඩුගත කිරීම අසාර්ථකයි',
  'reminder.exactTime': 'නිවැරදි දිනය සහ වේලාව පරීක්ෂා කරන්න',
  'voice.provider.local': 'මෙම උපාංගයේ',
  'voice.provider.cloud': 'අන්තර්ජාල සේවාව',
  'voice.provider.textOnly': 'පෙළ පමණයි',
  'voice.unavailable': 'මෙම භාෂාවට කථනය නොමැත. පෙළ තවමත් ක්‍රියා කරයි.',
  'accessibility.talkHint': 'අවසරය ලැබුණු පසු පමණක් මයික්‍රොෆෝන පටිගත කිරීම ආරම්භ කරයි',
  'accessibility.status': 'මිතුරු තත්ත්වය'
}

const ta: Catalog = {
  'brand.name': 'மிதுரு',
  'brand.reviewNote':
    'வெளியீட்டுக்கு முன் சிங்களம் மற்றும் தமிழ் பிராண்ட் எழுத்துப்பெயர்கள் தாய்மொழி நிபுணரால் மதிப்பாய்வு செய்யப்பட வேண்டும்.',
  'nav.home': 'முகப்பு',
  'nav.help': 'உதவி',
  'nav.language': 'மொழி',
  'nav.settings': 'அமைப்புகள்',
  'nav.standardMode': 'வழக்கமான Fabric',
  'onboarding.title': 'மிதுருவிற்கு வரவேற்கிறோம்',
  'onboarding.language.title': 'எந்த மொழியை விரும்புகிறீர்கள்?',
  'onboarding.interaction.title': 'மிதுருவை எவ்வாறு பயன்படுத்த விரும்புகிறீர்கள்?',
  'onboarding.interaction.voice': 'பேசிக் கேட்க',
  'onboarding.interaction.text': 'படித்துத் தட்டச்சு செய்ய',
  'onboarding.interaction.both': 'இரண்டும்',
  'onboarding.textSize.title': 'எழுத்தளவைத் தேர்ந்தெடுக்கவும்',
  'onboarding.textSize.large': 'பெரியது',
  'onboarding.textSize.extraLarge': 'மிகப் பெரிது',
  'onboarding.textSize.maximum': 'அதிகபட்சம்',
  'onboarding.speechRate.title': 'பேச்சு வேகத்தைத் தேர்ந்தெடுக்கவும்',
  'onboarding.speechRate.slow': 'மெதுவாக',
  'onboarding.speechRate.normal': 'இயல்பு',
  'onboarding.family.title': 'குடும்ப உறுப்பினர் அமைக்க உதவுகிறாரா?',
  'onboarding.family.yes': 'ஆம்',
  'onboarding.family.no': 'இல்லை',
  'onboarding.cloud.title': 'மிதுரு இணைய பேச்சுச் சேவையைப் பயன்படுத்தலாமா?',
  'onboarding.cloud.explanation':
    'நீங்கள் அனுமதித்தால், உங்கள் குரல் பதிவு இந்தச் சாதனத்தை விட்டு வெளியேறலாம். இணையச் சேவை பயன்படுத்தப்படும் போது மிதுரு காட்டும். நீங்கள் தட்டச்சைத் தேர்ந்தெடுக்கலாம்.',
  'onboarding.continue': 'தொடர்க',
  'onboarding.back': 'பின்',
  'onboarding.finish': 'மிதுருவைப் பயன்படுத்த தொடங்குக',
  'home.greeting': 'நான் எப்படி உதவலாம்?',
  'home.talk': 'பேசுங்கள்',
  'home.stopListening': 'கேட்பதை நிறுத்து',
  'home.typeInstead': 'தட்டச்சு செய்யுங்கள்',
  'home.repeat': 'மீண்டும் சொல்லுங்கள்',
  'home.stopSpeaking': 'பேசுவதை நிறுத்து',
  'home.cancel': 'ரத்துசெய்',
  'home.retry': 'மீண்டும் முயல்க',
  'home.send': 'அனுப்பு',
  'home.editTranscript': 'கேட்டதைத் திருத்துங்கள்',
  'home.transcriptPlaceholder': 'உங்கள் உரையாடல் இங்கே தோன்றும்.',
  'home.inputPlaceholder': 'உங்கள் கோரிக்கையைத் தட்டச்சு செய்யுங்கள்',
  'home.privacy.local': 'நீங்கள் உரையை அனுப்பும் வரை ஒலிவாங்கி ஒலி இந்தச் சாதனத்திலேயே இருக்கும்.',
  'home.privacy.cloud': 'இணைய பேச்சுச் சேவை தேர்ந்தெடுக்கப்பட்ட சேவைக்கு ஒலியை அனுப்பலாம்.',
  'privacy.manage': 'பேச்சுத் தனியுரிமை',
  'privacy.turnOffOnline': 'இணையப் பேச்சை நிறுத்து',
  'privacy.turnOnOnline': 'இணையப் பேச்சை அனுமதி',
  'state.idle': 'தயார்',
  'state.listening': 'கேட்கிறேன். முடிந்ததும் மீண்டும் தட்டுங்கள்.',
  'state.processing': 'உங்கள் கோரிக்கையைச் செய்கிறேன்.',
  'state.speaking': 'பேசுகிறேன். நிறுத்த தட்டுங்கள்.',
  'state.needsConfirmation': 'தொடர்வதற்கு முன் உறுதிப்படுத்துங்கள்.',
  'state.offline': 'இணைய இணைப்பு இல்லை. நீங்கள் இன்னும் தட்டச்சு செய்யலாம்.',
  'state.error': 'பிழை ஏற்பட்டது. எதுவும் மாற்றப்படவில்லை.',
  'suggest.messages': 'என் செய்திகளைப் படி',
  'suggest.family': 'குடும்பத்தினரை அழை அல்லது செய்தி அனுப்பு',
  'suggest.reminder': 'நினைவூட்டல் அமை',
  'suggest.document': 'ஒரு கடிதத்தை விளக்கு',
  'suggest.appointments': 'என் சந்திப்புகளைப் பார்',
  'suggest.question': 'ஒரு கேள்வி கேள்',
  'confirm.title': 'தொடர்வதற்கு முன் சரிபார்க்கவும்',
  'confirm.send': 'இந்தச் செய்தியை {recipient}க்கு அனுப்பச் சொன்னீர்கள். அனுப்பவா?',
  'confirm.delete': 'இது {item}ஐ நீக்கும். தொடரவா?',
  'confirm.share': 'இது உங்கள் தகவலை வேறு சேவையுடன் பகிரலாம். தொடரவா?',
  'confirm.schedule': 'இதை {dateTime}க்கு அமைக்கவா?',
  'confirm.command': 'கட்டளை',
  'confirm.location': 'இடம்',
  'confirm.yes': 'ஆம், தொடர்க',
  'confirm.no': 'இல்லை, ரத்துசெய்',
  'confirm.allowOnce': 'ஒருமுறை அனுமதி',
  'confirm.deny': 'மறு',
  'error.hearing': 'தெளிவாகக் கேட்கவில்லை. மீண்டும் முயல்க. எதுவும் அனுப்பப்படவில்லை.',
  'error.offline': 'இணைய இணைப்பு இல்லை. நீங்கள் தட்டச்சு செய்யலாம். எதுவும் அனுப்பப்படவில்லை.',
  'error.speechUnsupported': 'இந்தச் சாதனத்தில் இந்த மொழிக்குப் பேச்சு வசதி இல்லை. தட்டச்சு செய்யலாம்.',
  'error.onlineSpeechOff':
    'இணையப் பேச்சு முடக்கப்பட்டுள்ளது; அதனால் ஒலி அனுப்பப்படவில்லை. பேச்சுத் தனியுரிமையில் அதை இயக்கவும் அல்லது தட்டச்சு செய்யவும்.',
  'error.disconnected': 'உங்கள் சாதனம் Fabric உடன் இணைக்கப்படவில்லை. மீண்டும் இணைக்க Pairingஐத் திறக்கவும்.',
  'error.notSent': 'நான் செய்தியை அனுப்பவில்லை. மீண்டும் முயல்க.',
  'error.permission': 'ஒலிவாங்கி அனுமதி முடக்கப்பட்டுள்ளது. அமைப்புகளைத் திறக்கவும் அல்லது தட்டச்சு செய்யவும்.',
  'error.advanced': 'தொழில்நுட்ப விவரங்கள்',
  'help.title': 'உதவி',
  'help.body':
    'பேசுங்கள் என்பதைத் தட்டி பேசுங்கள். முடிந்ததும் மீண்டும் தட்டுங்கள். நீங்கள் தட்டச்சு செய்யலாம், சொற்களைத் திருத்தலாம் அல்லது மீண்டும் சொல்லச் கேட்கலாம்.',
  'family.title': 'குடும்ப உதவியாளர்',
  'family.privacy':
    'இந்தத் தேர்வு உதவியாளர் இருப்பதை மட்டும் பதிவு செய்கிறது. உரையாடல்கள், குரல் பதிவுகள், ஆவணங்கள், செய்திகள், உடல்நலத் தகவல் அல்லது இருப்பிடத்திற்கு தனி அணுகலை வழங்காது.',
  'family.contact': 'நம்பகமான உதவியாளரைத் தொடர்புகொள்',
  'document.choose': 'படம் அல்லது ஆவணத்தைத் தேர்ந்தெடு',
  'document.cloudConsent': 'விளக்குவதற்காக இது உங்கள் சாதனத்தை விட்டு வெளியேறலாம். தொடரவா?',
  'document.attachments': 'அனுப்ப வேண்டிய ஆவணங்கள்',
  'document.review': 'இந்த ஆவணங்களைச் சரிபார்த்து சேர்க்கவும்',
  'document.reviewed': 'ஆவணங்கள் சரிபார்க்கப்பட்டன',
  'document.remove': '{item} ஐ அகற்று',
  'document.clearAll': 'அனைத்தையும் அகற்று',
  'document.uploading': 'பதிவேற்றுகிறது',
  'document.error': 'பதிவேற்றம் தோல்வியடைந்தது',
  'reminder.exactTime': 'சரியான தேதியையும் நேரத்தையும் சரிபார்க்கவும்',
  'voice.provider.local': 'இந்தச் சாதனத்தில்',
  'voice.provider.cloud': 'இணையச் சேவை',
  'voice.provider.textOnly': 'உரை மட்டும்',
  'voice.unavailable': 'இந்த மொழிக்குப் பேச்சு கிடைக்கவில்லை. உரை உள்ளீடு இயங்கும்.',
  'accessibility.talkHint': 'அனுமதி கிடைத்த பிறகே ஒலிவாங்கி பதிவைத் தொடங்கும்',
  'accessibility.status': 'மிதுரு நிலை'
}

export const MITHURU_MESSAGES: Record<MithuruLocale, Catalog> = {
  'si-LK': si,
  'ta-LK': ta,
  'en-LK': en,
  en
}

export function normalizeMithuruLocale(value: string | null | undefined): MithuruLocale {
  const normalized = value?.replace('_', '-').toLowerCase() ?? ''

  if (normalized.startsWith('si')) {
    return 'si-LK'
  }

  if (normalized.startsWith('ta')) {
    return 'ta-LK'
  }

  if (normalized === 'en-lk') {
    return 'en-LK'
  }

  return 'en'
}

export function mithuruTranslate(
  locale: MithuruLocale,
  key: MithuruMessageKey,
  variables: Record<string, string> = {}
): string {
  let message: string = MITHURU_MESSAGES[locale][key] ?? en[key]

  for (const [name, value] of Object.entries(variables)) {
    message = message.replaceAll(`{${name}}`, value)
  }

  return message
}

export function missingMithuruTranslationKeys(locale: MithuruLocale): MithuruMessageKey[] {
  return (Object.keys(en) as MithuruMessageKey[]).filter(key => !MITHURU_MESSAGES[locale][key]?.trim())
}

export function pseudolocalizeMithuru(text: string): string {
  const expanded = text.replace(/[aeiou]/gi, letter => `${letter}${letter.toLowerCase()}`)

  return `［${expanded} ···］`
}

export function formatMithuruDateTime(date: Date, locale: MithuruLocale, timeZone: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'full',
    timeStyle: 'short',
    timeZone
  }).format(date)
}
