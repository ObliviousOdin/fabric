import Security
import XCTest
@testable import Fabric

final class SavedGatewayTests: XCTestCase {
    override func setUp() {
        super.setUp()
        resetStoreForTestIsolation()
    }

    override func tearDown() {
        resetStoreForTestIsolation()
        super.tearDown()
    }

    private func resetStoreForTestIsolation() {
        do {
            try GatewayStore.removeAll()
        } catch {
            // Unsigned runners can deny Security.framework access. Tests that
            // inject those statuses still need isolated metadata assertions.
            try? GatewayStore.removeAll(deleteCredentialService: { errSecItemNotFound })
        }
    }

    func testEndpointKeyNormalizesCosmeticURLDifferences() throws {
        let canonical = try XCTUnwrap(URL(string: "http://example.com"))
        let cosmetic = try XCTUnwrap(URL(string: "HTTP://Example.COM:80/"))

        XCTAssertEqual(
            SavedGateway.endpointKey(for: canonical),
            SavedGateway.endpointKey(for: cosmetic)
        )
    }

    func testEndpointKeyPreservesPathAndNonDefaultPort() throws {
        let first = try XCTUnwrap(URL(string: "https://example.com:8443/fabric/"))
        let same = try XCTUnwrap(URL(string: "https://EXAMPLE.com:8443/fabric"))
        let differentPort = try XCTUnwrap(URL(string: "https://example.com:9443/fabric"))

        XCTAssertEqual(
            SavedGateway.endpointKey(for: first),
            SavedGateway.endpointKey(for: same)
        )
        XCTAssertNotEqual(
            SavedGateway.endpointKey(for: first),
            SavedGateway.endpointKey(for: differentPort)
        )
    }

    func testUpsertKeepsOneCurrentRowPerEndpointAndRepairsLastActive() throws {
        let first = SavedGateway(
            id: "first",
            label: "First server",
            baseURL: try XCTUnwrap(URL(string: "http://example.com:80/")),
            authMode: .gated,
            username: "first"
        )
        let replacement = SavedGateway(
            id: "replacement",
            label: "Current server",
            baseURL: try XCTUnwrap(URL(string: "http://EXAMPLE.com")),
            authMode: .gated,
            username: "current"
        )

        GatewayStore.upsert(first)
        GatewayStore.setLastActive(first.id)
        let stored = GatewayStore.upsert(replacement)

        XCTAssertEqual(stored, [replacement])
        XCTAssertEqual(GatewayStore.lastActiveId(), replacement.id)
    }

    func testTokenUpsertPersistsOrFailsWithoutPublishingMetadata() throws {
        let gateway = SavedGateway(
            id: "pairing-boundary-token",
            label: "Pairing boundary",
            baseURL: try XCTUnwrap(URL(string: "https://agent.example.test")),
            authMode: .token
        )
        let credential = "one-time-pairing-credential"

        do {
            _ = try GatewayStore.upsert(gateway, token: credential)

            XCTAssertEqual(GatewayStore.token(id: gateway.id), credential)
            XCTAssertTrue(GatewayStore.canAutoConnect(gateway))

            try GatewayStore.remove(id: gateway.id)
            XCTAssertNil(GatewayStore.token(id: gateway.id))
        } catch GatewayStoreError.credentialStorageUnavailable {
            // Unsigned simulator runners may deny Keychain writes. The safety
            // contract in that environment is fail-closed: no metadata row may
            // advertise a credential that was not protected.
            XCTAssertFalse(GatewayStore.all().contains { $0.id == gateway.id })
            XCTAssertNil(GatewayStore.token(id: gateway.id))
        }
    }

    func testLegacyPlaintextTokenCannotAutoConnectEvenWhenCredentialExists() throws {
        let gateway = SavedGateway(
            id: "legacy-plaintext-token",
            label: "Old LAN gateway",
            baseURL: try XCTUnwrap(URL(string: "http://192.168.1.20:9119")),
            authMode: .token
        )
        var requestedCredentialID: String?

        XCTAssertFalse(GatewayStore.canAutoConnect(gateway) { id in
            requestedCredentialID = id
            return "still-present-upgrade-token"
        })
        XCTAssertNil(requestedCredentialID, "Unsafe transport must fail before reading Keychain.")
    }

    func testPlaintextRemoteTokenCannotBePersisted() throws {
        let gateway = SavedGateway(
            id: "reject-plaintext-token",
            label: "Unsafe LAN gateway",
            baseURL: try XCTUnwrap(URL(string: "http://192.168.1.20:9119")),
            authMode: .token
        )

        XCTAssertThrowsError(try GatewayStore.upsert(gateway, token: "must-not-be-saved")) { error in
            XCTAssertEqual(error as? GatewayTokenTransportError, .secureTransportRequired)
            XCTAssertFalse(error.localizedDescription.contains("must-not-be-saved"))
        }
        XCTAssertFalse(GatewayStore.all().contains { $0.id == gateway.id })
        XCTAssertNil(GatewayStore.token(id: gateway.id))
    }

    func testKeptPasswordPersistsAndIsRemovedWithItsGateway() throws {
        let gateway = SavedGateway(
            id: "kept-password",
            label: "Gated server",
            baseURL: try XCTUnwrap(URL(string: "https://gated.example.test")),
            authMode: .gated,
            username: "odin"
        )
        GatewayStore.upsert(gateway)

        do {
            try GatewayStore.savePassword("kept-sign-in-secret", for: gateway)
        } catch GatewayStoreError.credentialStorageUnavailable {
            throw XCTSkip("This unsigned simulator runner does not permit Keychain writes.")
        }

        XCTAssertEqual(GatewayStore.password(id: gateway.id), "kept-sign-in-secret")
        XCTAssertTrue(GatewayStore.hasStoredPassword(gateway))

        try GatewayStore.remove(id: gateway.id)
        XCTAssertNil(GatewayStore.password(id: gateway.id))
        XCTAssertFalse(GatewayStore.hasStoredPassword(gateway))
    }

    func testKeptPasswordRequiresSecureTransport() throws {
        let gateway = SavedGateway(
            id: "insecure-password",
            label: "Plain HTTP gateway",
            baseURL: try XCTUnwrap(URL(string: "http://192.168.1.20:9119")),
            authMode: .gated,
            username: "odin"
        )
        var requestedCredentialID: String?

        XCTAssertThrowsError(
            try GatewayStore.savePassword("must-not-be-saved", for: gateway)
        ) { error in
            XCTAssertEqual(error as? GatewayTokenTransportError, .secureTransportRequired)
            XCTAssertFalse(error.localizedDescription.contains("must-not-be-saved"))
        }
        XCTAssertFalse(GatewayStore.hasStoredPassword(gateway) { id in
            requestedCredentialID = id
            return "still-present-password"
        })
        XCTAssertNil(requestedCredentialID, "Unsafe transport must fail before reading Keychain.")
    }

    func testTokenModeGatewayNeverAdvertisesAKeptPassword() throws {
        let gateway = SavedGateway(
            id: "token-no-password",
            label: "Token server",
            baseURL: try XCTUnwrap(URL(string: "https://token.example.test")),
            authMode: .token
        )

        XCTAssertFalse(GatewayStore.hasStoredPassword(gateway) { _ in "orphan-password" })
    }

    func testSwitchingToTokenAuthDropsTheKeptPassword() throws {
        let baseURL = try XCTUnwrap(URL(string: "https://switching.example.test"))
        let gated = SavedGateway(
            id: "auth-switch",
            label: "Was gated",
            baseURL: baseURL,
            authMode: .gated,
            username: "odin"
        )
        GatewayStore.upsert(gated)
        do {
            try GatewayStore.savePassword("gated-era-secret", for: gated)
        } catch GatewayStoreError.credentialStorageUnavailable {
            throw XCTSkip("This unsigned simulator runner does not permit Keychain writes.")
        }

        let token = SavedGateway(
            id: "auth-switch",
            label: "Now token",
            baseURL: baseURL,
            authMode: .token
        )
        _ = try GatewayStore.upsert(token, token: "fresh-session-token")

        XCTAssertNil(GatewayStore.password(id: token.id))
        XCTAssertEqual(GatewayStore.token(id: token.id), "fresh-session-token")
    }

    func testFullResetRemovesOrphanTokenWhenGatewayMetadataIsCorrupt() throws {
        let gateway = SavedGateway(
            id: "orphan-token-\(UUID().uuidString)",
            label: "Orphan boundary",
            baseURL: try XCTUnwrap(URL(string: "https://orphan.example.test")),
            authMode: .token
        )

        do {
            _ = try GatewayStore.upsert(gateway, token: "orphan-test-credential")
        } catch GatewayStoreError.credentialStorageUnavailable {
            throw XCTSkip("This unsigned simulator runner does not permit Keychain writes.")
        }
        XCTAssertNotNil(GatewayStore.token(id: gateway.id))

        // Simulate an interrupted/older install whose metadata cannot be
        // decoded. A metadata-derived cleanup would silently orphan the token.
        UserDefaults.standard.set(
            Data("not valid gateway json".utf8),
            forKey: "fabric.gateways.v1"
        )
        XCTAssertTrue(GatewayStore.all().isEmpty)

        try GatewayStore.removeAll()

        XCTAssertNil(GatewayStore.token(id: gateway.id))
    }

    func testFullResetKeepsMetadataAndSurfacesCredentialDeletionFailure() throws {
        let gateway = SavedGateway(
            id: "delete-failure",
            label: "Keep until verified",
            baseURL: try XCTUnwrap(URL(string: "https://keep.example.test")),
            authMode: .gated
        )
        GatewayStore.upsert(gateway)
        GatewayStore.setLastActive(gateway.id)

        XCTAssertThrowsError(
            try GatewayStore.removeAll(deleteCredentialService: { errSecInteractionNotAllowed })
        ) { error in
            XCTAssertEqual(
                error as? GatewayStoreError,
                .credentialRemovalUnavailable
            )
        }
        XCTAssertEqual(GatewayStore.all(), [gateway])
        XCTAssertEqual(GatewayStore.lastActiveId(), gateway.id)
    }

    func testFullResetTreatsAlreadyEmptyCredentialServiceAsSuccess() throws {
        let gateway = SavedGateway(
            id: "already-empty",
            label: "Metadata only",
            baseURL: try XCTUnwrap(URL(string: "https://empty.example.test")),
            authMode: .gated
        )
        GatewayStore.upsert(gateway)

        try GatewayStore.removeAll(deleteCredentialService: { errSecItemNotFound })

        XCTAssertTrue(GatewayStore.all().isEmpty)
        XCTAssertNil(GatewayStore.lastActiveId())
    }

    func testForgetFailurePreservesEverySavedGatewayRecord() throws {
        let gateway = SavedGateway(
            id: "forget-failure",
            label: "Keep until credential deletion succeeds",
            baseURL: try XCTUnwrap(URL(string: "https://forget.example.test")),
            authMode: .token
        )
        GatewayStore.upsert(gateway)
        GatewayStore.setLastActive(gateway.id)
        GatewayStore.setCompletedConnectionIntro(true, id: gateway.id)

        XCTAssertThrowsError(
            try GatewayStore.remove(
                id: gateway.id,
                deleteCredential: { errSecInteractionNotAllowed }
            )
        ) { error in
            XCTAssertEqual(error as? GatewayStoreError, .credentialRemovalUnavailable)
        }

        XCTAssertEqual(GatewayStore.all(), [gateway])
        XCTAssertEqual(GatewayStore.lastActiveId(), gateway.id)
        XCTAssertTrue(GatewayStore.hasCompletedConnectionIntro(id: gateway.id))
    }

    func testForgetTreatsMissingCredentialAsAlreadyRemoved() throws {
        let gateway = SavedGateway(
            id: "forget-already-empty",
            label: "No credential remains",
            baseURL: try XCTUnwrap(URL(string: "https://forgotten.example.test")),
            authMode: .gated
        )
        GatewayStore.upsert(gateway)
        GatewayStore.setLastActive(gateway.id)
        GatewayStore.setCompletedConnectionIntro(true, id: gateway.id)

        try GatewayStore.remove(
            id: gateway.id,
            deleteCredential: { errSecItemNotFound }
        )

        XCTAssertTrue(GatewayStore.all().isEmpty)
        XCTAssertNil(GatewayStore.lastActiveId())
        XCTAssertFalse(GatewayStore.hasCompletedConnectionIntro(id: gateway.id))
    }
}
