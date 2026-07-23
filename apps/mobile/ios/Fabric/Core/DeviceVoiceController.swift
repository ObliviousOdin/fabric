import AVFoundation
import Foundation
import Observation
import Speech

/// User-facing failures from the device voice path. None of these messages
/// contain raw Speech framework or audio-session errors.
enum DeviceVoiceIssue: String, Identifiable, Equatable {
    case speechUnavailable
    case speechPermissionDenied
    case speechPermissionRestricted
    case microphonePermissionDenied
    case audioInputUnavailable
    case recognitionFailed
    case playbackFailed
    case voiceModeInterrupted

    var id: String { rawValue }

    var title: String {
        switch self {
        case .speechUnavailable: return "Dictation unavailable"
        case .speechPermissionDenied: return "Speech Recognition is off"
        case .speechPermissionRestricted: return "Speech Recognition is restricted"
        case .microphonePermissionDenied: return "Microphone access is off"
        case .audioInputUnavailable: return "Microphone unavailable"
        case .recognitionFailed: return "Dictation stopped"
        case .playbackFailed: return "Read aloud unavailable"
        case .voiceModeInterrupted: return "Voice Mode ended"
        }
    }

    var message: String {
        switch self {
        case .speechUnavailable:
            return "Apple Speech is not available for the current iPhone language right now. Try again later or type your message."
        case .speechPermissionDenied:
            return "Allow Speech Recognition for Fabric in iOS Settings to dictate a message."
        case .speechPermissionRestricted:
            return "This iPhone prevents apps from using speech recognition. Check Screen Time or device-management restrictions."
        case .microphonePermissionDenied:
            return "Allow Microphone access for Fabric in iOS Settings to dictate a message."
        case .audioInputUnavailable:
            return "Fabric couldn't start an audio input on this iPhone. Check the current audio route, then try again."
        case .recognitionFailed:
            return "Fabric couldn't continue speech recognition. Your latest transcript remains in the message draft."
        case .playbackFailed:
            return "Fabric couldn't start spoken-audio playback on this iPhone. Check the current audio route, then try again."
        case .voiceModeInterrupted:
            return "Audio on this iPhone was interrupted, so Voice Mode turned off. Everything already said stays in the conversation. Start Voice Mode again when you're ready."
        }
    }

    var canOpenSettings: Bool {
        self == .speechPermissionDenied || self == .microphonePermissionDenied
    }
}

enum DeviceDictationState: Equatable {
    case idle
    case requestingPermission
    case listening
    case finalizing

    var isListening: Bool { self == .listening }
    var isActive: Bool { self != .idle }
    var locksDraft: Bool { self != .idle }

    var stopAction: DeviceDictationStopAction {
        switch self {
        case .idle, .finalizing: return .none
        case .requestingPermission: return .cancel
        case .listening: return .finish
        }
    }
}

enum DeviceDictationStopAction: Equatable {
    case none
    case cancel
    case finish
}

enum DeviceVoiceRouteChangePolicy {
    static func invalidatesCurrentRoute(_ reason: AVAudioSession.RouteChangeReason) -> Bool {
        reason != .categoryChange && reason != .override
    }
}

/// Keeps a user's pre-existing draft byte-for-byte and appends the current
/// partial transcript. The transcript is never submitted automatically.
enum VoiceDraftComposer {
    static func merging(baseDraft: String, transcript: String) -> String {
        guard !transcript.isEmpty else { return baseDraft }
        guard !baseDraft.isEmpty else { return transcript }
        let separator = baseDraft.last?.isWhitespace == true ? "" : " "
        return baseDraft + separator + transcript
    }
}

struct DeviceVoiceOption: Identifiable, Equatable {
    let identifier: String
    let name: String
    let language: String
    let quality: String

    var id: String { identifier }

    var displayName: String {
        quality.isEmpty ? "\(name) · \(language)" : "\(name) · \(language) · \(quality)"
    }
}

/// Device-only preference for AVSpeechSynthesizer. An empty identifier means
/// Fabric follows the current iPhone language and chooses the best installed
/// matching voice.
enum DeviceVoicePreferences {
    static let selectedVoiceIdentifierKey = "deviceVoice.selectedVoiceIdentifier"

    static func options(
        voices: [AVSpeechSynthesisVoice] = AVSpeechSynthesisVoice.speechVoices()
    ) -> [DeviceVoiceOption] {
        voices
            .map { voice in
                DeviceVoiceOption(
                    identifier: voice.identifier,
                    name: voice.name,
                    language: voice.language,
                    quality: qualityLabel(voice.quality)
                )
            }
            .sorted {
                if $0.language != $1.language {
                    return $0.language.localizedCaseInsensitiveCompare($1.language) == .orderedAscending
                }
                if $0.name != $1.name {
                    return $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
                }
                return $0.identifier < $1.identifier
            }
    }

    static func selectedVoice(
        defaults: UserDefaults = .standard,
        voices: [AVSpeechSynthesisVoice] = AVSpeechSynthesisVoice.speechVoices(),
        preferredLanguages: [String] = Locale.preferredLanguages
    ) -> AVSpeechSynthesisVoice? {
        let selectedIdentifier = defaults.string(forKey: selectedVoiceIdentifierKey) ?? ""
        if !selectedIdentifier.isEmpty,
           let selected = voices.first(where: { $0.identifier == selectedIdentifier }) {
            return selected
        }

        let preferredLanguage = preferredLanguages.first ?? Locale.current.identifier
        let preferredCode = Locale(identifier: preferredLanguage).language.languageCode?.identifier
        let matching = voices.filter { voice in
            let voiceCode = Locale(identifier: voice.language).language.languageCode?.identifier
            return preferredCode != nil && voiceCode == preferredCode
        }
        if let bestMatch = matching.max(by: { $0.quality.rawValue < $1.quality.rawValue }) {
            return bestMatch
        }
        return AVSpeechSynthesisVoice(language: preferredLanguage)
    }

    static func displayName(
        for identifier: String,
        voices: [AVSpeechSynthesisVoice] = AVSpeechSynthesisVoice.speechVoices()
    ) -> String {
        guard !identifier.isEmpty,
              let voice = voices.first(where: { $0.identifier == identifier }) else {
            return "Best installed voice"
        }
        let quality = qualityLabel(voice.quality)
        return quality.isEmpty
            ? "\(voice.name) · \(voice.language)"
            : "\(voice.name) · \(voice.language) · \(quality)"
    }

    static func normalizedIdentifier(
        _ identifier: String,
        options: [DeviceVoiceOption] = options()
    ) -> String {
        guard !identifier.isEmpty else { return "" }
        return options.contains(where: { $0.identifier == identifier }) ? identifier : ""
    }

    private static func qualityLabel(_ quality: AVSpeechSynthesisVoiceQuality) -> String {
        switch quality {
        case .premium: return "Premium"
        case .enhanced: return "Enhanced"
        case .default: return ""
        @unknown default: return ""
        }
    }
}

/// Converts assistant Markdown into speech-friendly text. Technical blocks are
/// acknowledged but not read character-by-character, and the utterance is
/// bounded so a pathological response cannot enqueue unbounded speech.
enum DeviceVoiceText {
    static let maximumCharacters = 20_000

    static func spokenText(from source: String) -> String {
        let document = AssistantTranscriptDocument(source)
        let pieces = document.blocks.compactMap { block -> String? in
            switch block {
            case .paragraph(let markdown), .heading(_, let markdown), .listItem(_, _, let markdown):
                let text = String(AssistantMarkdownSafety.attributedString(from: markdown).characters)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                return text.isEmpty ? nil : text
            case .code:
                return "Code block omitted."
            case .diff:
                return "Code diff omitted."
            }
        }
        let joined = pieces.joined(separator: "\n")
        guard joined.count > maximumCharacters else { return joined }
        return String(joined.prefix(maximumCharacters - 1)) + "…"
    }
}

/// Native iPhone voice implementation. Dictation uses Apple's Speech framework
/// and prefers its on-device recognizer whenever the current locale supports
/// one; otherwise iOS may use Apple's speech service. Read-aloud uses an
/// installed AVSpeechSynthesizer voice. Fabric never sends phone audio to the
/// gateway and never persists microphone buffers.
@Observable
@MainActor
final class DeviceVoiceController: NSObject, AVSpeechSynthesizerDelegate {
    private(set) var dictationState: DeviceDictationState = .idle
    private(set) var transcript = ""
    private(set) var speakingMessageID: UUID?
    private(set) var issue: DeviceVoiceIssue?
    private(set) var voiceModePhase: VoiceModePhase = .inactive
    private(set) var voiceModeAgentSnapshot: VoiceModeAgentSnapshot = .idle

    /// Chat installs the prompt-submission path. The controller never talks to
    /// the gateway itself; it only hands over the final utterance text.
    @ObservationIgnored var onVoiceModeSubmit: ((String) async -> Bool)?

    @ObservationIgnored private let audioEngine = AVAudioEngine()
    @ObservationIgnored private let synthesizer = AVSpeechSynthesizer()
    @ObservationIgnored private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    @ObservationIgnored private var recognitionTask: SFSpeechRecognitionTask?
    @ObservationIgnored private var inputTapInstalled = false
    @ObservationIgnored private var dictationRunID = UUID()
    @ObservationIgnored private var finalizationTask: Task<Void, Never>?
    @ObservationIgnored private var activeUtterance: AVSpeechUtterance?
    @ObservationIgnored private var voiceModeWatchdog: Task<Void, Never>?
    @ObservationIgnored private var voiceModeLocale = Locale.current
    @ObservationIgnored private var voiceModeListeningStartedAt = Date()
    @ObservationIgnored private var voiceModeLastTranscriptChangeAt = Date()
    @ObservationIgnored private var voiceModeLastSeenTranscript = ""
    @ObservationIgnored private var voiceModeConsecutiveCaptureFailures = 0
    @ObservationIgnored private var voiceModeBaselineReplyID: UUID?
    @ObservationIgnored private var voiceModeSawAgentBusy = false
    @ObservationIgnored private var voiceModeWaitingStartedAt = Date()
    @ObservationIgnored private var voiceModeSpeakingStartedAt = Date()
    @ObservationIgnored private var voiceModeSpeakingTimeout: TimeInterval = 0
    @ObservationIgnored private let voiceModeListenPolicy = VoiceModeListenPolicy.standard

    var isListening: Bool { dictationState.isListening }
    var isSpeaking: Bool { speakingMessageID != nil }
    var voiceModeActive: Bool { voiceModePhase.isActive }

    override init() {
        super.init()
        synthesizer.delegate = self

        let center = NotificationCenter.default
        center.addObserver(self, selector: #selector(audioSessionInterrupted(_:)), name: AVAudioSession.interruptionNotification, object: nil)
        center.addObserver(self, selector: #selector(audioRouteChanged(_:)), name: AVAudioSession.routeChangeNotification, object: nil)
        center.addObserver(self, selector: #selector(audioEngineConfigurationChanged(_:)), name: .AVAudioEngineConfigurationChange, object: audioEngine)
        center.addObserver(self, selector: #selector(audioMediaServicesReset(_:)), name: AVAudioSession.mediaServicesWereResetNotification, object: nil)
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    func clearIssue() {
        issue = nil
    }

    func toggleDictation(locale: Locale = .current) async {
        guard !voiceModeActive else { return }
        switch dictationState.stopAction {
        case .none:
            guard dictationState == .idle else { return }
            await startDictation(locale: locale)
        case .cancel:
            cancelDictation()
        case .finish:
            finishDictation()
        }
    }

    func startDictation(locale: Locale = .current) async {
        issue = nil
        stopSpeaking()
        let authorizationRunID = UUID()
        dictationRunID = authorizationRunID
        dictationState = .requestingPermission

        let speechAuthorization = await speechAuthorizationStatus()
        guard dictationRunID == authorizationRunID else { return }
        guard speechAuthorization == .authorized else {
            dictationState = .idle
            switch speechAuthorization {
            case .denied:
                issue = .speechPermissionDenied
            case .restricted:
                issue = .speechPermissionRestricted
            case .authorized, .notDetermined:
                issue = .speechUnavailable
            @unknown default:
                issue = .speechUnavailable
            }
            return
        }

        let microphoneAuthorized = await requestMicrophoneAuthorization()
        guard dictationRunID == authorizationRunID else { return }
        guard microphoneAuthorized else {
            dictationState = .idle
            issue = .microphonePermissionDenied
            return
        }

        guard let recognizer = SFSpeechRecognizer(locale: locale), recognizer.isAvailable else {
            dictationState = .idle
            issue = .speechUnavailable
            return
        }

        cancelDictation()
        issue = nil
        transcript = ""
        let runID = UUID()
        dictationRunID = runID

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.taskHint = .dictation
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
        recognitionRequest = request

        do {
            let audioSession = AVAudioSession.sharedInstance()
            let recordingOptions: AVAudioSession.CategoryOptions = [
                .duckOthers,
                .allowBluetooth,
            ]
            try audioSession.setCategory(
                .playAndRecord,
                mode: .measurement,
                options: recordingOptions
            )
            try audioSession.setActive(true)

            // Read the input format only after the category and current route
            // are active. Bluetooth or headset activation can change the
            // hardware format; installing a tap with the stale pre-route
            // format can fail on a physical phone.
            let inputNode = audioEngine.inputNode
            let format = inputNode.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else {
                cancelDictation()
                issue = .audioInputUnavailable
                return
            }

            inputNode.installTap(onBus: 0, bufferSize: 1_024, format: format) {
                [weak request] buffer, _ in
                request?.append(buffer)
            }
            inputTapInstalled = true
            audioEngine.prepare()
            try audioEngine.start()
        } catch {
            cancelDictation()
            issue = .audioInputUnavailable
            return
        }

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor [weak self] in
                guard let self, self.dictationRunID == runID else { return }
                if let result {
                    self.transcript = result.bestTranscription.formattedString
                    if result.isFinal {
                        self.completeDictation(runID: runID, cancelRecognition: false)
                        self.voiceModeCaptureEnded(failed: false)
                        return
                    }
                }
                if error != nil {
                    let wasFinalizing = self.dictationState == .finalizing
                    self.completeDictation(runID: runID, cancelRecognition: true)
                    if !wasFinalizing { self.issue = .recognitionFailed }
                    // A finalize-phase error still delivered every partial the
                    // user said; only an error while listening counts against
                    // the Voice Mode recovery budget.
                    self.voiceModeCaptureEnded(failed: !wasFinalizing)
                }
            }
        }
        dictationState = .listening
    }

    func stopDictation() {
        switch dictationState.stopAction {
        case .none: return
        case .cancel: cancelDictation()
        case .finish: finishDictation()
        }
    }

    func toggleReadAloud(messageID: UUID, text: String) {
        guard !voiceModeActive else { return }
        if speakingMessageID == messageID {
            stopSpeaking()
            return
        }

        let spokenText = DeviceVoiceText.spokenText(from: text)
        guard !spokenText.isEmpty else { return }
        issue = nil
        _ = beginSpeaking(messageID: messageID, spokenText: spokenText)
    }

    /// Shared playback start for read-aloud and Voice Mode replies.
    private func beginSpeaking(messageID: UUID, spokenText: String) -> Bool {
        cancelDictation()
        stopSpeaking()

        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
            try audioSession.setActive(true)
        } catch {
            issue = .playbackFailed
            return false
        }

        let utterance = AVSpeechUtterance(string: spokenText)
        utterance.voice = DeviceVoicePreferences.selectedVoice()
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        activeUtterance = utterance
        speakingMessageID = messageID
        synthesizer.speak(utterance)
        return true
    }

    func stopSpeaking() {
        activeUtterance = nil
        speakingMessageID = nil
        if synthesizer.isSpeaking || synthesizer.isPaused {
            synthesizer.stopSpeaking(at: .immediate)
        }
        deactivateAudioSession()
    }

    func stopAll() {
        endVoiceMode()
        cancelDictation()
        stopSpeaking()
    }

    // MARK: - Voice Mode

    /// Starts the hands-free conversation loop. Capture begins only here —
    /// never as a side effect of opening Chat or of a previous session.
    func startVoiceMode(locale: Locale = .current) async {
        guard voiceModePhase == .inactive, dictationState == .idle else { return }
        stopSpeaking()
        voiceModeLocale = locale
        voiceModeConsecutiveCaptureFailures = 0
        voiceModeBaselineReplyID = voiceModeAgentSnapshot.latestReplyID
        voiceModePhase = .starting
        startVoiceModeWatchdog()
        await voiceModeBeginCapture()
    }

    /// Ends the loop completely: playback stops, microphone capture is
    /// released, and Chat returns to ordinary typed/dictated use. The
    /// conversation transcript is untouched.
    func endVoiceMode() {
        guard voiceModePhase != .inactive else { return }
        voiceModePhase = .inactive
        voiceModeWatchdog?.cancel()
        voiceModeWatchdog = nil
        cancelDictation()
        stopSpeaking()
    }

    /// Mute drops the current utterance without submitting anything; unmute
    /// starts a fresh capture.
    func voiceModeToggleMute() {
        switch voiceModePhase {
        case .starting, .listening, .finalizing:
            voiceModePhase = .muted
            cancelDictation()
        case .muted:
            voiceModeResumeListening()
        case .inactive, .waitingForAgent, .speaking:
            break
        }
    }

    /// Stops reading the current reply aloud and returns to listening. The
    /// reply itself stays in the chat transcript.
    func voiceModeSkipSpeaking() {
        guard voiceModePhase == .speaking else { return }
        stopSpeaking()
        voiceModeResumeListening()
    }

    /// Chat pushes a bounded snapshot of the agent's turn state whenever it
    /// changes; the reply loop reacts through pure policy.
    func voiceModeAgentUpdate(_ snapshot: VoiceModeAgentSnapshot) {
        voiceModeAgentSnapshot = snapshot
        guard voiceModeActive else { return }
        if voiceModePhase == .waitingForAgent, snapshot.busy {
            voiceModeSawAgentBusy = true
        }
        switch VoiceModeAgentPolicy.reaction(
            phase: voiceModePhase,
            snapshot: snapshot,
            baselineReplyID: voiceModeBaselineReplyID,
            sawAgentBusy: voiceModeSawAgentBusy
        ) {
        case .wait:
            break
        case .resumeListening:
            voiceModeResumeListening()
        case .speak(let messageID, let text):
            voiceModeSpeakReply(messageID: messageID, text: text)
        }
    }

    private func voiceModeBeginCapture() async {
        guard voiceModePhase == .starting else { return }
        await startDictation(locale: voiceModeLocale)
        // Mute or End may have won while permissions/audio were spinning up;
        // whatever they left behind must not keep a live microphone.
        guard voiceModePhase == .starting else {
            cancelDictation()
            return
        }
        if dictationState == .listening {
            voiceModePhase = .listening
            let now = Date()
            voiceModeListeningStartedAt = now
            voiceModeLastTranscriptChangeAt = now
            voiceModeLastSeenTranscript = ""
        } else {
            // startDictation surfaced the concrete issue (permission,
            // recognizer, or audio input); Voice Mode ends with that copy.
            endVoiceMode()
        }
    }

    private func voiceModeResumeListening() {
        guard voiceModeActive else { return }
        voiceModePhase = .starting
        Task { @MainActor [weak self] in
            await self?.voiceModeBeginCapture()
        }
    }

    private func startVoiceModeWatchdog() {
        voiceModeWatchdog?.cancel()
        voiceModeWatchdog = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(250))
                guard !Task.isCancelled else { return }
                self?.voiceModeWatchdogTick()
            }
        }
    }

    private func voiceModeWatchdogTick() {
        switch voiceModePhase {
        case .listening:
            let now = Date()
            if transcript != voiceModeLastSeenTranscript {
                voiceModeLastSeenTranscript = transcript
                voiceModeLastTranscriptChangeAt = now
            }
            switch voiceModeListenPolicy.assess(
                transcriptIsEmpty: transcript
                    .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                secondsSinceLastTranscriptChange: now
                    .timeIntervalSince(voiceModeLastTranscriptChangeAt),
                secondsSinceListeningStarted: now
                    .timeIntervalSince(voiceModeListeningStartedAt)
            ) {
            case .keepListening:
                break
            case .finalize:
                voiceModePhase = .finalizing
                finishDictation()
            case .refreshRecognition:
                voiceModePhase = .starting
                cancelDictation()
                Task { @MainActor [weak self] in
                    await self?.voiceModeBeginCapture()
                }
            }
        case .waitingForAgent:
            // Before the agent is seen busy, a silent shell resumes quickly;
            // after, the generous absolute ceiling still fires so a hung turn
            // or a dropped final `busy = false` can never trap the session
            // with the microphone off.
            if voiceModeListenPolicy.shouldResumeFromWaiting(
                sawAgentBusy: voiceModeSawAgentBusy,
                secondsWaiting: Date().timeIntervalSince(voiceModeWaitingStartedAt)
            ) {
                voiceModeResumeListening()
            }
        case .speaking:
            // The reply is spoken as one utterance; normally `completeSpeech`
            // resumes listening. If that delegate callback is dropped (an audio
            // glitch that raised no interruption/route/reset notification), the
            // synthesizer goes idle with the phase stuck on `speaking`. Recover
            // so the microphone is never stranded. The reply stays in chat.
            if voiceModeListenPolicy.shouldRecoverFromSpeaking(
                synthesizerIdle: !synthesizer.isSpeaking && !synthesizer.isPaused,
                secondsSpeaking: Date().timeIntervalSince(voiceModeSpeakingStartedAt),
                speakingTimeout: voiceModeSpeakingTimeout
            ) {
                voiceModeResumeListening()
            }
        case .inactive, .starting, .muted, .finalizing:
            break
        }
    }

    /// Funnel for every way a capture run can end while Voice Mode is active.
    private func voiceModeCaptureEnded(failed: Bool) {
        guard voiceModeActive else { return }
        if failed { voiceModeConsecutiveCaptureFailures += 1 }
        switch VoiceModeCapturePolicy.outcome(
            phase: voiceModePhase,
            finalTranscript: transcript,
            failed: failed,
            consecutiveFailures: voiceModeConsecutiveCaptureFailures
        ) {
        case .ignore:
            break
        case .restartListening:
            voiceModeResumeListening()
        case .endWithFailure:
            endVoiceMode()
            if issue == nil { issue = .voiceModeInterrupted }
        case .submit(let text):
            voiceModeConsecutiveCaptureFailures = 0
            voiceModeSubmit(text)
        }
    }

    private func voiceModeSubmit(_ text: String) {
        voiceModePhase = .waitingForAgent
        voiceModeWaitingStartedAt = Date()
        voiceModeSawAgentBusy = false
        voiceModeBaselineReplyID = voiceModeAgentSnapshot.latestReplyID
        transcript = ""
        guard let onVoiceModeSubmit else {
            voiceModeResumeListening()
            return
        }
        Task { @MainActor [weak self] in
            let accepted = await onVoiceModeSubmit(text)
            guard let self, self.voiceModePhase == .waitingForAgent else { return }
            if !accepted { self.voiceModeResumeListening() }
        }
    }

    private func voiceModeSpeakReply(messageID: UUID, text: String) {
        voiceModeBaselineReplyID = messageID
        let spokenText = DeviceVoiceText.spokenText(from: text)
        guard !spokenText.isEmpty else {
            voiceModeResumeListening()
            return
        }
        voiceModeSpeakingStartedAt = Date()
        voiceModeSpeakingTimeout = voiceModeListenPolicy.speakingTimeout(
            spokenCharacterCount: spokenText.count
        )
        voiceModePhase = .speaking
        if !beginSpeaking(messageID: messageID, spokenText: spokenText) {
            // Playback failed; the reply is still readable in chat. Keep the
            // conversation going instead of ending on a speaker problem.
            voiceModeResumeListening()
        }
    }

    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didFinish utterance: AVSpeechUtterance
    ) {
        let utteranceID = ObjectIdentifier(utterance)
        Task { @MainActor [weak self] in
            self?.completeSpeech(for: utteranceID)
        }
    }

    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didCancel utterance: AVSpeechUtterance
    ) {
        let utteranceID = ObjectIdentifier(utterance)
        Task { @MainActor [weak self] in
            self?.completeSpeech(for: utteranceID)
        }
    }

    private func completeSpeech(for utteranceID: ObjectIdentifier) {
        guard let activeUtterance,
              ObjectIdentifier(activeUtterance) == utteranceID else { return }
        self.activeUtterance = nil
        speakingMessageID = nil
        deactivateAudioSession()
        if voiceModePhase == .speaking {
            voiceModeResumeListening()
        }
    }

    private func finishDictation() {
        guard dictationState == .listening else { return }
        dictationState = .finalizing
        stopAudioInput()
        recognitionRequest?.endAudio()

        let runID = dictationRunID
        finalizationTask?.cancel()
        finalizationTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            guard let self, self.dictationRunID == runID else { return }
            self.completeDictation(runID: runID, cancelRecognition: true)
            // Apple Speech never returned the final phrase; the partial
            // transcript is what the user said.
            self.voiceModeCaptureEnded(failed: false)
        }
    }

    private func cancelDictation() {
        tearDownDictation(invalidateRun: true, cancelRecognition: true)
    }

    private func completeDictation(runID: UUID, cancelRecognition: Bool) {
        guard dictationRunID == runID else { return }
        tearDownDictation(invalidateRun: true, cancelRecognition: cancelRecognition)
    }

    private func stopAudioInput() {
        if audioEngine.isRunning { audioEngine.stop() }
        if inputTapInstalled {
            audioEngine.inputNode.removeTap(onBus: 0)
            inputTapInstalled = false
        }
    }

    private func tearDownDictation(invalidateRun: Bool, cancelRecognition: Bool) {
        if invalidateRun { dictationRunID = UUID() }
        finalizationTask?.cancel()
        finalizationTask = nil
        stopAudioInput()
        recognitionRequest?.endAudio()
        if cancelRecognition { recognitionTask?.cancel() }
        recognitionRequest = nil
        recognitionTask = nil
        dictationState = .idle
        deactivateAudioSession()
    }

    @objc nonisolated private func audioSessionInterrupted(_ notification: Notification) {
        guard let value = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? NSNumber,
              AVAudioSession.InterruptionType(rawValue: value.uintValue) == .began else { return }
        Task { @MainActor [weak self] in self?.handleAudioInterruption() }
    }

    @objc nonisolated private func audioRouteChanged(_ notification: Notification) {
        guard let value = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? NSNumber,
              let reason = AVAudioSession.RouteChangeReason(rawValue: value.uintValue),
              DeviceVoiceRouteChangePolicy.invalidatesCurrentRoute(reason) else { return }
        Task { @MainActor [weak self] in self?.handleAudioRouteInvalidation() }
    }

    @objc nonisolated private func audioEngineConfigurationChanged(_ notification: Notification) {
        Task { @MainActor [weak self] in self?.handleAudioInputInvalidation() }
    }

    @objc nonisolated private func audioMediaServicesReset(_ notification: Notification) {
        Task { @MainActor [weak self] in self?.handleMediaServicesReset() }
    }

    private func handleAudioInterruption() {
        if voiceModeActive {
            endVoiceMode()
            issue = .voiceModeInterrupted
            return
        }
        let wasDictating = dictationState.isActive
        let wasSpeaking = isSpeaking
        if wasDictating { cancelDictation() }
        if wasSpeaking { stopSpeaking() }
        if wasDictating {
            issue = .recognitionFailed
        } else if wasSpeaking {
            issue = .playbackFailed
        }
    }

    private func handleAudioInputInvalidation() {
        guard dictationState == .listening else { return }
        if voiceModeActive {
            endVoiceMode()
            issue = .voiceModeInterrupted
            return
        }
        cancelDictation()
        issue = .audioInputUnavailable
    }

    private func handleAudioRouteInvalidation() {
        if voiceModeActive {
            // The route the session started on is gone (headset unplugged,
            // Bluetooth dropped). End completely rather than continuing to
            // capture or speak on a route the user never chose.
            endVoiceMode()
            issue = .voiceModeInterrupted
            return
        }
        if isSpeaking { stopSpeaking() }
        handleAudioInputInvalidation()
    }

    private func handleMediaServicesReset() {
        if voiceModeActive {
            endVoiceMode()
            issue = .voiceModeInterrupted
            return
        }
        let wasDictating = dictationState.isActive
        let wasSpeaking = isSpeaking
        stopAll()
        if wasDictating {
            issue = .audioInputUnavailable
        } else if wasSpeaking {
            issue = .playbackFailed
        }
    }

    private func speechAuthorizationStatus() async -> SFSpeechRecognizerAuthorizationStatus {
        let current = SFSpeechRecognizer.authorizationStatus()
        guard current == .notDetermined else { return current }
        return await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
    }

    private func requestMicrophoneAuthorization() async -> Bool {
        switch AVAudioApplication.shared.recordPermission {
        case .granted:
            return true
        case .denied:
            return false
        case .undetermined:
            return await withCheckedContinuation { continuation in
                AVAudioApplication.requestRecordPermission { granted in
                    continuation.resume(returning: granted)
                }
            }
        @unknown default:
            return false
        }
    }

    private func deactivateAudioSession() {
        try? AVAudioSession.sharedInstance().setActive(
            false,
            options: .notifyOthersOnDeactivation
        )
    }
}
