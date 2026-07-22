import XCTest
@testable import Fabric

final class ConversationHomeSnapshotStoreTests: XCTestCase {
    private var directory: URL!

    override func setUp() {
        super.setUp()
        directory = FileManager.default.temporaryDirectory
            .appending(path: UUID().uuidString, directoryHint: .isDirectory)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: directory)
        super.tearDown()
    }

    func testRoundTripIsGatewayScopedAndBounded() throws {
        let store = ConversationHomeSnapshotStore(directoryURL: directory)
        let sessions = (0..<24).map {
            SessionSummary(
                id: "session-\($0)",
                title: "Session \($0)",
                preview: "Preview",
                startedAt: TimeInterval($0),
                messageCount: $0,
                source: "mobile"
            )
        }
        let snapshot = ConversationHomeSnapshot(
            gatewayID: "gateway-a",
            sessions: sessions,
            activeSessions: [],
            updatedAt: Date(timeIntervalSince1970: 1_000)
        )

        store.save(snapshot)

        let restored = try XCTUnwrap(store.load(
            gatewayID: "gateway-a",
            now: Date(timeIntervalSince1970: 1_100)
        ))
        XCTAssertEqual(restored.sessions.count, 16)
        XCTAssertEqual(restored.sessions.first?.id, "session-0")
        XCTAssertNil(store.load(
            gatewayID: "gateway-b",
            now: Date(timeIntervalSince1970: 1_100)
        ))
    }

    func testExpiredSnapshotFailsClosed() {
        let store = ConversationHomeSnapshotStore(directoryURL: directory)
        store.save(ConversationHomeSnapshot(
            gatewayID: "gateway-a",
            sessions: [],
            activeSessions: [],
            updatedAt: Date(timeIntervalSince1970: 1_000)
        ))

        XCTAssertNil(store.load(
            gatewayID: "gateway-a",
            now: Date(timeIntervalSince1970: 1_000 + 31 * 24 * 60 * 60)
        ))
    }

    func testSnapshotRequiresCompleteProtectionAndBackupExclusion() throws {
        let store = ConversationHomeSnapshotStore(directoryURL: directory)
        store.save(snapshot(gatewayID: "protected"))

        let file = store.snapshotURL(gatewayID: "protected")
        XCTAssertTrue(FileManager.default.fileExists(atPath: file.path))
        XCTAssertEqual(ConversationHomeSnapshotStore.requiredFileProtection, .complete)
        XCTAssertTrue(
            ConversationHomeSnapshotStore.hasRequiredFileProtection(FileProtectionType.complete)
        )
        XCTAssertFalse(
            ConversationHomeSnapshotStore.hasRequiredFileProtection(
                FileProtectionType.completeUntilFirstUserAuthentication
            )
        )
        XCTAssertFalse(ConversationHomeSnapshotStore.hasRequiredFileProtection(nil))

        let root = try XCTUnwrap(directory)
        for url in [root, file] {
            let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
            if let rawProtection = attributes[FileAttributeKey.protectionKey] {
                XCTAssertTrue(
                    ConversationHomeSnapshotStore.hasRequiredFileProtection(rawProtection)
                )
            }
            let values = try url.resourceValues(forKeys: [.isExcludedFromBackupKey])
            XCTAssertEqual(values.isExcludedFromBackup, true)
        }
    }

    func testSnapshotWithBackupEligibilityFailsClosedAndIsRemoved() throws {
        let store = ConversationHomeSnapshotStore(directoryURL: directory)
        store.save(snapshot(gatewayID: "weakened"))
        var file = store.snapshotURL(gatewayID: "weakened")
        var values = URLResourceValues()
        values.isExcludedFromBackup = false
        try file.setResourceValues(values)

        XCTAssertNil(store.load(gatewayID: "weakened"))
        XCTAssertFalse(FileManager.default.fileExists(atPath: file.path))
    }

    func testSnapshotDirectoryPrunesLeastRecentlyUsedGateway() throws {
        let store = ConversationHomeSnapshotStore(
            directoryURL: directory,
            policy: .init(
                maximumEncodedBytes: 32_768,
                maximumDirectoryBytes: 64_000,
                maximumSnapshots: 1,
                maximumAge: 3_600
            )
        )
        store.save(snapshot(gatewayID: "older"))
        let older = store.snapshotURL(gatewayID: "older")
        try FileManager.default.setAttributes(
            [.modificationDate: Date().addingTimeInterval(-30)],
            ofItemAtPath: older.path
        )

        store.save(snapshot(gatewayID: "newer"))

        XCTAssertFalse(FileManager.default.fileExists(atPath: older.path))
        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: store.snapshotURL(gatewayID: "newer").path
            )
        )
    }

    private func snapshot(gatewayID: String) -> ConversationHomeSnapshot {
        ConversationHomeSnapshot(
            gatewayID: gatewayID,
            sessions: [
                SessionSummary(
                    id: "session-\(gatewayID)",
                    title: "Protected session",
                    preview: "Presentation only",
                    startedAt: 1_000,
                    messageCount: 2,
                    source: "mobile"
                ),
            ],
            activeSessions: [],
            updatedAt: Date()
        )
    }
}
