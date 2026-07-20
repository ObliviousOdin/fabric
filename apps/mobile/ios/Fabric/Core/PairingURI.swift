import Foundation

/// Validation for a server address entered directly by the user.
enum GatewayBaseURL {
    static func parse(_ raw: String) -> URL? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard
            !trimmed.isEmpty,
            !trimmed.unicodeScalars.contains(where: { $0.value <= 32 }),
            let components = URLComponents(string: trimmed),
            components.scheme?.lowercased() == "http" || components.scheme?.lowercased() == "https",
            !(components.host ?? "").isEmpty,
            components.user == nil,
            components.password == nil,
            components.query == nil,
            components.fragment == nil
        else { return nil }
        return components.url
    }
}

enum PairingEnrollmentAuth: Equatable {
    case browser
    case local
}

/// A v2 QR's time-limited handoff. The raw value stays in memory only and is
/// never interpreted as a session token or a saved device credential.
struct PairingEnrollment: Equatable {
    let handle: String
    let auth: PairingEnrollmentAuth
}

/// Parsed `fabric://pair` payload from a pairing QR
/// (emitted by `fabric mobile`; contract in `fabric_cli/mobile_pairing.py`).
///
/// - `auth == "token"`: `token` is the session credential; connect directly.
/// - `auth == "gated"`: the gateway requires a provider login; the app asks
///   for username/password after the scan.
/// - version 2: an opaque, one-time `enrollment` handoff is recognized but
///   must not be misclassified as either of the legacy paths.
struct PairingPayload: Equatable {
    let baseURL: URL
    let gated: Bool
    let token: String?
    let enrollment: PairingEnrollment?

    private static let gatedKeys: Set<String> = ["v", "url", "auth"]
    private static let tokenKeys = gatedKeys.union(["token"])
    private static let enrollmentKeys: Set<String> = ["v", "url", "enrollment", "auth"]

    /// Parse either the canonical payload or the browser landing URL whose
    /// fragment contains that payload. Direct server addresses belong to
    /// `GatewayBaseURL`, not this machine-readable contract.
    static func parse(_ raw: String) -> PairingPayload? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let components = URLComponents(string: trimmed) else { return nil }
        if components.scheme?.lowercased() == "fabric" {
            return parsePayload(components)
        }

        guard
            components.scheme?.lowercased() == "http" || components.scheme?.lowercased() == "https",
            !(components.host ?? "").isEmpty,
            components.user == nil,
            components.password == nil,
            components.path == "/mobile/pair",
            components.query == nil,
            let fragment = components.percentEncodedFragment,
            let fragmentItems = parameters(from: fragment),
            Set(fragmentItems.keys) == ["pair"],
            let wrapped = fragmentItems["pair"],
            let payload = URLComponents(string: wrapped)
        else { return nil }
        return parsePayload(payload)
    }

    private static func parsePayload(_ components: URLComponents) -> PairingPayload? {
        guard
            components.scheme?.lowercased() == "fabric",
            components.host == "pair",
            components.user == nil,
            components.password == nil,
            components.port == nil,
            components.path.isEmpty,
            components.fragment == nil,
            let query = components.percentEncodedQuery,
            let params = parameters(from: query),
            let version = params["v"],
            let rawBaseURL = params["url"],
            let baseURL = GatewayBaseURL.parse(rawBaseURL)
        else { return nil }

        if version == "2" {
            guard
                Set(params.keys) == enrollmentKeys,
                baseURL.scheme?.lowercased() == "https",
                canonicalV2GatewayURL(rawBaseURL),
                let handle = params["enrollment"],
                validEnrollmentHandle(handle)
            else { return nil }
            let enrollmentAuth: PairingEnrollmentAuth
            switch params["auth"] {
            case "browser": enrollmentAuth = .browser
            case "local": enrollmentAuth = .local
            default: return nil
            }
            return PairingPayload(
                baseURL: baseURL,
                gated: false,
                token: nil,
                enrollment: PairingEnrollment(handle: handle, auth: enrollmentAuth)
            )
        }

        guard version == "1" else { return nil }

        switch params["auth"] {
        case "gated":
            guard Set(params.keys) == gatedKeys else { return nil }
            return PairingPayload(baseURL: baseURL, gated: true, token: nil, enrollment: nil)
        case "token":
            guard
                Set(params.keys) == tokenKeys,
                let token = params["token"],
                !token.isEmpty
            else { return nil }
            return PairingPayload(baseURL: baseURL, gated: false, token: token, enrollment: nil)
        default:
            return nil
        }
    }

    private static func validEnrollmentHandle(_ value: String) -> Bool {
        guard value.range(of: "^[A-Za-z0-9_-]{43,128}$", options: .regularExpression) != nil else {
            return false
        }
        return true
    }

    /// `URL` normalizes repeated trailing slashes. Preserve the machine-issued
    /// v2 wire grammar by checking `URLComponents` before that normalization.
    private static func canonicalV2GatewayURL(_ raw: String) -> Bool {
        guard
            raw == raw.trimmingCharacters(in: .whitespacesAndNewlines),
            !raw.unicodeScalars.contains(where: { $0.value <= 32 }),
            let components = URLComponents(string: raw),
            components.scheme?.lowercased() == "https",
            components.percentEncodedPath.isEmpty || components.percentEncodedPath == "/"
        else { return false }
        return true
    }

    private static func parameters(from encoded: String) -> [String: String]? {
        guard let items = URLComponents(string: "fabric://parameters?\(encoded)")?.queryItems else {
            return nil
        }
        var values: [String: String] = [:]
        for item in items {
            guard !item.name.isEmpty, let value = item.value, values[item.name] == nil else {
                return nil
            }
            values[item.name] = value
        }
        return values
    }
}
