import Foundation
import Speech

/// Bounded phone-side holding pen for voice notes the watch has already
/// handed off. `transferFile` is store-and-forward: by the time the phone
/// sees the audio, the watch shows it as delivered, so the phone must not
/// silently drop it just because the gateway socket happens to be closed.
///
/// This is not a blind offline prompt queue (`PRODUCTION.md` forbids those):
/// entries are user-authored, definitely-unsent recordings; nothing here
/// retries a side-effecting RPC — the drain submits each note exactly once
/// through the gated path and stops on the first unavailable outcome. The
/// same TTL and cap as the watch queue keep it bounded, and a full local
/// reset removes the directory.
final class WatchVoiceNoteStore: @unchecked Sendable {
    static let shared = WatchVoiceNoteStore()

    struct PendingVoiceNote: Equatable {
        let metadata: WatchVoiceNoteMetadata
        let audioURL: URL
    }

    private let queue = DispatchQueue(label: "fabric.watch.voice-note-store")
    private let directoryURL: URL
    private var draining = false

    init(directoryURL: URL? = nil) {
        if let directoryURL {
            self.directoryURL = directoryURL
        } else {
            let base = FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first ?? FileManager.default.temporaryDirectory
            self.directoryURL = base.appending(
                path: "FabricWatchRelay/VoiceNotes",
                directoryHint: .isDirectory
            )
        }
    }

    /// Persist one received transfer. The metadata sidecar makes the entry
    /// self-describing across launches; unreadable entries are removed.
    func store(fileAt url: URL, metadata: WatchVoiceNoteMetadata) {
        queue.sync {
            do {
                try FileManager.default.createDirectory(
                    at: directoryURL,
                    withIntermediateDirectories: true
                )
                let audioURL = directoryURL.appending(path: "\(metadata.id).audio")
                let sidecarURL = directoryURL.appending(path: "\(metadata.id).json")
                if FileManager.default.fileExists(atPath: audioURL.path) {
                    try FileManager.default.removeItem(atPath: audioURL.path)
                }
                try FileManager.default.moveItem(at: url, to: audioURL)
                let sidecar = try JSONSerialization.data(
                    withJSONObject: metadata.encoded()
                )
                try sidecar.write(to: sidecarURL)
                pruneLocked()
            } catch {
                try? FileManager.default.removeItem(at: url)
            }
        }
    }

    func pending() -> [PendingVoiceNote] {
        queue.sync { pendingLocked() }
    }

    func removeAll() throws {
        try queue.sync {
            if FileManager.default.fileExists(atPath: directoryURL.path) {
                try FileManager.default.removeItem(at: directoryURL)
            }
        }
    }

    private func pendingLocked() -> [PendingVoiceNote] {
        guard let names = try? FileManager.default.contentsOfDirectory(
            atPath: directoryURL.path
        ) else { return [] }
        var notes: [PendingVoiceNote] = []
        for name in names where name.hasSuffix(".json") {
            let sidecarURL = directoryURL.appending(path: name)
            guard let data = try? Data(contentsOf: sidecarURL),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let metadata = WatchVoiceNoteMetadata(payload: object)
            else {
                try? FileManager.default.removeItem(at: sidecarURL)
                continue
            }
            let audioURL = directoryURL.appending(path: "\(metadata.id).audio")
            guard FileManager.default.fileExists(atPath: audioURL.path) else {
                try? FileManager.default.removeItem(at: sidecarURL)
                continue
            }
            notes.append(PendingVoiceNote(metadata: metadata, audioURL: audioURL))
        }
        return notes.sorted { $0.metadata.createdAt < $1.metadata.createdAt }
    }

    private func removeLocked(id: String) {
        try? FileManager.default.removeItem(
            at: directoryURL.appending(path: "\(id).audio")
        )
        try? FileManager.default.removeItem(
            at: directoryURL.appending(path: "\(id).json")
        )
    }

    private func pruneLocked() {
        let now = Date().timeIntervalSince1970
        var notes = pendingLocked()
        for note in notes where now - note.metadata.createdAt >= WatchNoteQueuePolicy.noteTimeToLive {
            removeLocked(id: note.metadata.id)
        }
        notes = pendingLocked()
        while notes.count > WatchNoteQueuePolicy.maximumQueuedNotes {
            removeLocked(id: notes.removeFirst().metadata.id)
        }
    }

    private func remove(id: String) {
        queue.sync { removeLocked(id: id) }
    }

    /// Transcribe and submit every pending note, oldest first. Stops at the
    /// first unavailable delivery (the remainder waits for the next drain);
    /// an untranscribable recording is reported and dropped rather than
    /// wedging the queue forever.
    @MainActor
    func drain(
        appModel: AppModel,
        reportOutcome: @MainActor (String, String, String?) -> Void
    ) async {
        guard !draining else { return }
        draining = true
        defer { draining = false }

        for note in pending() {
            guard appModel.phase == .connected else { return }
            let text: String
            do {
                text = try await WatchVoiceNoteTranscriber.transcribe(fileAt: note.audioURL)
            } catch {
                remove(id: note.metadata.id)
                reportOutcome(note.metadata.id, "failed", "The recording couldn't be transcribed.")
                continue
            }
            guard let trimmedNote = WatchQuickNote.make(
                text: text,
                id: note.metadata.id,
                createdAt: note.metadata.createdAt
            ) else {
                remove(id: note.metadata.id)
                reportOutcome(note.metadata.id, "failed", "No speech was recognized in the recording.")
                continue
            }
            switch await appModel.deliverWatchNote(text: trimmedNote.text) {
            case .accepted:
                remove(id: note.metadata.id)
                reportOutcome(note.metadata.id, "submitted", nil)
            case .unavailable(let reason):
                reportOutcome(note.metadata.id, "held", reason)
                return
            }
        }
    }
}

/// One-shot file transcription with Apple Speech — the same provider the
/// phone's dictation path already declares (`NSSpeechRecognitionUsageDescription`
/// is in the app manifest). Fails closed on denied authorization; nothing is
/// ever submitted from a recording the user did not permit transcribing.
enum WatchVoiceNoteTranscriber {
    enum TranscriptionError: Error {
        case notAuthorized
        case recognizerUnavailable
        case noResult
    }

    static func transcribe(fileAt url: URL) async throws -> String {
        let status = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
        guard status == .authorized else { throw TranscriptionError.notAuthorized }
        guard let recognizer = SFSpeechRecognizer(), recognizer.isAvailable else {
            throw TranscriptionError.recognizerUnavailable
        }
        let request = SFSpeechURLRecognitionRequest(url: url)
        request.shouldReportPartialResults = false
        return try await withCheckedThrowingContinuation { continuation in
            var finished = false
            recognizer.recognitionTask(with: request) { result, error in
                guard !finished else { return }
                if let error {
                    finished = true
                    continuation.resume(throwing: error)
                    return
                }
                guard let result, result.isFinal else { return }
                finished = true
                let text = result.bestTranscription.formattedString
                if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    continuation.resume(throwing: TranscriptionError.noResult)
                } else {
                    continuation.resume(returning: text)
                }
            }
        }
    }
}
