import Foundation
import Observation
import WatchConnectivity
import WidgetKit

/// A transient, user-visible outcome for the last note action.
struct WatchNoteBanner: Equatable {
    enum Tone { case success, info, failure }
    let tone: Tone
    let text: String
}

/// Root watch state: the last relayed connection/pet snapshot, the local
/// sprite library, and the bounded note queue. All truth about delivery
/// comes from phone replies — the watch never marks a note sent on its own.
@Observable
@MainActor
final class WatchAppModel {
    private(set) var context: WatchRelayContext?
    private(set) var sprite: WatchSpriteAtlas?
    private(set) var queuedNotes: [WatchQuickNote] = []
    private(set) var phoneReachable = false
    private(set) var banner: WatchNoteBanner?

    private let link = WatchPhoneLink()
    private let store = WatchLocalStore()
    private var flushInFlight = false
    private var bannerClearTask: Task<Void, Never>?

    init() {
        queuedNotes = WatchNoteQueuePolicy.prune(
            store.loadNotes(),
            now: Date().timeIntervalSince1970
        )
        context = store.loadContext()
        sprite = store.loadSprite()
        link.model = self
        link.activate()
    }

    var petStateRaw: String { context?.petStateRaw ?? "idle" }
    var pose: WatchPetPose { WatchPetPose.pose(for: petStateRaw) }

    /// One-line status for the home screen, honest about which hop is down.
    var statusLine: String {
        guard let context else { return "Open Fabric on your iPhone to link." }
        if !phoneReachable {
            return "iPhone out of reach — notes will queue."
        }
        if context.isConnected {
            return context.gatewayLabel ?? "Connected"
        }
        return "iPhone isn't connected to Fabric."
    }

    // MARK: - Notes

    func submitNote(_ text: String) {
        guard let note = WatchQuickNote.make(
            text: text,
            id: UUID().uuidString,
            createdAt: Date().timeIntervalSince1970
        ) else { return }
        queuedNotes.append(note)
        persistNotes()
        flush()
    }

    /// Deliver queued notes head-first. One in-flight send at a time; any
    /// non-accepted outcome stops the pass and keeps order intact.
    func flush() {
        guard !flushInFlight, phoneReachable, let head = queuedNotes.first else { return }
        flushInFlight = true
        link.sendNote(head) { [weak self] reply in
            Task { @MainActor in
                guard let self else { return }
                self.flushInFlight = false
                switch reply {
                case .accepted:
                    self.queuedNotes.removeAll { $0.id == head.id }
                    self.persistNotes()
                    self.showBanner(WatchNoteBanner(tone: .success, text: "Note sent to Fabric."))
                    self.flush()
                case .unavailable(let reason):
                    self.showBanner(WatchNoteBanner(tone: .info, text: reason))
                case nil:
                    // Transport error: the note stays queued; reachability
                    // changes retrigger the flush.
                    break
                }
            }
        }
    }

    // MARK: - Voice notes

    /// Hand one recording to the phone. `transferFile` is store-and-forward,
    /// so from the wrist's perspective the note is delivered once queued;
    /// the phone reports transcription/submission outcomes asynchronously.
    func sendVoiceNote(fileURL: URL, durationMs: Int) {
        let metadata = WatchVoiceNoteMetadata(
            id: UUID().uuidString,
            createdAt: Date().timeIntervalSince1970,
            durationMs: durationMs,
            mimeType: "audio/mp4"
        )
        link.transferVoiceNote(fileURL: fileURL, metadata: metadata)
        showBanner(WatchNoteBanner(tone: .info, text: "Voice note handed to iPhone."))
    }

    // MARK: - Link callbacks

    func receivedContext(_ context: WatchRelayContext) {
        self.context = context
        store.saveContext(context)
        publishWidgetSnapshot(context)
        if let revision = context.petRevision, revision != sprite?.manifest.revision {
            link.requestSprite(haveRevision: sprite?.manifest.revision)
        }
        flush()
    }

    func receivedSprite(_ atlas: WatchSpriteAtlas) {
        sprite = atlas
    }

    func reachabilityChanged(_ reachable: Bool) {
        phoneReachable = reachable
        if reachable {
            flush()
            if let revision = context?.petRevision, revision != sprite?.manifest.revision {
                link.requestSprite(haveRevision: sprite?.manifest.revision)
            }
        }
    }

    func receivedVoiceNoteOutcome(status: String, reason: String?) {
        switch status {
        case "submitted":
            showBanner(WatchNoteBanner(tone: .success, text: "Voice note sent to Fabric."))
        case "held":
            showBanner(WatchNoteBanner(
                tone: .info,
                text: reason ?? "Voice note is waiting on the iPhone."
            ))
        default:
            showBanner(WatchNoteBanner(
                tone: .failure,
                text: reason ?? "Voice note couldn't be transcribed."
            ))
        }
    }

    var spriteStore: WatchLocalStore { store }

    // MARK: - Private

    private func persistNotes() {
        queuedNotes = WatchNoteQueuePolicy.prune(
            queuedNotes,
            now: Date().timeIntervalSince1970
        )
        store.saveNotes(queuedNotes)
    }

    private func showBanner(_ banner: WatchNoteBanner) {
        self.banner = banner
        bannerClearTask?.cancel()
        bannerClearTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            guard !Task.isCancelled else { return }
            self?.banner = nil
        }
    }

    private var lastWidgetSnapshot: [String: Any]?

    private func publishWidgetSnapshot(_ context: WatchRelayContext) {
        let snapshot = WatchWidgetSnapshot.encode(context: context)
        // Reload budgets are real; skip when nothing glanceable changed.
        if let last = lastWidgetSnapshot,
           last["petState"] as? String == snapshot["petState"] as? String,
           last["connected"] as? Bool == snapshot["connected"] as? Bool,
           last["attention"] as? Bool == snapshot["attention"] as? Bool,
           last["petName"] as? String == snapshot["petName"] as? String {
            return
        }
        lastWidgetSnapshot = snapshot
        store.saveWidgetSnapshot(snapshot)
        WidgetCenter.shared.reloadAllTimelines()
    }
}

/// Watch side of the `WCSession` transport. Thin by design: decode, hop to
/// the main actor, hand to the model.
final class WatchPhoneLink: NSObject {
    @MainActor weak var model: WatchAppModel?

    func activate() {
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        session.delegate = self
        session.activate()
    }

    @MainActor
    func sendNote(_ note: WatchQuickNote, completion: @escaping (WatchNoteReply?) -> Void) {
        let session = WCSession.default
        guard session.activationState == .activated, session.isReachable else {
            completion(nil)
            return
        }
        session.sendMessage(
            note.encoded(),
            replyHandler: { payload in completion(WatchNoteReply(payload: payload)) },
            errorHandler: { _ in completion(nil) }
        )
    }

    @MainActor
    func transferVoiceNote(fileURL: URL, metadata: WatchVoiceNoteMetadata) {
        let session = WCSession.default
        guard session.activationState == .activated else { return }
        session.transferFile(fileURL, metadata: metadata.encoded())
    }

    @MainActor
    func requestSprite(haveRevision: String?) {
        let session = WCSession.default
        guard session.activationState == .activated, session.isReachable else { return }
        session.sendMessage(
            WatchRelayControl.spriteRequest(haveRevision: haveRevision),
            replyHandler: nil,
            errorHandler: nil
        )
    }
}

extension WatchPhoneLink: WCSessionDelegate {
    nonisolated func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        let stored = session.receivedApplicationContext
        let reachable = session.isReachable
        Task { @MainActor in
            guard let model = self.model else { return }
            if let context = WatchRelayContext(payload: stored) {
                model.receivedContext(context)
            }
            model.reachabilityChanged(reachable)
        }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        let reachable = session.isReachable
        Task { @MainActor in
            self.model?.reachabilityChanged(reachable)
        }
    }

    nonisolated func session(
        _ session: WCSession,
        didReceiveApplicationContext applicationContext: [String: Any]
    ) {
        guard let context = WatchRelayContext(payload: applicationContext) else { return }
        Task { @MainActor in
            self.model?.receivedContext(context)
        }
    }

    nonisolated func session(_ session: WCSession, didReceive file: WCSessionFile) {
        // The transferred file is deleted when this callback returns; move it
        // synchronously before hopping actors.
        guard let manifest = WatchSpriteManifest(payload: file.metadata ?? [:]) else { return }
        let holding = FileManager.default.temporaryDirectory
            .appending(path: "fabric-sprite-\(UUID().uuidString).atlas")
        do {
            try FileManager.default.moveItem(at: file.fileURL, to: holding)
        } catch {
            return
        }
        Task { @MainActor in
            guard let model = self.model else {
                try? FileManager.default.removeItem(at: holding)
                return
            }
            if let atlas = model.spriteStore.installSprite(
                from: holding,
                manifest: manifest
            ) {
                model.receivedSprite(atlas)
            }
        }
    }

    nonisolated func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any]
    ) {
        guard message[WatchRelayKey.kind] as? String == "note.voice.outcome",
              let status = message["status"] as? String else { return }
        let reason = message["reason"] as? String
        Task { @MainActor in
            self.model?.receivedVoiceNoteOutcome(status: status, reason: reason)
        }
    }
}
