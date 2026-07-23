import Foundation

/// Voice Mode turns Chat into a hands-free conversation loop:
/// listen → transcribe → send → agent works → speak the reply → listen again.
///
/// Everything in this file is pure policy so the loop's decisions are
/// unit-testable without audio hardware. `DeviceVoiceController` owns the
/// microphone, Apple Speech, and playback; Chat owns prompt submission and the
/// transcript. Voice Mode never records before the user starts it, never
/// leaves the on-device Apple Speech path, and never answers an approval — the
/// existing explicit approval UI remains the only way to consent.
enum VoiceModePhase: String, Equatable {
    /// Voice Mode is off; dictation and read-aloud behave exactly as before.
    case inactive
    /// The user started Voice Mode and permissions/audio are spinning up.
    case starting
    /// The microphone is live and partial transcripts are accumulating.
    case listening
    /// The user muted the microphone; the session stays open.
    case muted
    /// Speech paused long enough to treat the utterance as complete; waiting
    /// for Apple Speech to return the final phrase.
    case finalizing
    /// The transcript was submitted as a prompt; the agent owns the turn.
    case waitingForAgent
    /// The completed reply is being read aloud.
    case speaking

    var isActive: Bool { self != .inactive }

    /// While capturing or finalizing an utterance, the composer draft and
    /// manual dictation stay out of the way.
    var ownsMicrophone: Bool {
        self == .starting || self == .listening || self == .finalizing
    }
}

/// End-of-utterance and session-upkeep decisions while the microphone is live.
struct VoiceModeListenPolicy: Equatable {
    /// Silence after the last transcript change that completes an utterance.
    var silenceWindow: TimeInterval
    /// Hard bound on a single utterance so one turn cannot capture unbounded
    /// audio.
    var maximumUtterance: TimeInterval
    /// With no speech at all, restart recognition before Apple's service
    /// window can expire it mid-listen.
    var recognitionRefreshWindow: TimeInterval
    /// How long `waitingForAgent` may sit with no evidence the agent started
    /// before Voice Mode resumes listening instead of waiting forever.
    var agentStartTimeout: TimeInterval
    /// Absolute ceiling on `waitingForAgent`, applied even after the agent was
    /// seen busy. A hung turn or a dropped final `busy = false` update must not
    /// strand the session with the microphone off and no way back but a manual
    /// End. Generous so it never cuts a legitimately long turn.
    var agentReplyTimeout: TimeInterval
    /// Minimum time in `speaking` before an idle synthesizer is treated as a
    /// finished/dropped utterance rather than one that has not started yet.
    var speakingStuckGrace: TimeInterval
    /// Per-character speaking-time estimate used to bound `speaking` when the
    /// synthesizer reports it is still speaking but never fires its completion
    /// callback. Deliberately slow so real speech is never cut short.
    var speakingSecondsPerCharacter: TimeInterval
    /// Fixed slack added to the estimated speaking time before the ceiling
    /// applies.
    var speakingTimeoutMargin: TimeInterval

    static let standard = VoiceModeListenPolicy(
        silenceWindow: 1.6,
        maximumUtterance: 90,
        recognitionRefreshWindow: 45,
        agentStartTimeout: 15,
        agentReplyTimeout: 240,
        speakingStuckGrace: 1.5,
        speakingSecondsPerCharacter: 0.12,
        speakingTimeoutMargin: 20
    )

    enum Assessment: Equatable {
        case keepListening
        case finalize
        case refreshRecognition
    }

    func assess(
        transcriptIsEmpty: Bool,
        secondsSinceLastTranscriptChange: TimeInterval,
        secondsSinceListeningStarted: TimeInterval
    ) -> Assessment {
        if !transcriptIsEmpty {
            if secondsSinceLastTranscriptChange >= silenceWindow { return .finalize }
            if secondsSinceListeningStarted >= maximumUtterance { return .finalize }
            return .keepListening
        }
        if secondsSinceListeningStarted >= recognitionRefreshWindow {
            return .refreshRecognition
        }
        return .keepListening
    }

    /// Whether the loop should stop waiting for a submitted prompt and resume
    /// listening. Before the agent is seen busy, the short start timeout
    /// applies; after, only the generous absolute ceiling can fire, so a
    /// stalled turn can never trap the session forever.
    func shouldResumeFromWaiting(
        sawAgentBusy: Bool,
        secondsWaiting: TimeInterval
    ) -> Bool {
        if !sawAgentBusy, secondsWaiting >= agentStartTimeout { return true }
        return secondsWaiting >= agentReplyTimeout
    }

    /// A generous upper bound on how long a reply of this length should take to
    /// speak; used only as a backstop against a synthesizer that never reports
    /// completion.
    func speakingTimeout(spokenCharacterCount: Int) -> TimeInterval {
        Double(max(0, spokenCharacterCount)) * speakingSecondsPerCharacter
            + speakingTimeoutMargin
    }

    /// Whether the loop should leave the `speaking` phase and resume listening.
    /// It recovers as soon as the synthesizer is idle past the startup grace
    /// (the normal completion path with a dropped callback), and unconditionally
    /// once the length-based ceiling passes (a synthesizer wedged reporting it
    /// is still speaking).
    func shouldRecoverFromSpeaking(
        synthesizerIdle: Bool,
        secondsSpeaking: TimeInterval,
        speakingTimeout: TimeInterval
    ) -> Bool {
        if secondsSpeaking >= speakingStuckGrace, synthesizerIdle { return true }
        return secondsSpeaking >= speakingTimeout
    }
}

/// What Voice Mode does when a capture run ends, for any reason.
enum VoiceModeCaptureOutcome: Equatable {
    case submit(String)
    case restartListening
    case endWithFailure
    case ignore
}

enum VoiceModeCapturePolicy {
    /// Consecutive capture failures Voice Mode absorbs by restarting before it
    /// ends the session with the visible issue instead of looping silently.
    static let failureLimit = 3

    static func outcome(
        phase: VoiceModePhase,
        finalTranscript: String,
        failed: Bool,
        consecutiveFailures: Int
    ) -> VoiceModeCaptureOutcome {
        guard phase == .listening || phase == .finalizing else { return .ignore }
        if failed {
            return consecutiveFailures < failureLimit ? .restartListening : .endWithFailure
        }
        let trimmed = finalTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? .restartListening : .submit(trimmed)
    }
}

/// A bounded projection of the chat surface the reply loop reacts to. It
/// carries presentation text only — never raw tool output or approvals.
struct VoiceModeAgentSnapshot: Equatable {
    var busy: Bool
    var awaitingInteraction: Bool
    var latestReplyID: UUID?
    var latestReplyText: String

    static let idle = VoiceModeAgentSnapshot(
        busy: false,
        awaitingInteraction: false,
        latestReplyID: nil,
        latestReplyText: ""
    )
}

enum VoiceModeAgentReaction: Equatable {
    case wait
    case speak(UUID, String)
    case resumeListening
}

enum VoiceModeAgentPolicy {
    /// Decides the next step while a submitted prompt is outstanding.
    ///
    /// - `baselineReplyID` is the newest completed assistant message at submit
    ///   time, so history is never re-spoken.
    /// - `sawAgentBusy` distinguishes "the agent finished" from "the agent has
    ///   not started yet" when `busy` is false in both cases.
    /// - A pending approval or question always waits: consent stays with the
    ///   explicit interaction UI, never with a spoken reply loop.
    static func reaction(
        phase: VoiceModePhase,
        snapshot: VoiceModeAgentSnapshot,
        baselineReplyID: UUID?,
        sawAgentBusy: Bool
    ) -> VoiceModeAgentReaction {
        guard phase == .waitingForAgent else { return .wait }
        if snapshot.awaitingInteraction { return .wait }
        if snapshot.busy { return .wait }
        if let replyID = snapshot.latestReplyID, replyID != baselineReplyID {
            return .speak(replyID, snapshot.latestReplyText)
        }
        return sawAgentBusy ? .resumeListening : .wait
    }
}

/// When the Voice Mode entry control is offered at all.
enum VoiceModeAvailability {
    static func canStart(
        sessionReady: Bool,
        busy: Bool,
        hasUnknownSendOutcome: Bool,
        dictationState: DeviceDictationState
    ) -> Bool {
        sessionReady && !busy && !hasUnknownSendOutcome && dictationState == .idle
    }
}

/// Factual, screen-reader-first status copy for the in-conversation shell.
/// States name what is actually happening; there is no decorative "active"
/// state that implies work without evidence.
enum VoiceModeStatusPresentation {
    static func label(phase: VoiceModePhase, awaitingInteraction: Bool) -> String {
        switch phase {
        case .inactive: return ""
        case .starting: return "Starting voice…"
        case .listening: return "Listening"
        case .muted: return "Muted"
        case .finalizing: return "Finishing what you said…"
        case .waitingForAgent:
            return awaitingInteraction ? "Awaiting your approval in chat" : "Working…"
        case .speaking: return "Speaking"
        }
    }

    static func accessibilityAnnouncement(
        phase: VoiceModePhase,
        awaitingInteraction: Bool
    ) -> String? {
        switch phase {
        case .inactive: return "Voice Mode ended"
        case .starting: return nil
        case .listening: return "Voice Mode listening"
        case .muted: return "Voice Mode muted"
        case .finalizing: return nil
        case .waitingForAgent:
            return awaitingInteraction
                ? "Fabric is awaiting your approval in chat"
                : "Fabric is working"
        case .speaking: return "Fabric is speaking"
        }
    }
}
