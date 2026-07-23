import SwiftUI
import UIKit

/// The compact in-conversation Voice Mode surface. It sits above the composer
/// while the loop runs; the chat thread stays the transcript and source of
/// truth. Status copy is factual (`Listening`, `Working…`, `Speaking`) — never
/// a decorative animation that implies work without evidence — and every
/// control is an explicit button, so the loop is always interruptible.
struct VoiceModeShell: View {
    let phase: VoiceModePhase
    let awaitingInteraction: Bool
    let caption: String
    let onToggleMute: () -> Void
    let onSkipSpeaking: () -> Void
    let onEnd: () -> Void

    private var statusLabel: String {
        VoiceModeStatusPresentation.label(
            phase: phase,
            awaitingInteraction: awaitingInteraction
        )
    }

    private var showsMuteControl: Bool {
        switch phase {
        case .starting, .listening, .finalizing, .muted: return true
        case .inactive, .waitingForAgent, .speaking: return false
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 12) {
                Image(systemName: phase == .muted ? "mic.slash.fill" : "waveform")
                    .foregroundStyle(
                        phase == .listening ? FabricTheme.threadActive : FabricTheme.textMuted
                    )
                    .accessibilityHidden(true)
                Text(statusLabel)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(FabricTheme.text)
                    .accessibilityAddTraits(.updatesFrequently)
                Spacer(minLength: 8)
                if showsMuteControl {
                    Button(phase == .muted ? "Unmute" : "Mute", action: onToggleMute)
                        .buttonStyle(.bordered)
                        .frame(minHeight: FabricTheme.minTarget)
                        .accessibilityHint(
                            phase == .muted
                                ? "Resumes listening"
                                : "Stops listening without ending Voice Mode"
                        )
                        .accessibilityIdentifier("voice-mode-mute")
                }
                if phase == .speaking {
                    Button("Skip", action: onSkipSpeaking)
                        .buttonStyle(.bordered)
                        .frame(minHeight: FabricTheme.minTarget)
                        .accessibilityLabel("Skip speaking")
                        .accessibilityHint("Stops reading this reply aloud and listens again")
                        .accessibilityIdentifier("voice-mode-skip")
                }
                Button("End", role: .destructive, action: onEnd)
                    .buttonStyle(.bordered)
                    .frame(minHeight: FabricTheme.minTarget)
                    .accessibilityLabel("End Voice Mode")
                    .accessibilityIdentifier("voice-mode-end")
            }
            if !caption.isEmpty {
                // The live partial transcript: captions stay visible even
                // though the final text also lands in the chat thread.
                Text(caption)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .lineLimit(3)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityLabel("Heard so far: \(caption)")
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(FabricTheme.surfaceInset)
        .overlay(alignment: .top) { Divider() }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Voice Mode: \(statusLabel)")
        .accessibilityIdentifier("voice-mode-shell")
        .onChange(of: phase) { _, newPhase in
            guard UIAccessibility.isVoiceOverRunning,
                  let announcement = VoiceModeStatusPresentation.accessibilityAnnouncement(
                      phase: newPhase,
                      awaitingInteraction: awaitingInteraction
                  ) else { return }
            UIAccessibility.post(notification: .announcement, argument: announcement)
        }
    }
}
