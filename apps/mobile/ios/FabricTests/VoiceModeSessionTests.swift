import XCTest
@testable import Fabric

final class VoiceModeSessionTests: XCTestCase {
    // MARK: - Listening / end-of-utterance policy

    func testSilenceAfterSpeechFinalizesTheUtterance() {
        let policy = VoiceModeListenPolicy.standard

        XCTAssertEqual(
            policy.assess(
                transcriptIsEmpty: false,
                secondsSinceLastTranscriptChange: policy.silenceWindow,
                secondsSinceListeningStarted: 5
            ),
            .finalize
        )
        XCTAssertEqual(
            policy.assess(
                transcriptIsEmpty: false,
                secondsSinceLastTranscriptChange: policy.silenceWindow / 2,
                secondsSinceListeningStarted: 5
            ),
            .keepListening
        )
    }

    func testUtteranceDurationIsBoundedEvenWhileSpeechContinues() {
        let policy = VoiceModeListenPolicy.standard

        XCTAssertEqual(
            policy.assess(
                transcriptIsEmpty: false,
                secondsSinceLastTranscriptChange: 0.1,
                secondsSinceListeningStarted: policy.maximumUtterance
            ),
            .finalize
        )
    }

    func testSilentListeningRefreshesRecognitionInsteadOfSubmitting() {
        let policy = VoiceModeListenPolicy.standard

        XCTAssertEqual(
            policy.assess(
                transcriptIsEmpty: true,
                secondsSinceLastTranscriptChange: policy.recognitionRefreshWindow + 1,
                secondsSinceListeningStarted: policy.recognitionRefreshWindow + 1
            ),
            .refreshRecognition
        )
        XCTAssertEqual(
            policy.assess(
                transcriptIsEmpty: true,
                secondsSinceLastTranscriptChange: 5,
                secondsSinceListeningStarted: 5
            ),
            .keepListening
        )
    }

    func testListenPolicyBoundsRelateSensibly() {
        let policy = VoiceModeListenPolicy.standard

        // The silence window must complete an utterance long before the
        // recognition refresh or the hard utterance bound can race it.
        XCTAssertLessThan(policy.silenceWindow, policy.recognitionRefreshWindow)
        XCTAssertLessThan(policy.silenceWindow, policy.maximumUtterance)
        XCTAssertGreaterThan(policy.agentStartTimeout, 0)
        // The absolute reply ceiling must be a genuine backstop, not a second
        // short timeout that would cut legitimately long turns.
        XCTAssertGreaterThan(policy.agentReplyTimeout, policy.agentStartTimeout)
        XCTAssertGreaterThan(policy.speakingStuckGrace, 0)
        XCTAssertGreaterThan(policy.speakingSecondsPerCharacter, 0)
        XCTAssertGreaterThan(policy.speakingTimeoutMargin, 0)
    }

    // MARK: - Waiting-for-agent backstop

    func testSilentShellResumesQuicklyBeforeTheAgentIsSeenBusy() {
        let policy = VoiceModeListenPolicy.standard

        XCTAssertTrue(
            policy.shouldResumeFromWaiting(
                sawAgentBusy: false,
                secondsWaiting: policy.agentStartTimeout
            )
        )
        XCTAssertFalse(
            policy.shouldResumeFromWaiting(
                sawAgentBusy: false,
                secondsWaiting: policy.agentStartTimeout / 2
            )
        )
    }

    func testABusyAgentIsGivenUntilTheAbsoluteCeilingButNeverForever() {
        let policy = VoiceModeListenPolicy.standard

        // A latched-busy turn is not cut at the short start timeout...
        XCTAssertFalse(
            policy.shouldResumeFromWaiting(
                sawAgentBusy: true,
                secondsWaiting: policy.agentStartTimeout + 1
            )
        )
        XCTAssertFalse(
            policy.shouldResumeFromWaiting(
                sawAgentBusy: true,
                secondsWaiting: policy.agentReplyTimeout - 1
            )
        )
        // ...but the absolute ceiling always fires, so the mic is never
        // stranded by a hung turn or a dropped final `busy = false`.
        XCTAssertTrue(
            policy.shouldResumeFromWaiting(
                sawAgentBusy: true,
                secondsWaiting: policy.agentReplyTimeout
            )
        )
    }

    // MARK: - Speaking backstop

    func testSpeakingTimeoutScalesWithLengthAndIncludesMargin() {
        let policy = VoiceModeListenPolicy.standard

        XCTAssertEqual(policy.speakingTimeout(spokenCharacterCount: 0), policy.speakingTimeoutMargin)
        XCTAssertGreaterThan(
            policy.speakingTimeout(spokenCharacterCount: 2_000),
            policy.speakingTimeout(spokenCharacterCount: 100)
        )
        // A short reply still gets more than the raw estimate: the margin
        // guarantees real speech is never cut short by the backstop.
        XCTAssertGreaterThan(policy.speakingTimeout(spokenCharacterCount: 10), policy.speakingTimeoutMargin)
    }

    func testIdleSynthesizerAfterGraceRecoversFromDroppedCompletion() {
        let policy = VoiceModeListenPolicy.standard
        let timeout = policy.speakingTimeout(spokenCharacterCount: 500)

        // Idle past the startup grace: the utterance finished (or was dropped)
        // without a delegate callback — recover.
        XCTAssertTrue(
            policy.shouldRecoverFromSpeaking(
                synthesizerIdle: true,
                secondsSpeaking: policy.speakingStuckGrace,
                speakingTimeout: timeout
            )
        )
        // Idle inside the startup grace: `speak` was just called and the
        // synthesizer has not flipped to speaking yet — do not recover.
        XCTAssertFalse(
            policy.shouldRecoverFromSpeaking(
                synthesizerIdle: true,
                secondsSpeaking: policy.speakingStuckGrace / 2,
                speakingTimeout: timeout
            )
        )
    }

    func testActiveSynthesizerIsNeverCutUntilTheLengthCeiling() {
        let policy = VoiceModeListenPolicy.standard
        let timeout = policy.speakingTimeout(spokenCharacterCount: 500)

        // Still speaking, well within the ceiling: leave it alone.
        XCTAssertFalse(
            policy.shouldRecoverFromSpeaking(
                synthesizerIdle: false,
                secondsSpeaking: timeout / 2,
                speakingTimeout: timeout
            )
        )
        // Wedged reporting "still speaking" past the ceiling: recover anyway.
        XCTAssertTrue(
            policy.shouldRecoverFromSpeaking(
                synthesizerIdle: false,
                secondsSpeaking: timeout,
                speakingTimeout: timeout
            )
        )
    }

    // MARK: - Capture-ended policy

    func testFinalTranscriptIsSubmittedTrimmed() {
        XCTAssertEqual(
            VoiceModeCapturePolicy.outcome(
                phase: .finalizing,
                finalTranscript: "  send the release notes  ",
                failed: false,
                consecutiveFailures: 0
            ),
            .submit("send the release notes")
        )
    }

    func testRecognizerInitiatedFinalWhileListeningStillSubmits() {
        XCTAssertEqual(
            VoiceModeCapturePolicy.outcome(
                phase: .listening,
                finalTranscript: "what changed today",
                failed: false,
                consecutiveFailures: 0
            ),
            .submit("what changed today")
        )
    }

    func testEmptyCaptureRestartsListeningWithoutSubmitting() {
        XCTAssertEqual(
            VoiceModeCapturePolicy.outcome(
                phase: .finalizing,
                finalTranscript: "   ",
                failed: false,
                consecutiveFailures: 0
            ),
            .restartListening
        )
    }

    func testCaptureFailuresRestartWithinBudgetThenEndVisibly() {
        XCTAssertEqual(
            VoiceModeCapturePolicy.outcome(
                phase: .listening,
                finalTranscript: "",
                failed: true,
                consecutiveFailures: VoiceModeCapturePolicy.failureLimit - 1
            ),
            .restartListening
        )
        XCTAssertEqual(
            VoiceModeCapturePolicy.outcome(
                phase: .listening,
                finalTranscript: "",
                failed: true,
                consecutiveFailures: VoiceModeCapturePolicy.failureLimit
            ),
            .endWithFailure
        )
    }

    func testCaptureEndIsIgnoredOutsideAnActiveCapturePhase() {
        for phase: VoiceModePhase in [.inactive, .muted, .waitingForAgent, .speaking] {
            XCTAssertEqual(
                VoiceModeCapturePolicy.outcome(
                    phase: phase,
                    finalTranscript: "left over words",
                    failed: false,
                    consecutiveFailures: 0
                ),
                .ignore,
                "phase \(phase) must not submit or restart"
            )
        }
    }

    // MARK: - Reply loop policy

    private func snapshot(
        busy: Bool = false,
        awaitingInteraction: Bool = false,
        replyID: UUID? = nil,
        replyText: String = ""
    ) -> VoiceModeAgentSnapshot {
        VoiceModeAgentSnapshot(
            busy: busy,
            awaitingInteraction: awaitingInteraction,
            latestReplyID: replyID,
            latestReplyText: replyText
        )
    }

    func testNewCompletedReplyIsSpokenExactlyWhenTheTurnEnds() {
        let baseline = UUID()
        let reply = UUID()

        XCTAssertEqual(
            VoiceModeAgentPolicy.reaction(
                phase: .waitingForAgent,
                snapshot: snapshot(busy: false, replyID: reply, replyText: "Done."),
                baselineReplyID: baseline,
                sawAgentBusy: true
            ),
            .speak(reply, "Done.")
        )
        // While the agent is still busy the reply may not be the turn's last
        // word; keep waiting.
        XCTAssertEqual(
            VoiceModeAgentPolicy.reaction(
                phase: .waitingForAgent,
                snapshot: snapshot(busy: true, replyID: reply, replyText: "Done."),
                baselineReplyID: baseline,
                sawAgentBusy: true
            ),
            .wait
        )
    }

    func testHistoryIsNeverReSpoken() {
        let baseline = UUID()

        XCTAssertEqual(
            VoiceModeAgentPolicy.reaction(
                phase: .waitingForAgent,
                snapshot: snapshot(busy: false, replyID: baseline, replyText: "Old reply"),
                baselineReplyID: baseline,
                sawAgentBusy: true
            ),
            .resumeListening
        )
    }

    func testPendingApprovalAlwaysWaitsForTheExplicitInteractionUI() {
        let reply = UUID()

        XCTAssertEqual(
            VoiceModeAgentPolicy.reaction(
                phase: .waitingForAgent,
                snapshot: snapshot(
                    busy: false,
                    awaitingInteraction: true,
                    replyID: reply,
                    replyText: "May I run this?"
                ),
                baselineReplyID: nil,
                sawAgentBusy: true
            ),
            .wait
        )
    }

    func testQuietBusyFlagWaitsUntilTheAgentActuallyStarted() {
        // busy == false before the agent ever ran must not be read as "the
        // agent finished"; without a new reply the loop keeps waiting.
        XCTAssertEqual(
            VoiceModeAgentPolicy.reaction(
                phase: .waitingForAgent,
                snapshot: snapshot(busy: false),
                baselineReplyID: nil,
                sawAgentBusy: false
            ),
            .wait
        )
        XCTAssertEqual(
            VoiceModeAgentPolicy.reaction(
                phase: .waitingForAgent,
                snapshot: snapshot(busy: false),
                baselineReplyID: nil,
                sawAgentBusy: true
            ),
            .resumeListening
        )
    }

    func testFastReplyBeforeBusyEverFlippedStillSpeaks() {
        let reply = UUID()

        XCTAssertEqual(
            VoiceModeAgentPolicy.reaction(
                phase: .waitingForAgent,
                snapshot: snapshot(busy: false, replyID: reply, replyText: "Quick answer"),
                baselineReplyID: nil,
                sawAgentBusy: false
            ),
            .speak(reply, "Quick answer")
        )
    }

    func testReplyPolicyIsInertOutsideTheWaitingPhase() {
        let reply = UUID()
        for phase: VoiceModePhase in [.inactive, .starting, .listening, .muted, .finalizing, .speaking] {
            XCTAssertEqual(
                VoiceModeAgentPolicy.reaction(
                    phase: phase,
                    snapshot: snapshot(busy: false, replyID: reply, replyText: "text"),
                    baselineReplyID: nil,
                    sawAgentBusy: true
                ),
                .wait,
                "phase \(phase) must not react to transcript changes"
            )
        }
    }

    // MARK: - Availability and presentation

    func testVoiceModeStartRequiresAnIdleReadySession() {
        XCTAssertTrue(
            VoiceModeAvailability.canStart(
                sessionReady: true,
                busy: false,
                hasUnknownSendOutcome: false,
                dictationState: .idle
            )
        )
        XCTAssertFalse(
            VoiceModeAvailability.canStart(
                sessionReady: false,
                busy: false,
                hasUnknownSendOutcome: false,
                dictationState: .idle
            )
        )
        XCTAssertFalse(
            VoiceModeAvailability.canStart(
                sessionReady: true,
                busy: true,
                hasUnknownSendOutcome: false,
                dictationState: .idle
            )
        )
        XCTAssertFalse(
            VoiceModeAvailability.canStart(
                sessionReady: true,
                busy: false,
                hasUnknownSendOutcome: true,
                dictationState: .idle
            )
        )
        XCTAssertFalse(
            VoiceModeAvailability.canStart(
                sessionReady: true,
                busy: false,
                hasUnknownSendOutcome: false,
                dictationState: .listening
            )
        )
    }

    func testMicrophoneOwnershipTracksCapturePhasesOnly() {
        XCTAssertTrue(VoiceModePhase.starting.ownsMicrophone)
        XCTAssertTrue(VoiceModePhase.listening.ownsMicrophone)
        XCTAssertTrue(VoiceModePhase.finalizing.ownsMicrophone)
        XCTAssertFalse(VoiceModePhase.muted.ownsMicrophone)
        XCTAssertFalse(VoiceModePhase.waitingForAgent.ownsMicrophone)
        XCTAssertFalse(VoiceModePhase.speaking.ownsMicrophone)
        XCTAssertFalse(VoiceModePhase.inactive.ownsMicrophone)
        XCTAssertFalse(VoiceModePhase.inactive.isActive)
        XCTAssertTrue(VoiceModePhase.muted.isActive)
    }

    func testEveryActivePhaseHasFactualStatusCopy() {
        let activePhases: [VoiceModePhase] = [
            .starting, .listening, .muted, .finalizing, .waitingForAgent, .speaking,
        ]
        for phase in activePhases {
            XCTAssertFalse(
                VoiceModeStatusPresentation.label(phase: phase, awaitingInteraction: false).isEmpty,
                "phase \(phase) needs a visible status"
            )
        }
        XCTAssertTrue(
            VoiceModeStatusPresentation.label(phase: .inactive, awaitingInteraction: false).isEmpty
        )
    }

    func testAwaitingApprovalIsNamedInsteadOfPretendingToWork() {
        let working = VoiceModeStatusPresentation.label(
            phase: .waitingForAgent,
            awaitingInteraction: false
        )
        let awaiting = VoiceModeStatusPresentation.label(
            phase: .waitingForAgent,
            awaitingInteraction: true
        )

        XCTAssertNotEqual(working, awaiting)
        XCTAssertTrue(awaiting.localizedCaseInsensitiveContains("approval"))
    }

    func testVoiceModeInterruptionIssueOffersNoSettingsDetour() {
        XCTAssertFalse(DeviceVoiceIssue.voiceModeInterrupted.canOpenSettings)
        XCTAssertFalse(DeviceVoiceIssue.voiceModeInterrupted.title.isEmpty)
        XCTAssertFalse(DeviceVoiceIssue.voiceModeInterrupted.message.isEmpty)
    }
}
