import Foundation
import XCTest
@testable import Fabric

/// The watch relay codec is compiled into three targets from one file; these
/// tests pin its behavioral contract — validation, round-trips, queue policy,
/// and the sprite frame math — without touching `WCSession`.
final class WatchRelayContractTests: XCTestCase {
    // MARK: - Context

    func testContextRoundTripsThroughItsWireEncoding() {
        let context = WatchRelayContext(
            phase: "connected",
            gatewayLabel: "Studio Mac",
            petStateRaw: "run",
            petName: "Boba",
            petRevision: "12345:678",
            petAvailable: true,
            updatedAt: 1_700_000_000
        )
        let decoded = WatchRelayContext(payload: context.encoded())
        XCTAssertEqual(decoded, context)
        XCTAssertTrue(decoded?.isConnected == true)
        XCTAssertFalse(decoded?.needsAttention == true)
    }

    func testContextAttentionTracksTheWaitingState() {
        let context = WatchRelayContext(
            phase: "connected",
            gatewayLabel: nil,
            petStateRaw: "waiting",
            petName: nil,
            petRevision: nil,
            petAvailable: false,
            updatedAt: 1
        )
        XCTAssertTrue(context.needsAttention)
    }

    func testContextRejectsWrongVersionAndMissingFields() {
        var payload = WatchRelayContext(
            phase: "connected",
            gatewayLabel: nil,
            petStateRaw: "idle",
            petName: nil,
            petRevision: nil,
            petAvailable: false,
            updatedAt: 1
        ).encoded()
        payload[WatchRelayKey.version] = watchRelayProtocolVersion + 1
        XCTAssertNil(WatchRelayContext(payload: payload))
        XCTAssertNil(WatchRelayContext(payload: [:]))
        XCTAssertNil(WatchRelayContext(payload: [
            WatchRelayKey.version: watchRelayProtocolVersion,
            "phase": "connected",
        ]))
    }

    // MARK: - Notes

    func testNoteMakeTrimsAndRejectsEmptyOrOversizedText() {
        XCTAssertNil(WatchQuickNote.make(text: "   \n ", id: "a", createdAt: 1))
        XCTAssertNil(WatchQuickNote.make(
            text: String(repeating: "x", count: WatchQuickNote.maximumTextLength + 1),
            id: "a",
            createdAt: 1
        ))
        let note = WatchQuickNote.make(text: "  remember the demo  ", id: "a", createdAt: 1)
        XCTAssertEqual(note?.text, "remember the demo")
    }

    func testNoteRoundTripsThroughItsWireEncoding() throws {
        let note = try XCTUnwrap(
            WatchQuickNote.make(text: "ship the voice note workflow", id: "n-1", createdAt: 42)
        )
        XCTAssertEqual(WatchQuickNote(payload: note.encoded()), note)
    }

    func testNoteDecodeRejectsUntrimmedWirePayloads() {
        // A payload whose text does not survive validation verbatim is not a
        // note this codec produced; fail closed instead of silently rewriting.
        var payload = WatchQuickNote(id: "n-1", text: "hello", createdAt: 42).encoded()
        payload["text"] = "  hello  "
        XCTAssertNil(WatchQuickNote(payload: payload))
    }

    func testNoteReplyRoundTripsBothOutcomes() {
        let accepted = WatchNoteReply.accepted(sessionId: "s-1")
        XCTAssertEqual(WatchNoteReply(payload: accepted.encoded()), accepted)
        let unavailable = WatchNoteReply.unavailable(reason: "offline")
        XCTAssertEqual(WatchNoteReply(payload: unavailable.encoded()), unavailable)
        XCTAssertNil(WatchNoteReply(payload: ["status": "unavailable"]))
    }

    // MARK: - Queue policy

    func testQueuePruneDropsExpiredAndEvictsOldestBeyondTheCap() throws {
        let now: Double = 1_000_000
        let expired = try XCTUnwrap(WatchQuickNote.make(
            text: "old",
            id: "expired",
            createdAt: now - WatchNoteQueuePolicy.noteTimeToLive
        ))
        var notes = [expired]
        let surplus = 5
        for index in 0..<(WatchNoteQueuePolicy.maximumQueuedNotes + surplus) {
            notes.append(try XCTUnwrap(WatchQuickNote.make(
                text: "note \(index)",
                id: "n-\(index)",
                createdAt: now - Double(1_000 - index)
            )))
        }

        let pruned = WatchNoteQueuePolicy.prune(notes, now: now)

        XCTAssertEqual(pruned.count, WatchNoteQueuePolicy.maximumQueuedNotes)
        XCTAssertFalse(pruned.contains { $0.id == "expired" })
        // Eviction removes from the front: the oldest fresh notes go first
        // and delivery order is preserved for the rest.
        XCTAssertEqual(pruned.first?.id, "n-\(surplus)")
        XCTAssertEqual(pruned.last?.id, "n-\(WatchNoteQueuePolicy.maximumQueuedNotes + surplus - 1)")
    }

    // MARK: - Voice metadata

    func testVoiceMetadataRoundTripsAndRejectsNonPositiveDurations() {
        let metadata = WatchVoiceNoteMetadata(
            id: "v-1",
            createdAt: 42,
            durationMs: 1_840,
            mimeType: "audio/mp4"
        )
        XCTAssertEqual(WatchVoiceNoteMetadata(payload: metadata.encoded()), metadata)
        var payload = metadata.encoded()
        payload["durationMs"] = 0
        XCTAssertNil(WatchVoiceNoteMetadata(payload: payload))
    }

    // MARK: - Sprite manifest + frame layout

    private func canonicalManifest(
        framesByRow: [String: Int] = ["idle": 6, "running": 8]
    ) -> WatchSpriteManifest {
        WatchSpriteManifest(
            slug: "boba",
            displayName: "Boba",
            revision: "1:1",
            mime: "image/webp",
            frameW: 192,
            frameH: 208,
            framesPerState: 6,
            loopMs: 1_100,
            stateRows: ["idle", "running", "waiting"],
            framesByRow: framesByRow
        )
    }

    func testSpriteManifestRoundTripsAndBoundsItsGeometry() {
        let manifest = canonicalManifest()
        XCTAssertEqual(WatchSpriteManifest(payload: manifest.encoded()), manifest)

        var oversized = manifest.encoded()
        oversized["frameW"] = WatchSpriteManifest.maximumAtlasDimension
        XCTAssertNil(WatchSpriteManifest(payload: oversized))

        var invalid = manifest.encoded()
        invalid["loopMs"] = 0
        XCTAssertNil(WatchSpriteManifest(payload: invalid))
    }

    func testFrameLayoutResolvesDeclaredRowsAndAliases() throws {
        let manifest = canonicalManifest()
        // 8 columns x 3 rows of 192x208 frames.
        let layout = try XCTUnwrap(WatchSpriteFrameLayout.resolve(
            stateRaw: "run",
            manifest: manifest,
            atlasWidth: 192 * 8,
            atlasHeight: 208 * 3
        ))
        XCTAssertEqual(layout.rowIndex, 1)
        XCTAssertEqual(layout.frames, 8)
        XCTAssertEqual(layout.stepMilliseconds, 1_100 / 8)
    }

    func testFrameLayoutFallsBackToIdleForUndeclaredRows() throws {
        // `waiting` is a named row but declares no frames; the alias mapping
        // must retreat to idle rather than animating transparent padding.
        let layout = try XCTUnwrap(WatchSpriteFrameLayout.resolve(
            stateRaw: "waiting",
            manifest: canonicalManifest(),
            atlasWidth: 192 * 8,
            atlasHeight: 208 * 3
        ))
        XCTAssertEqual(layout.rowIndex, 0)
        XCTAssertEqual(layout.frames, 6)
    }

    func testFrameLayoutBoundsFramesByTheDecodedAtlas() throws {
        // The manifest may promise more frames than the decoded pixels hold;
        // the atlas is authoritative.
        let layout = try XCTUnwrap(WatchSpriteFrameLayout.resolve(
            stateRaw: "idle",
            manifest: canonicalManifest(framesByRow: [:]),
            atlasWidth: 192 * 3,
            atlasHeight: 208 * 3
        ))
        XCTAssertEqual(layout.frames, 3)
        XCTAssertNil(WatchSpriteFrameLayout.resolve(
            stateRaw: "run",
            manifest: canonicalManifest(),
            atlasWidth: 192 * 4, // running declares 8 frames; atlas holds 4
            atlasHeight: 208 * 3
        ))
    }

    func testFrameColumnCyclesThroughTheRow() {
        let layout = WatchSpriteFrameLayout(rowIndex: 0, frames: 6, stepMilliseconds: 183)
        XCTAssertEqual(layout.column(atMillisecond: 0), 0)
        XCTAssertEqual(layout.column(atMillisecond: 183), 1)
        XCTAssertEqual(layout.column(atMillisecond: 183 * 6), 0)
    }

    // MARK: - Pose vocabulary

    func testEveryPetStateMapsToARenderablePose() {
        // The vocabulary must stay total over the phone's pet states and
        // fail soft for unknown future states — invariants, not exact art.
        for state in [PetState.idle, .wave, .run, .failed, .review, .jump, .waiting] {
            let pose = WatchPetPose.pose(for: state.rawValue)
            XCTAssertFalse(pose.symbolName.isEmpty, "\(state) needs a symbol")
            XCTAssertFalse(pose.caption.isEmpty, "\(state) needs a caption")
        }
        XCTAssertTrue(WatchPetPose.pose(for: "waiting").isAttention)
        XCTAssertEqual(
            WatchPetPose.pose(for: "some-future-state").symbolName,
            WatchPetPose.pose(for: "idle").symbolName
        )
    }

    // MARK: - Widget snapshot

    func testWidgetSnapshotRoundTripsAndFailsClosedOnVersionDrift() {
        let context = WatchRelayContext(
            phase: "connected",
            gatewayLabel: "Studio Mac",
            petStateRaw: "waiting",
            petName: "Boba",
            petRevision: nil,
            petAvailable: true,
            updatedAt: 7
        )
        let decoded = WatchWidgetSnapshot.decode(WatchWidgetSnapshot.encode(context: context))
        XCTAssertEqual(decoded?.petStateRaw, "waiting")
        XCTAssertEqual(decoded?.petName, "Boba")
        XCTAssertEqual(decoded?.connected, true)
        XCTAssertEqual(decoded?.attention, true)
        XCTAssertEqual(decoded?.updatedAt, 7)

        var drifted = WatchWidgetSnapshot.encode(context: context)
        drifted[WatchRelayKey.version] = watchRelayProtocolVersion + 1
        XCTAssertNil(WatchWidgetSnapshot.decode(drifted))
        XCTAssertNil(WatchWidgetSnapshot.decode(nil))
    }
}
