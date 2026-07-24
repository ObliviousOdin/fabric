import Foundation
import LocalAuthentication
import Security

enum GatewayStoreError: LocalizedError, Equatable {
    case credentialStorageUnavailable
    case credentialRemovalUnavailable

    var errorDescription: String? {
        switch self {
        case .credentialStorageUnavailable:
            return "Couldn't protect this server credential. Unlock the device and try again."
        case .credentialRemovalUnavailable:
            return "Couldn't remove every protected server credential. Unlock the device and try again."
        }
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
/// credentials live in the Keychain keyed by `id`: the session token (token
/// mode) always, and the sign-in password (gated mode) only when the user
/// opts in to keeping it on this device. Without a kept password, a gated
/// server auto-logs-in only while its cookie session is alive.
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
    private static let connectionIntroKey = "fabric.gateways.connection-intro.v1"
    private static let keychainService = "io.github.obliviousodin.fabric.mobile"

    // MARK: - Library

    static func all() -> [SavedGateway] {
        guard
            let data = UserDefaults.standard.data(forKey: listKey),
            let list = try? JSONDecoder().decode([SavedGateway].self, from: data)
        else { return [] }

        // Older builds appended a new row on every scan. Keep the newest row
        // per endpoint and repair the library in place so stale duplicates do
        // not keep sending the user to an obsolete auth record.
        var seenEndpoints = Set<String>()
        let deduplicated = Array(list.reversed().filter {
            seenEndpoints.insert($0.endpointKey).inserted
        }.reversed())
        guard deduplicated.count != list.count else { return list }

        let keptIDs = Set(deduplicated.map(\.id))
        let removed = list.filter { !keptIDs.contains($0.id) }
        persist(deduplicated)
        for gateway in removed { deleteCredentials(id: gateway.id) }
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

    static func hasCompletedConnectionIntro(id: String) -> Bool {
        completedConnectionIntroIDs().contains(id)
    }

    static func setCompletedConnectionIntro(_ completed: Bool, id: String) {
        guard !id.isEmpty else { return }
        var ids = completedConnectionIntroIDs()
        if completed {
            ids.insert(id)
        } else {
            ids.remove(id)
        }
        UserDefaults.standard.set(Array(ids).sorted(), forKey: connectionIntroKey)
    }

    /// Insert or update non-secret metadata, then persist it.
    @discardableResult
    static func upsert(_ gateway: SavedGateway) -> [SavedGateway] {
        upsertMetadata(gateway, deleteCurrentToken: gateway.authMode == .gated)
    }

    /// Protect a token before publishing metadata that makes the server appear
    /// auto-connectable. Keychain failure leaves no partially saved server.
    /// A server switching to token auth also drops any kept sign-in password.
    @discardableResult
    static func upsert(_ gateway: SavedGateway, token: String) throws -> [SavedGateway] {
        guard GatewayBaseURL.allowsTokenCredential(gateway.baseURL) else {
            throw GatewayTokenTransportError.secureTransportRequired
        }
        try saveToken(token, id: gateway.id)
        deletePassword(id: gateway.id)
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
        for id in duplicateIDs { deleteCredentials(id: id) }
        if let lastActive = lastActiveId(), duplicateIDs.contains(lastActive) {
            setLastActive(gateway.id)
        }
        if deleteCurrentToken {
            // A server switching to gated auth sheds its stale token only;
            // any password the user chose to keep remains its credential.
            _ = deleteTokenStatus(id: gateway.id)
        }
        return list
    }

    /// Explicit user-initiated removal is credential-first: a failed Security
    /// framework deletion must leave the saved row and all related metadata in
    /// place so the UI can report failure without orphaning a token or a kept
    /// sign-in password.
    static func remove(id: String) throws {
        try remove(id: id, deleteCredential: {
            let tokenStatus = deleteTokenStatus(id: id)
            guard tokenStatus == errSecSuccess || tokenStatus == errSecItemNotFound else {
                return tokenStatus
            }
            return deletePasswordStatus(id: id)
        })
    }

    /// Internal seam for the offboarding failure contract. Maintenance cleanup
    /// during deduplication remains best-effort; this path backs the visible
    /// "Forget" promise and therefore must be verifiable.
    static func remove(id: String, deleteCredential: () -> OSStatus) throws {
        let status = deleteCredential()
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw GatewayStoreError.credentialRemovalUnavailable
        }
        persist(all().filter { $0.id != id })
        setCompletedConnectionIntro(false, id: id)
        if lastActiveId() == id { setLastActive(nil) }
    }

    /// Remove every protected gateway token for this app service before
    /// deleting the metadata that lets Settings verify reset completion.
    ///
    /// This deliberately does not derive the Keychain accounts from `all()`:
    /// that JSON may be missing or corrupt while orphaned credentials still
    /// exist. `errSecItemNotFound` is already the desired clean state; every
    /// other failure leaves metadata in place and is surfaced to the caller.
    static func removeAll() throws {
        try removeAll(deleteCredentialService: deleteCredentialService)
    }

    /// Internal seam for behavioral tests of the failure contract. Production
    /// callers use `removeAll()` above, which always performs the service-wide
    /// Security framework deletion.
    static func removeAll(deleteCredentialService: () -> OSStatus) throws {
        let status = deleteCredentialService()
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw GatewayStoreError.credentialRemovalUnavailable
        }
        UserDefaults.standard.removeObject(forKey: listKey)
        UserDefaults.standard.removeObject(forKey: lastActiveKey)
        UserDefaults.standard.removeObject(forKey: connectionIntroKey)
    }

    private static func completedConnectionIntroIDs() -> Set<String> {
        Set(UserDefaults.standard.stringArray(forKey: connectionIntroKey) ?? [])
    }

    static func token(id: String) -> String? {
        loadToken(id: id)
    }

    // MARK: - Kept sign-in passwords (gated mode, opt-in)

    /// Keep a gated server's sign-in password on this device. The password
    /// only ever lives in the Keychain — never in metadata — and, like a
    /// token, is only accepted for a transport that can keep it secret.
    static func savePassword(_ password: String, for gateway: SavedGateway) throws {
        guard GatewayBaseURL.allowsTokenCredential(gateway.baseURL) else {
            throw GatewayTokenTransportError.secureTransportRequired
        }
        try saveCredential(password, query: passwordQuery(id: gateway.id))
    }

    static func password(id: String) -> String? {
        loadCredential(query: passwordQuery(id: id))
    }

    static func deletePassword(id: String) {
        _ = deletePasswordStatus(id: id)
    }

    /// A gated server with a kept password can sign in again with no prompt
    /// (unless its provider requires a fresh TOTP code at connect time).
    static func hasStoredPassword(_ gateway: SavedGateway) -> Bool {
        hasStoredPassword(gateway, loadCredential: { password(id: $0) })
    }

    /// Internal seam mirroring `canAutoConnect`: the transport check runs
    /// before Keychain access so an unsafe endpoint never advertises a kept
    /// credential even when one still exists.
    static func hasStoredPassword(
        _ gateway: SavedGateway,
        loadCredential: (String) -> String?
    ) -> Bool {
        gateway.authMode == .gated
            && GatewayBaseURL.allowsTokenCredential(gateway.baseURL)
            && !(loadCredential(gateway.id) ?? "").isEmpty
    }

    /// A token-mode server with a stored token can reconnect with no prompt.
    /// (Gated servers are checked at connect time against the live cookie
    /// session and any kept password — see `hasStoredPassword`.)
    static func canAutoConnect(_ gateway: SavedGateway) -> Bool {
        canAutoConnect(gateway, loadCredential: loadToken)
    }

    /// Internal seam for the saved-upgrade contract. The transport check must
    /// run independently of Keychain availability so a legacy plaintext row
    /// is never advertised as reconnectable even when its token still exists.
    static func canAutoConnect(
        _ gateway: SavedGateway,
        loadCredential: (String) -> String?
    ) -> Bool {
        gateway.authMode == .token
            && GatewayBaseURL.allowsTokenCredential(gateway.baseURL)
            && !(loadCredential(gateway.id) ?? "").isEmpty
    }

    private static func persist(_ list: [SavedGateway]) {
        if let data = try? JSONEncoder().encode(list) {
            UserDefaults.standard.set(data, forKey: listKey)
        }
    }

    // MARK: - Keychain (token + optional password entries per gateway id)

    private static func tokenQuery(id: String) -> [String: Any] {
        credentialQuery(account: "gateway-token-\(id)")
    }

    private static func passwordQuery(id: String) -> [String: Any] {
        credentialQuery(account: "gateway-password-\(id)")
    }

    private static func credentialQuery(account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: account,
        ]
    }

    private static func loadToken(id: String) -> String? {
        loadCredential(query: tokenQuery(id: id))
    }

    private static func loadCredential(query: [String: Any]) -> String? {
        var query = query
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func saveToken(_ token: String, id: String) throws {
        try saveCredential(token, query: tokenQuery(id: id))
    }

    private static func saveCredential(_ value: String, query: [String: Any]) throws {
        let data = Data(value.utf8)
        var addQuery = query
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        let status: OSStatus
        if addStatus == errSecDuplicateItem {
            status = SecItemUpdate(
                query as CFDictionary,
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

    private static func deleteCredentials(id: String) {
        _ = deleteTokenStatus(id: id)
        _ = deletePasswordStatus(id: id)
    }

    private static func deleteTokenStatus(id: String) -> OSStatus {
        SecItemDelete(tokenQuery(id: id) as CFDictionary)
    }

    private static func deletePasswordStatus(id: String) -> OSStatus {
        SecItemDelete(passwordQuery(id: id) as CFDictionary)
    }

    private static func deleteCredentialService() -> OSStatus {
        SecItemDelete([
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
        ] as CFDictionary)
    }
}

/// Errors surfaced when a paired Link controller's opaque MLS state cannot be
/// protected or released. The state is deliberately separate from saved
/// gateway credentials: it grants machine-control authority, not just a
/// gateway HTTP session.
enum LinkControllerStoreError: LocalizedError, Equatable {
    case stateStorageUnavailable
    case stateRemovalUnavailable

    var errorDescription: String? {
        switch self {
        case .stateStorageUnavailable:
            return "Couldn't access protected Fabric Link state. Unlock this device and try again."
        case .stateRemovalUnavailable:
            return "Couldn't remove protected Fabric Link state. Unlock this device and try again."
        }
    }
}

/// Device-local storage for one paired Link controller's opaque MLS state.
///
/// The opaque state contains the controller's private MLS material. It never
/// enters UserDefaults, gateway metadata, app logs, or an app-managed file.
/// Every access requires the current device owner through the Keychain's
/// user-presence access-control flag, and `ThisDeviceOnly` prevents migration
/// to another device through backups or sync.
enum LinkControllerStore {
    private static let keychainService = "io.github.obliviousodin.fabric.link.controller.v1"
    private static let accountPrefix = "link-controller-"
    // OpenMLS state plus a crash-safe encrypted outbox can briefly exceed the
    // bare MLS snapshot size. Keep this aligned with the controller bundle's
    // 20 MiB hard ceiling; larger records fail closed before Keychain access.
    private static let maxStateBytes = 20 * 1024 * 1024
    private static let authorizationContexts = AuthorizationContextCache()

    static func load(controllerID: String) throws -> Data? {
        var query = authorizedCredentialQuery(
            controllerID: controllerID,
            reason: "Authenticate to access Fabric Link"
        )
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = item as? Data else {
            throw LinkControllerStoreError.stateStorageUnavailable
        }
        guard !data.isEmpty, data.count <= maxStateBytes else {
            throw LinkControllerStoreError.stateStorageUnavailable
        }
        return data
    }

    static func save(_ opaqueState: Data, controllerID: String) throws {
        guard !opaqueState.isEmpty, opaqueState.count <= maxStateBytes else {
            throw LinkControllerStoreError.stateStorageUnavailable
        }
        let query = credentialQuery(controllerID: controllerID)
        var accessControlError: Unmanaged<CFError>?
        guard let accessControl = SecAccessControlCreateWithFlags(
            nil,
            kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            .userPresence,
            &accessControlError
        ) else {
            throw LinkControllerStoreError.stateStorageUnavailable
        }

        var addQuery = query
        addQuery[kSecValueData as String] = opaqueState
        addQuery[kSecAttrAccessControl as String] = accessControl
        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        let status: OSStatus
        if addStatus == errSecDuplicateItem {
            // Existing controller items were created with the same access
            // control; only replace their opaque state after user presence.
            let authorizedQuery = authorizedCredentialQuery(
                controllerID: controllerID,
                reason: "Authenticate to update Fabric Link"
            )
            status = SecItemUpdate(
                authorizedQuery as CFDictionary,
                [kSecValueData as String: opaqueState] as CFDictionary
            )
        } else {
            status = addStatus
        }
        guard status == errSecSuccess else {
            throw LinkControllerStoreError.stateStorageUnavailable
        }
    }

    static func remove(controllerID: String) throws {
        let query = authorizedCredentialQuery(
            controllerID: controllerID,
            reason: "Authenticate to remove Fabric Link"
        )
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw LinkControllerStoreError.stateRemovalUnavailable
        }
        authorizationContexts.invalidate(controllerID: controllerID)
    }

    /// Re-lock all controller authority when the app leaves the foreground.
    ///
    /// A single authenticated context is deliberately reused while the app is
    /// active so polling a live session does not present a biometric prompt
    /// for every MLS state update. It never survives a background transition.
    static func lock() {
        authorizationContexts.invalidateAll()
    }

    private static func credentialQuery(controllerID: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: accountPrefix + validatedControllerID(controllerID),
        ]
    }

    private static func authorizedCredentialQuery(
        controllerID: String,
        reason: String
    ) -> [String: Any] {
        var query = credentialQuery(controllerID: controllerID)
        let context = authorizationContexts.context(
            controllerID: validatedControllerID(controllerID),
            reason: reason
        )
        query[kSecUseAuthenticationContext as String] = context
        return query
    }

    private static func validatedControllerID(_ controllerID: String) -> String {
        precondition(
            !controllerID.isEmpty && controllerID.count <= 128
                && controllerID.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "." || $0 == "_" || $0 == "-") },
            "Invalid Fabric Link controller identifier"
        )
        return controllerID
    }

    private final class AuthorizationContextCache: @unchecked Sendable {
        private let lock = NSLock()
        private var contexts: [String: LAContext] = [:]

        func context(controllerID: String, reason: String) -> LAContext {
            lock.lock()
            defer { lock.unlock() }
            if let existing = contexts[controllerID] {
                return existing
            }
            let context = LAContext()
            context.localizedReason = reason
            context.touchIDAuthenticationAllowableReuseDuration = 300
            contexts[controllerID] = context
            return context
        }

        func invalidate(controllerID: String) {
            lock.lock()
            let context = contexts.removeValue(forKey: controllerID)
            lock.unlock()
            context?.invalidate()
        }

        func invalidateAll() {
            lock.lock()
            let current = Array(contexts.values)
            contexts.removeAll(keepingCapacity: false)
            lock.unlock()
            current.forEach { $0.invalidate() }
        }
    }
}
