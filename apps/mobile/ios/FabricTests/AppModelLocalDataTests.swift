import Foundation
import Security
import XCTest
@testable import Fabric

final class AppModelLocalDataTests: XCTestCase {
    override func setUp() {
        super.setUp()
        resetStoreForTestIsolation()
        GatewayAPI.clearAllAuthSessions()
    }

    override func tearDown() {
        GatewayAPI.clearAllAuthSessions()
        resetStoreForTestIsolation()
        super.tearDown()
    }

    private func resetStoreForTestIsolation() {
        do {
            try GatewayStore.removeAll()
        } catch {
            try? GatewayStore.removeAll(deleteCredentialService: { errSecItemNotFound })
        }
    }

    func testPresentationCacheStoreRemovesOnlyConfiguredDeviceDirectories() throws {
        let fileManager = FileManager.default
        let root = fileManager.temporaryDirectory
            .appending(path: "fabric-presentation-clear-\(UUID().uuidString)", directoryHint: .isDirectory)
        let cache = root.appending(path: "Fabric", directoryHint: .isDirectory)
        let unrelated = root.appending(path: "SavedServerMetadata", directoryHint: .notDirectory)
        defer { try? fileManager.removeItem(at: root) }

        try fileManager.createDirectory(at: cache, withIntermediateDirectories: true)
        try Data("presentation only".utf8).write(
            to: cache.appending(path: "snapshot.json", directoryHint: .notDirectory)
        )
        try Data("keep".utf8).write(to: unrelated)

        try DevicePresentationCacheStore(
            directoryURLs: [cache],
            fileManager: fileManager
        ).removeAll()

        XCTAssertFalse(fileManager.fileExists(atPath: cache.path))
        XCTAssertTrue(fileManager.fileExists(atPath: unrelated.path))
    }

    @MainActor
    func testClearCachedPresentationDataPreservesSavedServerMetadata() throws {
        let gateway = try savedGateway(id: "cache-preserves-server")
        GatewayStore.upsert(gateway)
        let cache = temporaryCacheDirectory()
        defer { try? FileManager.default.removeItem(at: cache.deletingLastPathComponent()) }
        try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
        try Data("cached".utf8).write(to: cache.appending(path: "home.json"))
        let model = AppModel(
            presentationCacheStore: DevicePresentationCacheStore(directoryURLs: [cache])
        )

        try model.clearCachedPresentationData()

        XCTAssertEqual(model.gateways, [gateway])
        XCTAssertEqual(GatewayStore.all(), [gateway])
        XCTAssertFalse(FileManager.default.fileExists(atPath: cache.path))
    }

    @MainActor
    func testResetFailureDoesNotPublishAnEmptyServerLibrary() throws {
        let gateway = try savedGateway(id: "reset-failure-server")
        GatewayStore.upsert(gateway)
        let model = AppModel(
            presentationCacheStore: DevicePresentationCacheStore(directoryURLs: []),
            resetGatewayStore: {
                throw GatewayStoreError.credentialRemovalUnavailable
            }
        )

        XCTAssertThrowsError(try model.resetLocalAppData()) { error in
            XCTAssertEqual(error as? AppLocalDataError, .fullResetUnavailable)
        }

        XCTAssertEqual(model.gateways, [gateway])
        XCTAssertEqual(GatewayStore.all(), [gateway])
        guard case .disconnected = model.phase else {
            return XCTFail("A failed local reset must leave the client disconnected.")
        }
    }

    @MainActor
    func testResetPublishesCompletionOnlyAfterCredentialCleanupSucceeds() throws {
        let gateway = try savedGateway(id: "reset-success-server")
        GatewayStore.upsert(gateway)
        var credentialCleanupFinished = false
        let model = AppModel(
            presentationCacheStore: DevicePresentationCacheStore(directoryURLs: []),
            resetGatewayStore: {
                try GatewayStore.removeAll(deleteCredentialService: { errSecItemNotFound })
                credentialCleanupFinished = true
            }
        )

        try model.resetLocalAppData()

        XCTAssertTrue(credentialCleanupFinished)
        XCTAssertTrue(model.gateways.isEmpty)
        XCTAssertTrue(GatewayStore.all().isEmpty)
    }

    @MainActor
    func testForgetFailurePreservesServerAndEphemeralGatedSession() throws {
        let gateway = try savedGateway(id: "forget-model-failure")
        GatewayStore.upsert(gateway)
        let (cookie, authSession) = try installTestCookie(for: gateway)
        let model = AppModel(
            presentationCacheStore: DevicePresentationCacheStore(directoryURLs: []),
            removeGatewayFromStore: { _ in
                throw GatewayStoreError.credentialRemovalUnavailable
            }
        )
        model.installConnectionStateForTesting(
            gatewayID: gateway.id,
            phase: .connected
        )

        XCTAssertThrowsError(try model.removeGateway(id: gateway.id)) { error in
            XCTAssertEqual(error as? AppLocalDataError, .forgetGatewayUnavailable)
            XCTAssertEqual(
                error.localizedDescription,
                "Fabric couldn't remove the saved credential, so this server is still saved on this iPhone. Unlock the device and try again."
            )
        }

        XCTAssertEqual(model.gateways, [gateway])
        XCTAssertEqual(GatewayStore.all(), [gateway])
        XCTAssertEqual(model.activeGatewayId, gateway.id)
        guard case .connected = model.phase else {
            return XCTFail("A credential deletion failure must not disconnect the active server.")
        }
        XCTAssertTrue(GatewayAPI.isAuthSessionCurrent(authSession, for: gateway))
        XCTAssertTrue(cookieIsPresent(cookie, in: authSession))
    }

    @MainActor
    func testSuccessfulGatedForgetClearsOnlyThatGatewaySession() throws {
        let gateway = try savedGateway(id: "forget-model-success")
        let otherGateway = try savedGateway(
            id: "forget-model-keep",
            urlString: "https://studio.example.test:9443"
        )
        GatewayStore.upsert(gateway)
        GatewayStore.upsert(otherGateway)
        let (cookie, authSession) = try installTestCookie(for: gateway)
        let (otherCookie, otherAuthSession) = try installTestCookie(for: otherGateway)
        let model = AppModel(
            presentationCacheStore: DevicePresentationCacheStore(directoryURLs: []),
            removeGatewayFromStore: { id in
                try GatewayStore.remove(
                    id: id,
                    deleteCredential: { errSecItemNotFound }
                )
            }
        )

        try model.removeGateway(id: gateway.id)

        XCTAssertEqual(model.gateways, [otherGateway])
        XCTAssertEqual(GatewayStore.all(), [otherGateway])
        XCTAssertFalse(GatewayAPI.isAuthSessionCurrent(authSession, for: gateway))
        XCTAssertFalse(cookieIsPresent(cookie, in: authSession))
        XCTAssertTrue(GatewayAPI.isAuthSessionCurrent(otherAuthSession, for: otherGateway))
        XCTAssertTrue(cookieIsPresent(otherCookie, in: otherAuthSession))
    }

    func testAuthSessionsIsolateSameHostEndpointsWithDifferentPorts() throws {
        let first = try savedGateway(
            id: "cookie-origin-first",
            urlString: "https://studio.example.test:8443"
        )
        let second = try savedGateway(
            id: "cookie-origin-second",
            urlString: "https://studio.example.test:9443"
        )
        let (cookie, firstSession) = try installTestCookie(for: first)
        let secondSession = GatewayAPI.beginAuthSession(
            for: second,
            preservingExistingCookies: true
        )

        let firstStorage = try XCTUnwrap(firstSession.session.configuration.httpCookieStorage)
        let secondStorage = try XCTUnwrap(secondSession.session.configuration.httpCookieStorage)

        XCTAssertFalse(firstStorage === secondStorage)
        // RFC cookie matching ignores ports: this cookie would be eligible for
        // the second URL if both gateways shared one jar.
        XCTAssertTrue(firstStorage.cookies(for: second.baseURL)?.contains(cookie) == true)
        XCTAssertFalse(secondStorage.cookies(for: second.baseURL)?.contains(cookie) == true)
    }

    func testSupersededAuthGenerationCannotMutateReplacementJar() throws {
        let gateway = try savedGateway(id: "cookie-generation")
        let (cookie, firstSession) = try installTestCookie(for: gateway)

        let replacement = GatewayAPI.beginAuthSession(
            for: gateway,
            preservingExistingCookies: true
        )

        XCTAssertFalse(GatewayAPI.isAuthSessionCurrent(firstSession, for: gateway))
        XCTAssertTrue(GatewayAPI.isAuthSessionCurrent(replacement, for: gateway))
        XCTAssertTrue(cookieIsPresent(cookie, in: replacement))

        let lateCookie = try makeTestCookie(
            name: "fabric-late-superseded-session",
            domain: gateway.baseURL.host() ?? "studio.example.test"
        )
        firstSession.session.configuration.httpCookieStorage?.setCookie(lateCookie)
        XCTAssertFalse(cookieIsPresent(lateCookie, in: replacement))

        let freshPasswordSession = GatewayAPI.beginAuthSession(
            for: gateway,
            preservingExistingCookies: false
        )
        XCTAssertFalse(cookieIsPresent(cookie, in: freshPasswordSession))
        XCTAssertFalse(GatewayAPI.isAuthSessionCurrent(replacement, for: gateway))
        XCTAssertTrue(GatewayAPI.isAuthSessionCurrent(freshPasswordSession, for: gateway))
    }

    @MainActor
    func testDisconnectInvalidatesOnlyActiveGatewayAuthSession() throws {
        let active = try savedGateway(id: "disconnect-active")
        let inactive = try savedGateway(
            id: "disconnect-inactive",
            urlString: "https://studio.example.test:9443"
        )
        GatewayStore.upsert(active)
        GatewayStore.upsert(inactive)
        let (_, activeSession) = try installTestCookie(for: active)
        let (inactiveCookie, inactiveSession) = try installTestCookie(for: inactive)
        let model = AppModel(presentationCacheStore: DevicePresentationCacheStore(directoryURLs: []))
        model.installConnectionStateForTesting(gatewayID: active.id, phase: .connected)

        model.disconnect()

        XCTAssertFalse(GatewayAPI.isAuthSessionCurrent(activeSession, for: active))
        XCTAssertTrue(GatewayAPI.isAuthSessionCurrent(inactiveSession, for: inactive))
        XCTAssertTrue(cookieIsPresent(inactiveCookie, in: inactiveSession))
    }

    @MainActor
    func testFullResetInvalidatesEveryGatewayAuthSession() throws {
        let first = try savedGateway(id: "reset-cookie-first")
        let second = try savedGateway(
            id: "reset-cookie-second",
            urlString: "https://studio.example.test:9443"
        )
        GatewayStore.upsert(first)
        GatewayStore.upsert(second)
        let (_, firstSession) = try installTestCookie(for: first)
        let (_, secondSession) = try installTestCookie(for: second)
        let model = AppModel(
            presentationCacheStore: DevicePresentationCacheStore(directoryURLs: []),
            resetGatewayStore: {
                try GatewayStore.removeAll(deleteCredentialService: { errSecItemNotFound })
            }
        )

        try model.resetLocalAppData()

        XCTAssertFalse(GatewayAPI.isAuthSessionCurrent(firstSession, for: first))
        XCTAssertFalse(GatewayAPI.isAuthSessionCurrent(secondSession, for: second))
    }

    @MainActor
    func testUserConnectFailsClosedForUpgradedPlaintextTokenGateway() async throws {
        let gateway = SavedGateway(
            id: "legacy-user-connect",
            label: "Old LAN gateway",
            baseURL: try XCTUnwrap(URL(string: "http://192.168.1.20:9119")),
            authMode: .token
        )
        GatewayStore.upsert(gateway)
        let model = AppModel(
            presentationCacheStore: DevicePresentationCacheStore(directoryURLs: [])
        )

        await model.connectToken(gateway)

        XCTAssertEqual(
            model.lastConnectError,
            GatewayTokenTransportError.secureTransportRequired.localizedDescription
        )
        XCTAssertEqual(model.gateways, [gateway], "The row stays visible so the user can re-pair or forget it.")
        XCTAssertNil(model.activeGatewayId)
        guard case .disconnected = model.phase else {
            return XCTFail("Rejected plaintext token must not start a connection attempt.")
        }
    }

    @MainActor
    func testAutomaticReconnectFailsClosedForUpgradedPlaintextTokenGateway() async throws {
        let gateway = SavedGateway(
            id: "legacy-auto-reconnect",
            label: "Old LAN gateway",
            baseURL: try XCTUnwrap(URL(string: "http://192.168.1.20:9119")),
            authMode: .token
        )
        GatewayStore.upsert(gateway)
        let model = AppModel(
            presentationCacheStore: DevicePresentationCacheStore(directoryURLs: [])
        )
        model.installConnectionStateForTesting(gatewayID: gateway.id, phase: .reconnecting)

        await model.reconnectActiveGatewayForTesting()

        XCTAssertEqual(
            model.lastConnectError,
            GatewayTokenTransportError.secureTransportRequired.localizedDescription
        )
        XCTAssertEqual(model.activeGatewayId, gateway.id, "Recovery keeps the exact saved row selected.")
        guard case .disconnected = model.phase else {
            return XCTFail("Automatic reconnect must stop before reading or transporting a token.")
        }
    }

    private func savedGateway(
        id: String,
        urlString: String = "https://studio.example.test"
    ) throws -> SavedGateway {
        SavedGateway(
            id: id,
            label: "Studio Mac",
            baseURL: try XCTUnwrap(URL(string: urlString)),
            authMode: .gated
        )
    }

    private func temporaryCacheDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appending(path: "fabric-model-cache-\(UUID().uuidString)", directoryHint: .isDirectory)
            .appending(path: "Fabric", directoryHint: .isDirectory)
    }

    private func installTestCookie(
        for gateway: SavedGateway
    ) throws -> (HTTPCookie, GatewayAuthSessionLease) {
        let cookie = try makeTestCookie(
            name: "fabric-test-session-\(gateway.id)",
            domain: gateway.baseURL.host() ?? "studio.example.test"
        )
        let authSession = GatewayAPI.beginAuthSession(
            for: gateway,
            preservingExistingCookies: true
        )
        let storage = try XCTUnwrap(authSession.session.configuration.httpCookieStorage)
        storage.setCookie(cookie)
        XCTAssertTrue(cookieIsPresent(cookie, in: authSession))
        return (cookie, authSession)
    }

    private func makeTestCookie(name: String, domain: String) throws -> HTTPCookie {
        try XCTUnwrap(HTTPCookie(properties: [
            .domain: domain,
            .path: "/",
            .name: name,
            .value: "disposable-test-value",
            .secure: "TRUE",
            .expires: Date().addingTimeInterval(300),
        ]))
    }

    private func cookieIsPresent(
        _ expected: HTTPCookie,
        in authSession: GatewayAuthSessionLease
    ) -> Bool {
        authSession.session.configuration.httpCookieStorage?.cookies?.contains {
            $0.name == expected.name
                && $0.domain == expected.domain
                && $0.value == expected.value
        } ?? false
    }
}
