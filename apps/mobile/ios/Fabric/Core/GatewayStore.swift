import Foundation
import Security

enum GatewayStoreError: LocalizedError {
    case credentialStorageUnavailable

    var errorDescription: String? {
        "Couldn't protect this server credential. Unlock the device and try again."
    }
}

/// How the app authenticates to a gateway.
enum GatewayAuthMode: String, Codable {
    /// Loopback/tunnel deployments: the session token is the credential.
    case token
    /// Non-loopback binds: provider login (password/OAuth) + WS tickets.
    case gated
}

/// One saved Fabric server in the library. Metadata is JSON in UserDefaults;
/// the token (token mode) lives in the Keychain keyed by `id`. Passwords are
/// never stored — a gated server auto-logs-in only while its cookie session
/// is alive, otherwise the user re-enters the password.
struct SavedGateway: Identifiable, Codable, Equatable {
    let id: String
    var label: String
    var baseURL: URL
    var authMode: GatewayAuthMode
    var username: String

    init(
        id: String = UUID().uuidString,
        label: String,
        baseURL: URL,
        authMode: GatewayAuthMode,
        username: String = ""
    ) {
        self.id = id
        self.label = label
        self.baseURL = baseURL
        self.authMode = authMode
        self.username = username
    }

    /// A human label from the URL when the user didn't name the server —
    /// "odin.tail1234.ts.net" reads better than the full URL in a list.
    static func defaultLabel(for url: URL) -> String {
        url.host() ?? url.absoluteString
    }

    /// Stable identity for a server regardless of cosmetic URL differences.
    /// Pairing the same endpoint again updates its saved row instead of adding
    /// a confusing duplicate with stale credentials.
    static func endpointKey(for url: URL) -> String {
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        }
        components.scheme = components.scheme?.lowercased()
        components.host = components.host?.lowercased()
        components.user = nil
        components.password = nil
        components.query = nil
        components.fragment = nil
        if (components.scheme == "http" && components.port == 80)
            || (components.scheme == "https" && components.port == 443) {
            components.port = nil
        }
        while components.path.count > 1, components.path.hasSuffix("/") {
            components.path.removeLast()
        }
        if components.path == "/" { components.path = "" }
        return components.string ?? url.absoluteString
    }

    var endpointKey: String { Self.endpointKey(for: baseURL) }
}

/// The saved-server library: an ordered list plus the id last connected to.
/// Replaces the single-record store — the app can hold many Fabric servers
/// and switch between them.
enum GatewayStore {
    private static let listKey = "fabric.gateways.v1"
    private static let lastActiveKey = "fabric.gateways.lastActive"
    private static let keychainService = "io.github.obliviousodin.fabric.mobile"

    // MARK: - Library

    static func all() -> [SavedGateway] {
        guard
            let data = UserDefaults.standard.data(forKey: listKey),
            let list = try? JSONDecoder().decode([SavedGateway].self, from: data)
        else { return [] }

        // Older builds appended a new row on every scan. Keep the newest row
        // per endpoint and migrate the library in place so stale duplicates do
        // not keep sending the user to an obsolete auth record.
        var seenEndpoints = Set<String>()
        let deduplicated = Array(list.reversed().filter {
            seenEndpoints.insert($0.endpointKey).inserted
        }.reversed())
        guard deduplicated.count != list.count else { return list }

        let keptIDs = Set(deduplicated.map(\.id))
        let removed = list.filter { !keptIDs.contains($0.id) }
        persist(deduplicated)
        for gateway in removed { deleteToken(id: gateway.id) }
        if let lastActive = lastActiveId(),
           let removedActive = removed.first(where: { $0.id == lastActive }),
           let replacement = deduplicated.first(where: { $0.endpointKey == removedActive.endpointKey }) {
            setLastActive(replacement.id)
        }
        return deduplicated
    }

    static func lastActiveId() -> String? {
        UserDefaults.standard.string(forKey: lastActiveKey)
    }

    static func setLastActive(_ id: String?) {
        if let id {
            UserDefaults.standard.set(id, forKey: lastActiveKey)
        } else {
            UserDefaults.standard.removeObject(forKey: lastActiveKey)
        }
    }

    /// Insert or update non-secret metadata, then persist it.
    @discardableResult
    static func upsert(_ gateway: SavedGateway) -> [SavedGateway] {
        upsertMetadata(gateway, deleteCurrentToken: gateway.authMode == .gated)
    }

    /// Protect a token before publishing metadata that makes the server appear
    /// auto-connectable. Keychain failure leaves no partially saved server.
    @discardableResult
    static func upsert(_ gateway: SavedGateway, token: String) throws -> [SavedGateway] {
        try saveToken(token, id: gateway.id)
        return upsertMetadata(gateway, deleteCurrentToken: false)
    }

    private static func upsertMetadata(
        _ gateway: SavedGateway,
        deleteCurrentToken: Bool
    ) -> [SavedGateway] {
        var list = all()
        if let index = list.firstIndex(where: { $0.id == gateway.id }) {
            list[index] = gateway
        } else {
            list.append(gateway)
        }
        let duplicateIDs = list
            .filter { $0.id != gateway.id && $0.endpointKey == gateway.endpointKey }
            .map(\.id)
        list.removeAll { duplicateIDs.contains($0.id) }
        persist(list)
        for id in duplicateIDs { deleteToken(id: id) }
        if let lastActive = lastActiveId(), duplicateIDs.contains(lastActive) {
            setLastActive(gateway.id)
        }
        if deleteCurrentToken {
            deleteToken(id: gateway.id)
        }
        return list
    }

    static func remove(id: String) {
        persist(all().filter { $0.id != id })
        deleteToken(id: id)
        if lastActiveId() == id { setLastActive(nil) }
    }

    static func token(id: String) -> String? {
        loadToken(id: id)
    }

    /// A token-mode server with a stored token can reconnect with no prompt.
    /// (Gated servers are checked at connect time against the live cookie
    /// session, so readiness there can't be answered synchronously here.)
    static func canAutoConnect(_ gateway: SavedGateway) -> Bool {
        gateway.authMode == .token && !(loadToken(id: gateway.id) ?? "").isEmpty
    }

    private static func persist(_ list: [SavedGateway]) {
        if let data = try? JSONEncoder().encode(list) {
            UserDefaults.standard.set(data, forKey: listKey)
        }
    }

    // MARK: - Keychain (one token entry per gateway id)

    private static func tokenQuery(id: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: "gateway-token-\(id)",
        ]
    }

    private static func loadToken(id: String) -> String? {
        var query = tokenQuery(id: id)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func saveToken(_ token: String, id: String) throws {
        let data = Data(token.utf8)
        var addQuery = tokenQuery(id: id)
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        let status: OSStatus
        if addStatus == errSecDuplicateItem {
            status = SecItemUpdate(
                tokenQuery(id: id) as CFDictionary,
                [
                    kSecValueData as String: data,
                    kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                ] as CFDictionary
            )
        } else {
            status = addStatus
        }
        guard status == errSecSuccess else {
            throw GatewayStoreError.credentialStorageUnavailable
        }
    }

    private static func deleteToken(id: String) {
        SecItemDelete(tokenQuery(id: id) as CFDictionary)
    }
}
