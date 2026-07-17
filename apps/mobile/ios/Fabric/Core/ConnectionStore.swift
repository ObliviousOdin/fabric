import Foundation
import Security

/// How the app authenticates to a gateway.
enum GatewayAuthMode: String {
    /// Loopback/tunnel deployments: the session token is the credential.
    case token
    /// Non-loopback binds: provider login (password/OAuth) + WS tickets.
    case gated
}

/// Persisted connection settings: the gateway base URL, auth mode, and
/// username live in UserDefaults (not secret); the session token in the
/// Keychain. Passwords are never persisted — gated sessions ride the
/// cookie store, and the user re-enters the password when it dies.
struct ConnectionSettings: Equatable {
    var baseURL: URL
    var token: String
    var authMode: GatewayAuthMode = .token
    var username: String = ""
}

enum ConnectionStore {
    private static let urlDefaultsKey = "fabric.gateway.baseURL"
    private static let authModeDefaultsKey = "fabric.gateway.authMode"
    private static let usernameDefaultsKey = "fabric.gateway.username"
    private static let keychainService = "io.github.obliviousodin.fabric.mobile"
    private static let keychainAccount = "gateway-session-token"

    static func load() -> ConnectionSettings? {
        guard
            let urlString = UserDefaults.standard.string(forKey: urlDefaultsKey),
            let url = URL(string: urlString)
        else { return nil }

        let mode = GatewayAuthMode(
            rawValue: UserDefaults.standard.string(forKey: authModeDefaultsKey) ?? ""
        ) ?? .token
        let username = UserDefaults.standard.string(forKey: usernameDefaultsKey) ?? ""
        let token = loadToken() ?? ""

        // Token mode without a stored token is an incomplete record.
        if mode == .token && token.isEmpty { return nil }

        return ConnectionSettings(baseURL: url, token: token, authMode: mode, username: username)
    }

    static func save(_ settings: ConnectionSettings) {
        UserDefaults.standard.set(settings.baseURL.absoluteString, forKey: urlDefaultsKey)
        UserDefaults.standard.set(settings.authMode.rawValue, forKey: authModeDefaultsKey)
        UserDefaults.standard.set(settings.username, forKey: usernameDefaultsKey)
        if settings.token.isEmpty {
            SecItemDelete(baseTokenQuery() as CFDictionary)
        } else {
            saveToken(settings.token)
        }
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: urlDefaultsKey)
        UserDefaults.standard.removeObject(forKey: authModeDefaultsKey)
        UserDefaults.standard.removeObject(forKey: usernameDefaultsKey)
        SecItemDelete(baseTokenQuery() as CFDictionary)
    }

    // MARK: - Keychain

    private static func baseTokenQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: keychainAccount,
        ]
    }

    private static func loadToken() -> String? {
        var query = baseTokenQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func saveToken(_ token: String) {
        let data = Data(token.utf8)
        var addQuery = baseTokenQuery()
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock

        let status = SecItemAdd(addQuery as CFDictionary, nil)
        if status == errSecDuplicateItem {
            SecItemUpdate(
                baseTokenQuery() as CFDictionary,
                [kSecValueData as String: data] as CFDictionary
            )
        }
    }
}
