import Foundation
import SwiftUI
import WatchConnectivity

/// iPhone side of the W-relay transport (`WATCH.md` §5).
///
/// The phone remains the single authenticated gateway client: the watch never
/// sees credentials, and every note the wrist captures is delivered through
/// the same capability-gated `session.create` + `prompt.submit` path a typed
/// phone message uses. When that path is unavailable the reply says so and
/// the note stays queued on the watch — there is no phone-side ghost queue
/// for text notes (voice notes are files and use the bounded pending store,
/// because `transferFile` delivery is store-and-forward and cannot be
/// refused mid-flight).
@MainActor
final class WatchRelay: NSObject {
    static let shared = WatchRelay()

    private weak var appModel: AppModel?
    private var activated = false
    /// Pet state from the live chat surface; nil when no chat is on screen.
    private var liveChatPetState: PetState?
    private var lastPublishedContext: WatchRelayContext?
    private var lastQueuedSpriteRevision: String?

    private var session: WCSession? {
        WCSession.isSupported() ? WCSession.default : nil
    }

    /// Idempotent. Call once from the app entry; safe on devices with no
    /// paired watch (the session simply never reports a counterpart).
    func activate(appModel: AppModel) {
        self.appModel = appModel
        guard !activated, let session else { return }
        activated = true
        session.delegate = self
        session.activate()
    }

    /// The chat surface reports its derived pet state so the wrist mirrors
    /// the exact animation the phone shows. Passing nil (chat left the
    /// screen) falls back to a steady idle pose.
    func updateLiveChatPetState(_ state: PetState?) {
        liveChatPetState = state
        publishContext()
    }

    /// Scene became active: drain any voice notes that arrived while the
    /// gateway socket was down, then refresh the wrist snapshot.
    func phoneDidBecomeActive() {
        publishContext()
        guard let appModel else { return }
        Task { [weak self] in
            await WatchVoiceNoteStore.shared.drain(appModel: appModel) { id, status, reason in
                self?.sendVoiceNoteOutcome(id: id, status: status, reason: reason)
            }
        }
    }

    /// Push the current connection + pet snapshot to the watch. Latest-wins
    /// (`updateApplicationContext`), deduplicated so animation-state churn
    /// while nothing user-visible changed does not spam the transport.
    func publishContext() {
        guard let appModel, let session, session.activationState == .activated,
              session.isPaired, session.isWatchAppInstalled else { return }

        let phase: String
        switch appModel.phase {
        case .connected: phase = "connected"
        case .connecting: phase = "connecting"
        case .reconnecting: phase = "reconnecting"
        case .disconnected: phase = "disconnected"
        }

        var petName: String?
        var petRevision: String?
        var petAvailable = false
        if case .active(let display) = appModel.petState {
            petName = display.sheet.displayName
            petRevision = display.sheet.spritesheetRevision
            petAvailable = true
        }

        let context = WatchRelayContext(
            phase: phase,
            gatewayLabel: appModel.activeGateway?.label,
            petStateRaw: (liveChatPetState ?? .idle).rawValue,
            petName: petName,
            petRevision: petRevision,
            petAvailable: petAvailable,
            updatedAt: Date().timeIntervalSince1970
        )

        // Compare everything except the timestamp; identical snapshots are
        // not re-sent.
        if let previous = lastPublishedContext,
           previous.phase == context.phase,
           previous.gatewayLabel == context.gatewayLabel,
           previous.petStateRaw == context.petStateRaw,
           previous.petName == context.petName,
           previous.petRevision == context.petRevision,
           previous.petAvailable == context.petAvailable {
            return
        }
        lastPublishedContext = context
        try? session.updateApplicationContext(context.encoded())

        if case .active(let display) = appModel.petState {
            queueSpriteTransferIfNeeded(display.sheet)
        }
    }

    // MARK: - Sprite transfer

    /// Ship the decoded atlas once per revision. `transferFile` is
    /// store-and-forward, so a queued transfer survives both apps closing.
    private func queueSpriteTransferIfNeeded(_ sheet: PetSpriteSheet, force: Bool = false) {
        guard let session, session.activationState == .activated,
              session.isPaired, session.isWatchAppInstalled else { return }
        guard force || sheet.spritesheetRevision != lastQueuedSpriteRevision else { return }
        guard !sheet.spritesheetRevision.isEmpty,
              let data = Data(base64Encoded: sheet.spritesheetBase64) else { return }

        let manifest = WatchSpriteManifest(
            slug: sheet.slug,
            displayName: sheet.displayName,
            revision: sheet.spritesheetRevision,
            mime: sheet.mime,
            frameW: sheet.frameW,
            frameH: sheet.frameH,
            framesPerState: sheet.framesPerState,
            loopMs: sheet.loopMs,
            stateRows: sheet.stateRows,
            framesByRow: sheet.framesByRow
        )
        let fileURL = FileManager.default.temporaryDirectory
            .appending(path: "fabric-pet-\(UUID().uuidString).sprite")
        do {
            try data.write(to: fileURL)
        } catch {
            return
        }
        lastQueuedSpriteRevision = sheet.spritesheetRevision
        session.transferFile(fileURL, metadata: manifest.encoded())
    }

    private func handleSpriteRequest(haveRevision: String?) {
        guard let appModel, case .active(let display) = appModel.petState else { return }
        guard display.sheet.spritesheetRevision != haveRevision else { return }
        queueSpriteTransferIfNeeded(display.sheet, force: true)
    }

    // MARK: - Inbound notes

    private func handleNoteMessage(
        _ payload: [String: Any],
        reply: @escaping ([String: Any]) -> Void
    ) {
        guard let note = WatchQuickNote(payload: payload) else {
            reply(WatchNoteReply.unavailable(reason: "The note couldn't be read. Try again.").encoded())
            return
        }
        guard let appModel else {
            reply(WatchNoteReply.unavailable(reason: "Open Fabric on your iPhone first.").encoded())
            return
        }
        Task { @MainActor in
            let outcome = await appModel.deliverWatchNote(text: note.text)
            reply(outcome.encoded())
        }
    }

    private func sendVoiceNoteOutcome(id: String, status: String, reason: String?) {
        guard let session, session.activationState == .activated, session.isReachable else { return }
        session.sendMessage(
            WatchRelayControl.voiceNoteOutcome(id: id, status: status, reason: reason),
            replyHandler: nil,
            errorHandler: nil
        )
    }

    fileprivate func routeMessage(
        _ payload: [String: Any],
        reply: @escaping ([String: Any]) -> Void
    ) {
        switch payload[WatchRelayKey.kind] as? String {
        case "note.text":
            handleNoteMessage(payload, reply: reply)
        case "pet.sprite.request":
            handleSpriteRequest(haveRevision: payload["haveRevision"] as? String)
            reply(["status": "ok"])
        default:
            reply(WatchNoteReply.unavailable(reason: "Update Fabric on your iPhone to use this.").encoded())
        }
    }

    fileprivate func routeReceivedVoiceFile(storedAt url: URL, metadata: [String: Any]) {
        guard let metadata = WatchVoiceNoteMetadata(payload: metadata) else {
            try? FileManager.default.removeItem(at: url)
            return
        }
        WatchVoiceNoteStore.shared.store(fileAt: url, metadata: metadata)
        guard let appModel else { return }
        Task { [weak self] in
            await WatchVoiceNoteStore.shared.drain(appModel: appModel) { id, status, reason in
                self?.sendVoiceNoteOutcome(id: id, status: status, reason: reason)
            }
        }
    }
}

// MARK: - WCSessionDelegate

extension WatchRelay: WCSessionDelegate {
    nonisolated func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        Task { @MainActor in self.publishContext() }
    }

    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}

    nonisolated func sessionDidDeactivate(_ session: WCSession) {
        // A watch switch deactivates the old session; reactivating binds the
        // new watch.
        session.activate()
    }

    nonisolated func sessionWatchStateDidChange(_ session: WCSession) {
        Task { @MainActor in self.publishContext() }
    }

    nonisolated func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        Task { @MainActor in
            self.routeMessage(message, reply: replyHandler)
        }
    }

    nonisolated func session(_ session: WCSession, didReceive file: WCSessionFile) {
        // The incoming file is deleted when this callback returns; move it
        // synchronously before hopping actors.
        let metadata = file.metadata ?? [:]
        let holding = FileManager.default.temporaryDirectory
            .appending(path: "fabric-watch-voice-\(UUID().uuidString).m4a")
        do {
            try FileManager.default.moveItem(at: file.fileURL, to: holding)
        } catch {
            return
        }
        Task { @MainActor in
            self.routeReceivedVoiceFile(storedAt: holding, metadata: metadata)
        }
    }
}

// MARK: - Note delivery through the gated gateway path

extension AppModel {
    /// Deliver one wrist-captured note as its own goal: a fresh session plus
    /// one gated `prompt.submit`, exactly the baseline-chat contract. Any
    /// missing precondition returns `unavailable` so the watch keeps the note
    /// — this path never buffers and never retries on its own.
    func deliverWatchNote(text: String) async -> WatchNoteReply {
        guard phase == .connected else {
            return .unavailable(reason: "iPhone isn't connected to Fabric right now.")
        }
        guard supportsGatewayMethod("session.create"),
              supportsGatewayMethod("prompt.submit") else {
            return .unavailable(reason: "This Fabric server can't accept notes from the watch.")
        }
        do {
            let session = try await api.createSession()
            guard !session.sessionId.isEmpty else {
                return .unavailable(reason: "Fabric couldn't start a session for this note.")
            }
            try await api.submitPrompt(sessionId: session.sessionId, text: text)
            return .accepted(sessionId: session.sessionId)
        } catch {
            return .unavailable(reason: "Fabric couldn't take the note right now. It stays on your watch.")
        }
    }
}

// MARK: - Scene bridge

/// One modifier wires the relay into the app entry: activation, connection /
/// pet snapshots, and the foreground voice-note drain. Everything it observes
/// is already `Equatable` app state — no new signals, no polling.
struct WatchRelayBridge: ViewModifier {
    let appModel: AppModel
    @Environment(\.scenePhase) private var scenePhase

    func body(content: Content) -> some View {
        content
            .task { WatchRelay.shared.activate(appModel: appModel) }
            .onChange(of: appModel.phase) { WatchRelay.shared.publishContext() }
            .onChange(of: appModel.petState) { WatchRelay.shared.publishContext() }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { WatchRelay.shared.phoneDidBecomeActive() }
            }
    }
}

extension View {
    func watchRelayBridge(_ appModel: AppModel) -> some View {
        modifier(WatchRelayBridge(appModel: appModel))
    }
}
