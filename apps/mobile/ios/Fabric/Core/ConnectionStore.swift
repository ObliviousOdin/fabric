import Foundation
import Security

/// Persisted connection settings: the gateway base URL lives in
/// UserDefaults (not secret), the session token in the Keychain.
struct ConnectionSettings: Equatable {
    var baseURL: URL
    var token: String
}

enum ConnectionStore {
    private static let urlDefaultsKey = "fabric.gateway.baseURL"
    private static let keychainService = "io.github.obliviousodin.fabric.mobile"
    private static let keychainAccount = "gateway-session-token"

    static func load() -> ConnectionSettings? {
        guard
            let urlString = UserDefaults.standard.string(forKey: urlDefaultsKey),
            let url = URL(string: urlString),
            let token = loadToken(), !token.isEmpty
        else { return nil }
        return ConnectionSettings(baseURL: url, token: token)
    }

    static func save(_ settings: ConnectionSettings) {
        UserDefaults.standard.set(settings.baseURL.absoluteString, forKey: urlDefaultsKey)
        saveToken(settings.token)
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: urlDefaultsKey)
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
