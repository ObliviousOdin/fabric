import AVFoundation
import SwiftUI

/// Record → stop → hand off. The recording is AAC mono, capped at two
/// minutes, and leaves the wrist as one `transferFile` (store-and-forward);
/// transcription and submission stay on the phone, which owns Apple Speech
/// and the gated gateway path.
struct WatchVoiceNoteView: View {
    @Environment(WatchAppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    @State private var recorder = WatchVoiceRecorder()
    @State private var isRecording = false
    @State private var permissionDenied = false
    @State private var startedAt: Date?

    var body: some View {
        VStack(spacing: 12) {
            if permissionDenied {
                Text("Allow microphone access for Fabric in Settings to record voice notes.")
                    .font(.footnote)
                    .multilineTextAlignment(.center)
            } else {
                Image(systemName: isRecording ? "waveform" : "mic.fill")
                    .font(.system(size: 34))
                    .foregroundStyle(isRecording ? Color.red : Color.accentColor)
                    .symbolEffect(.pulse, isActive: isRecording)

                if isRecording, let startedAt {
                    Text(startedAt, style: .timer)
                        .font(.title3.monospacedDigit())
                }

                Button {
                    isRecording ? finishRecording() : startRecording()
                } label: {
                    Text(isRecording ? "Stop & send" : "Record")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(isRecording ? .red : nil)
            }
        }
        .navigationTitle("Voice note")
        .onDisappear {
            // Leaving the screen discards an in-progress recording; only an
            // explicit stop hands audio to the phone.
            recorder.cancel()
        }
    }

    private func startRecording() {
        recorder.requestPermissionAndStart { granted in
            if granted {
                isRecording = true
                startedAt = Date()
            } else {
                permissionDenied = true
            }
        }
    }

    private func finishRecording() {
        isRecording = false
        guard let result = recorder.stop() else { return }
        model.sendVoiceNote(fileURL: result.fileURL, durationMs: result.durationMs)
        dismiss()
    }
}

/// Thin AVAudioRecorder wrapper. No delegate dance: the view drives start and
/// stop explicitly, and the two-minute cap is enforced by the recorder
/// itself (`record(forDuration:)`).
final class WatchVoiceRecorder {
    struct Result {
        let fileURL: URL
        let durationMs: Int
    }

    static let maximumDurationSeconds: TimeInterval = 120

    private var recorder: AVAudioRecorder?
    private var fileURL: URL?

    func requestPermissionAndStart(completion: @escaping (Bool) -> Void) {
        let audioSession = AVAudioSession.sharedInstance()
        audioSession.requestRecordPermission { granted in
            DispatchQueue.main.async {
                guard granted else {
                    completion(false)
                    return
                }
                completion(self.start())
            }
        }
    }

    private func start() -> Bool {
        let audioSession = AVAudioSession.sharedInstance()
        do {
            try audioSession.setCategory(.record, mode: .default)
            try audioSession.setActive(true)
        } catch {
            return false
        }
        let url = FileManager.default.temporaryDirectory
            .appending(path: "fabric-voice-\(UUID().uuidString).m4a")
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ]
        do {
            let recorder = try AVAudioRecorder(url: url, settings: settings)
            guard recorder.record(forDuration: Self.maximumDurationSeconds) else { return false }
            self.recorder = recorder
            fileURL = url
            return true
        } catch {
            return false
        }
    }

    func stop() -> Result? {
        guard let recorder, let fileURL else { return nil }
        let durationMs = max(1, Int(recorder.currentTime * 1_000))
        recorder.stop()
        self.recorder = nil
        self.fileURL = nil
        try? AVAudioSession.sharedInstance().setActive(false)
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return nil }
        return Result(fileURL: fileURL, durationMs: durationMs)
    }

    func cancel() {
        guard let recorder else { return }
        recorder.stop()
        if let fileURL {
            try? FileManager.default.removeItem(at: fileURL)
        }
        self.recorder = nil
        fileURL = nil
        try? AVAudioSession.sharedInstance().setActive(false)
    }
}
