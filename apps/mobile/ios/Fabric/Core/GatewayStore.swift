import Foundation
import Security

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
        return list
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

    /// Insert or update by id, then persist. Returns the stored list.
    @discardableResult
    static func upsert(_ gateway: SavedGateway, token: String? = nil) -> [SavedGateway] {
        var list = all()
        if let index = list.firstIndex(where: { $0.id == gateway.id }) {
            list[index] = gateway
        } else {
            list.append(gateway)
        }
        persist(list)
        if let token {
            saveToken(token, id: gateway.id)
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

    private static func saveToken(_ token: String, id: String) {
        let data = Data(token.utf8)
        var addQuery = tokenQuery(id: id)
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        if SecItemAdd(addQuery as CFDictionary, nil) == errSecDuplicateItem {
            SecItemUpdate(
                tokenQuery(id: id) as CFDictionary,
                [kSecValueData as String: data] as CFDictionary
            )
        }
    }

    private static func deleteToken(id: String) {
        SecItemDelete(tokenQuery(id: id) as CFDictionary)
    }
}
