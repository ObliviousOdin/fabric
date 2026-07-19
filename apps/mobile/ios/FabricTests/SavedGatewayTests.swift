import XCTest
@testable import Fabric

final class SavedGatewayTests: XCTestCase {
    override func tearDown() {
        UserDefaults.standard.removeObject(forKey: "fabric.gateways.v1")
        UserDefaults.standard.removeObject(forKey: "fabric.gateways.lastActive")
        super.tearDown()
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

    func testLibraryMigrationKeepsNewestDuplicateAndRepairsLastActive() throws {
        let older = SavedGateway(
            id: "older",
            label: "Old server",
            baseURL: try XCTUnwrap(URL(string: "http://example.com:80/")),
            authMode: .gated,
            username: "old"
        )
        let newer = SavedGateway(
            id: "newer",
            label: "Current server",
            baseURL: try XCTUnwrap(URL(string: "http://EXAMPLE.com")),
            authMode: .gated,
            username: "current"
        )
        UserDefaults.standard.set(
            try JSONEncoder().encode([older, newer]),
            forKey: "fabric.gateways.v1"
        )
        UserDefaults.standard.set(older.id, forKey: "fabric.gateways.lastActive")

        let migrated = GatewayStore.all()

        XCTAssertEqual(migrated, [newer])
        XCTAssertEqual(GatewayStore.lastActiveId(), newer.id)
    }
}
