import Foundation

/// Wire contract for the phone ↔ watch relay (`WATCH.md` §5, W-relay).
///
/// Compiled into three targets — the iOS app, the watch app, and the watch
/// widget extension — so both ends of every `WCSession` payload share one
/// codec and one validation rule. Everything here is pure Foundation and
/// property-list-safe: `WCSession` only transports plist types.
///
/// The watch holds no gateway credentials and never re-derives pet state; the
/// phone remains the single authenticated client and the single
/// activity→animation brain (`PetActivitySnapshot.derive`). The relay ships
/// results, not signals.
let watchRelayProtocolVersion = 1

enum WatchRelayKey {
    static let version = "v"
    static let kind = "kind"
}

// MARK: - Phone → watch application context

/// Latest-wins connection + pet snapshot delivered via
/// `updateApplicationContext`. Missing or malformed payloads decode to nil so
/// a newer phone can add fields without stranding an older watch, while a
/// wrong protocol version fails closed.
struct WatchRelayContext: Equatable {
    let phase: String
    let gatewayLabel: String?
    let petStateRaw: String
    let petName: String?
    let petRevision: String?
    let petAvailable: Bool
    let updatedAt: Double

    var isConnected: Bool { phase == "connected" }
    /// The one state that means "blocked on the user" (approval or question).
    var needsAttention: Bool { petStateRaw == "waiting" }

    func encoded() -> [String: Any] {
        var payload: [String: Any] = [
            WatchRelayKey.version: watchRelayProtocolVersion,
            "phase": phase,
            "petState": petStateRaw,
            "petAvailable": petAvailable,
            "updatedAt": updatedAt,
        ]
        payload["gatewayLabel"] = gatewayLabel
        payload["petName"] = petName
        payload["petRevision"] = petRevision
        return payload
    }

    init(
        phase: String,
        gatewayLabel: String?,
        petStateRaw: String,
        petName: String?,
        petRevision: String?,
        petAvailable: Bool,
        updatedAt: Double
    ) {
        self.phase = phase
        self.gatewayLabel = gatewayLabel
        self.petStateRaw = petStateRaw
        self.petName = petName
        self.petRevision = petRevision
        self.petAvailable = petAvailable
        self.updatedAt = updatedAt
    }

    init?(payload: [String: Any]) {
        guard payload[WatchRelayKey.version] as? Int == watchRelayProtocolVersion,
              let phase = payload["phase"] as? String, !phase.isEmpty,
              let petStateRaw = payload["petState"] as? String, !petStateRaw.isEmpty,
              let updatedAt = payload["updatedAt"] as? Double
        else { return nil }
        self.phase = phase
        gatewayLabel = payload["gatewayLabel"] as? String
        self.petStateRaw = petStateRaw
        petName = payload["petName"] as? String
        petRevision = payload["petRevision"] as? String
        petAvailable = payload["petAvailable"] as? Bool ?? false
        self.updatedAt = updatedAt
    }
}

// MARK: - Watch → phone quick notes

/// One dictated/typed note captured on the wrist. Notes are user-authored,
/// definitely-unsent content — the only category the offline contract permits
/// to queue (`ARCHITECTURE.md` §6).
struct WatchQuickNote: Equatable {
    /// Transport bound: WCSession messages are small plists; a note is a
    /// thought, not a document.
    static let maximumTextLength = 8_000

    let id: String
    let text: String
    let createdAt: Double

    /// nil for empty (post-trim) or oversized text — never send a blank turn.
    static func make(text: String, id: String, createdAt: Double) -> WatchQuickNote? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= maximumTextLength else { return nil }
        return WatchQuickNote(id: id, text: trimmed, createdAt: createdAt)
    }

    func encoded() -> [String: Any] {
        [
            WatchRelayKey.version: watchRelayProtocolVersion,
            WatchRelayKey.kind: "note.text",
            "id": id,
            "text": text,
            "createdAt": createdAt,
        ]
    }

    init(id: String, text: String, createdAt: Double) {
        self.id = id
        self.text = text
        self.createdAt = createdAt
    }

    init?(payload: [String: Any]) {
        guard payload[WatchRelayKey.version] as? Int == watchRelayProtocolVersion,
              payload[WatchRelayKey.kind] as? String == "note.text",
              let id = payload["id"] as? String, !id.isEmpty,
              let text = payload["text"] as? String,
              let createdAt = payload["createdAt"] as? Double,
              let valid = WatchQuickNote.make(text: text, id: id, createdAt: createdAt),
              valid.text == text
        else { return nil }
        self = valid
    }
}

/// Phone's reply to one note delivery attempt. `unavailable` keeps the note
/// on the watch — no phone-side ghost queue exists, so the reply is the whole
/// truth about where the note lives.
enum WatchNoteReply: Equatable {
    case accepted(sessionId: String?)
    case unavailable(reason: String)

    func encoded() -> [String: Any] {
        switch self {
        case .accepted(let sessionId):
            var payload: [String: Any] = ["status": "accepted"]
            payload["sessionId"] = sessionId
            return payload
        case .unavailable(let reason):
            return ["status": "unavailable", "reason": reason]
        }
    }

    init?(payload: [String: Any]) {
        switch payload["status"] as? String {
        case "accepted":
            self = .accepted(sessionId: payload["sessionId"] as? String)
        case "unavailable":
            guard let reason = payload["reason"] as? String else { return nil }
            self = .unavailable(reason: reason)
        default:
            return nil
        }
    }
}

// MARK: - Watch → phone voice notes (file transfer metadata)

/// Metadata for one recorded voice note shipped via `transferFile`.
/// `mode`/`mimeType`/`durationMs` mirror the `fabric.phone_audio` v1 fields
/// so the phone can transcribe and submit without re-deriving anything.
struct WatchVoiceNoteMetadata: Equatable {
    let id: String
    let createdAt: Double
    let durationMs: Int
    let mimeType: String

    func encoded() -> [String: Any] {
        [
            WatchRelayKey.version: watchRelayProtocolVersion,
            WatchRelayKey.kind: "note.voice",
            "id": id,
            "createdAt": createdAt,
            "durationMs": durationMs,
            "mimeType": mimeType,
            "mode": "voice_note",
        ]
    }

    init(id: String, createdAt: Double, durationMs: Int, mimeType: String) {
        self.id = id
        self.createdAt = createdAt
        self.durationMs = durationMs
        self.mimeType = mimeType
    }

    init?(payload: [String: Any]) {
        guard payload[WatchRelayKey.version] as? Int == watchRelayProtocolVersion,
              payload[WatchRelayKey.kind] as? String == "note.voice",
              payload["mode"] as? String == "voice_note",
              let id = payload["id"] as? String, !id.isEmpty,
              let createdAt = payload["createdAt"] as? Double,
              let durationMs = payload["durationMs"] as? Int, durationMs > 0,
              let mimeType = payload["mimeType"] as? String, !mimeType.isEmpty
        else { return nil }
        self.id = id
        self.createdAt = createdAt
        self.durationMs = durationMs
        self.mimeType = mimeType
    }
}

// MARK: - Watch queue policy

/// Wrist mirror of the phone outbound-queue rules (`ARCHITECTURE.md` §6):
/// bounded, definitely-unsent only, oldest evicted first, expired dropped.
enum WatchNoteQueuePolicy {
    static let maximumQueuedNotes = 50
    static let noteTimeToLive: Double = 48 * 60 * 60

    /// Drop expired notes, then evict from the front (oldest) down to the cap.
    /// Order is preserved: notes deliver first-in first-out.
    static func prune(_ notes: [WatchQuickNote], now: Double) -> [WatchQuickNote] {
        let fresh = notes.filter { now - $0.createdAt < noteTimeToLive }
        guard fresh.count > maximumQueuedNotes else { return fresh }
        return Array(fresh.suffix(maximumQueuedNotes))
    }
}

// MARK: - Phone → watch sprite transfer

/// Geometry manifest accompanying one spritesheet `transferFile`. The same
/// bounds as the phone's `PetSpriteSheet` validation — gateway data stays
/// untrusted even after one relay hop.
struct WatchSpriteManifest: Equatable {
    static let maximumAtlasDimension = 8_192
    static let maximumFramesPerRow = 256
    static let maximumStateRows = 128

    let slug: String
    let displayName: String
    let revision: String
    let mime: String
    let frameW: Int
    let frameH: Int
    let framesPerState: Int
    let loopMs: Int
    let stateRows: [String]
    let framesByRow: [String: Int]

    func encoded() -> [String: Any] {
        [
            WatchRelayKey.version: watchRelayProtocolVersion,
            WatchRelayKey.kind: "pet.sprite",
            "slug": slug,
            "displayName": displayName,
            "revision": revision,
            "mime": mime,
            "frameW": frameW,
            "frameH": frameH,
            "framesPerState": framesPerState,
            "loopMs": loopMs,
            "stateRows": stateRows,
            "framesByRow": framesByRow,
        ]
    }

    init(
        slug: String,
        displayName: String,
        revision: String,
        mime: String,
        frameW: Int,
        frameH: Int,
        framesPerState: Int,
        loopMs: Int,
        stateRows: [String],
        framesByRow: [String: Int]
    ) {
        self.slug = slug
        self.displayName = displayName
        self.revision = revision
        self.mime = mime
        self.frameW = frameW
        self.frameH = frameH
        self.framesPerState = framesPerState
        self.loopMs = loopMs
        self.stateRows = stateRows
        self.framesByRow = framesByRow
    }

    init?(payload: [String: Any]) {
        guard payload[WatchRelayKey.version] as? Int == watchRelayProtocolVersion,
              payload[WatchRelayKey.kind] as? String == "pet.sprite",
              let slug = payload["slug"] as? String, !slug.isEmpty,
              let revision = payload["revision"] as? String, !revision.isEmpty,
              let frameW = payload["frameW"] as? Int, frameW > 0,
              let frameH = payload["frameH"] as? Int, frameH > 0,
              let framesPerState = payload["framesPerState"] as? Int,
              (1...Self.maximumFramesPerRow).contains(framesPerState),
              let loopMs = payload["loopMs"] as? Int, loopMs > 0,
              let stateRows = payload["stateRows"] as? [String],
              (1...Self.maximumStateRows).contains(stateRows.count),
              frameW * framesPerState <= Self.maximumAtlasDimension,
              frameH * stateRows.count <= Self.maximumAtlasDimension
        else { return nil }
        var framesByRow: [String: Int] = [:]
        if let raw = payload["framesByRow"] as? [String: Int] {
            guard raw.count <= Self.maximumStateRows,
                  raw.values.allSatisfy({ (0...Self.maximumFramesPerRow).contains($0) })
            else { return nil }
            framesByRow = raw
        }
        self.slug = slug
        displayName = payload["displayName"] as? String ?? slug
        self.revision = revision
        mime = payload["mime"] as? String ?? "image/webp"
        self.frameW = frameW
        self.frameH = frameH
        self.framesPerState = framesPerState
        self.loopMs = loopMs
        self.stateRows = stateRows
        self.framesByRow = framesByRow
    }
}

// MARK: - Sprite frame layout (pure math shared with tests)

/// Row/column resolution for one animation state, mirroring the phone's
/// `PetSpriteView`: named row when present with declared frames, `idle`
/// fallback otherwise; `framesPerState` bounded by the decoded atlas when a
/// row declares no count. Never trusts the manifest over the pixels.
struct WatchSpriteFrameLayout: Equatable {
    let rowIndex: Int
    let frames: Int
    let stepMilliseconds: Int

    static func resolve(
        stateRaw: String,
        manifest: WatchSpriteManifest,
        atlasWidth: Int,
        atlasHeight: Int
    ) -> WatchSpriteFrameLayout? {
        guard manifest.frameW > 0, manifest.frameH > 0, manifest.loopMs > 0 else { return nil }
        let name = rowName(for: stateRaw, manifest: manifest)
        guard let index = manifest.stateRows.firstIndex(of: name) else { return nil }
        let declared = manifest.framesByRow[name] ?? 0
        let atlasColumns = atlasWidth / manifest.frameW
        let frames = declared > 0 ? declared : min(manifest.framesPerState, atlasColumns)
        guard frames > 0,
              index < atlasHeight / manifest.frameH,
              frames <= atlasColumns
        else { return nil }
        return WatchSpriteFrameLayout(
            rowIndex: index,
            frames: frames,
            stepMilliseconds: max(1, manifest.loopMs / frames)
        )
    }

    /// UI state → canonical row name with the same aliases as the phone.
    static func rowName(for stateRaw: String, manifest: WatchSpriteManifest) -> String {
        let candidate: String
        switch stateRaw {
        case "wave": candidate = "waving"
        case "jump": candidate = "jumping"
        case "run": candidate = "running"
        case "failed": candidate = "failed"
        case "review": candidate = "review"
        case "waiting": candidate = "waiting"
        default: candidate = "idle"
        }
        guard manifest.stateRows.contains(candidate),
              (manifest.framesByRow[candidate] ?? 0) > 0
        else { return "idle" }
        return candidate
    }

    func column(atMillisecond elapsed: Int) -> Int {
        (elapsed / stepMilliseconds) % frames
    }
}

// MARK: - Pose fallback (symbol vocabulary)

/// SF Symbol stand-in when no spritesheet has arrived yet (or in the widget,
/// which renders no bitmaps in v1). Every pet state maps to a pose; unknown
/// future states inherit the idle pose rather than failing.
struct WatchPetPose: Equatable {
    let symbolName: String
    let caption: String
    let isAttention: Bool

    static func pose(for stateRaw: String) -> WatchPetPose {
        switch stateRaw {
        case "run":
            return WatchPetPose(symbolName: "figure.run", caption: "Working", isAttention: false)
        case "review":
            return WatchPetPose(symbolName: "text.magnifyingglass", caption: "Thinking", isAttention: false)
        case "waiting":
            return WatchPetPose(symbolName: "hand.raised.fill", caption: "Needs you", isAttention: true)
        case "failed":
            return WatchPetPose(symbolName: "exclamationmark.triangle.fill", caption: "Hit a snag", isAttention: true)
        case "jump":
            return WatchPetPose(symbolName: "party.popper.fill", caption: "Done!", isAttention: false)
        case "wave":
            return WatchPetPose(symbolName: "hand.wave.fill", caption: "Finished", isAttention: false)
        default:
            return WatchPetPose(symbolName: "pawprint.fill", caption: "Idle", isAttention: false)
        }
    }
}

// MARK: - Widget snapshot

/// The watch app writes this into the shared app-group defaults; the widget
/// extension reads it. One key, one plist dictionary, no partial writes.
enum WatchWidgetSnapshot {
    static let defaultsKey = "fabric.watch.glance.v1"
    static let appGroupInfoKey = "FabricAppGroupIdentifier"

    static func encode(context: WatchRelayContext) -> [String: Any] {
        var payload: [String: Any] = [
            WatchRelayKey.version: watchRelayProtocolVersion,
            "petState": context.petStateRaw,
            "connected": context.isConnected,
            "attention": context.needsAttention,
            "updatedAt": context.updatedAt,
        ]
        payload["petName"] = context.petName
        return payload
    }

    static func decode(_ payload: [String: Any]?) -> (
        petStateRaw: String, petName: String?, connected: Bool, attention: Bool, updatedAt: Double
    )? {
        guard let payload,
              payload[WatchRelayKey.version] as? Int == watchRelayProtocolVersion,
              let petStateRaw = payload["petState"] as? String,
              let updatedAt = payload["updatedAt"] as? Double
        else { return nil }
        return (
            petStateRaw: petStateRaw,
            petName: payload["petName"] as? String,
            connected: payload["connected"] as? Bool ?? false,
            attention: payload["attention"] as? Bool ?? false,
            updatedAt: updatedAt
        )
    }
}

// MARK: - Control messages

/// Small watch→phone / phone→watch request-reply kinds that ride
/// `sendMessage` beside notes.
enum WatchRelayControl {
    /// Watch asks the phone to (re)send the sprite it is missing.
    static func spriteRequest(haveRevision: String?) -> [String: Any] {
        var payload: [String: Any] = [
            WatchRelayKey.version: watchRelayProtocolVersion,
            WatchRelayKey.kind: "pet.sprite.request",
        ]
        payload["haveRevision"] = haveRevision
        return payload
    }

    /// Phone reports the fate of one transferred voice note.
    static func voiceNoteOutcome(id: String, status: String, reason: String?) -> [String: Any] {
        var payload: [String: Any] = [
            WatchRelayKey.version: watchRelayProtocolVersion,
            WatchRelayKey.kind: "note.voice.outcome",
            "id": id,
            "status": status,
        ]
        payload["reason"] = reason
        return payload
    }
}
