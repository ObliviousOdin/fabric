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

/// Parsed version-1 `fabric://pair` payload from a pairing QR
/// (emitted by `fabric mobile`; contract in `fabric_cli/mobile_pairing.py`).
///
/// - `auth == "token"`: `token` is the session credential; connect directly.
/// - `auth == "gated"`: the gateway requires a provider login; the app asks
///   for username/password after the scan.
struct PairingPayload: Equatable {
    let baseURL: URL
    let gated: Bool
    let token: String?

    private static let gatedKeys: Set<String> = ["v", "url", "auth"]
    private static let tokenKeys = gatedKeys.union(["token"])

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
            params["v"] == "1",
            let rawBaseURL = params["url"],
            let baseURL = GatewayBaseURL.parse(rawBaseURL)
        else { return nil }

        switch params["auth"] {
        case "gated":
            guard Set(params.keys) == gatedKeys else { return nil }
            return PairingPayload(baseURL: baseURL, gated: true, token: nil)
        case "token":
            guard
                Set(params.keys) == tokenKeys,
                let token = params["token"],
                !token.isEmpty
            else { return nil }
            return PairingPayload(baseURL: baseURL, gated: false, token: token)
        default:
            return nil
        }
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
