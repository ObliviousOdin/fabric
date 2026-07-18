import Foundation

/// Parsed `fabric://pair` payload from a pairing QR
/// (emitted by `fabric mobile`; contract in `fabric_cli/mobile_pairing.py`).
///
/// - `auth == "token"`: `token` is the session credential; connect directly.
/// - `auth == "gated"`: the gateway requires a provider login; the app asks
///   for username/password after the scan.
struct PairingPayload: Equatable {
    let baseURL: URL
    let gated: Bool
    let token: String?

    /// Parse a scanned string. Accepts the canonical `fabric://pair?...` URI
    /// and, as a convenience, a plain `http(s)://...` URL (treated as gated
    /// unless it carries a `token` query parameter).
    static func parse(_ raw: String) -> PairingPayload? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let components = URLComponents(string: trimmed) else { return nil }

        if components.scheme == "fabric" {
            guard components.host == "pair" else { return nil }
            var urlString: String?
            var auth = "gated"
            var token: String?
            var version: String?
            for item in components.queryItems ?? [] {
                switch item.name {
                case "v": version = item.value
                case "url": urlString = item.value
                case "auth": auth = item.value ?? "gated"
                case "token": token = item.value
                default: break
                }
            }
            guard
                version == "1",
                let urlString,
                let url = validatedBaseURL(urlString)
            else { return nil }
            let gated = auth != "token" || (token ?? "").isEmpty
            return PairingPayload(baseURL: url, gated: gated, token: gated ? nil : token)
        }

        if components.scheme == "http" || components.scheme == "https" {
            if components.path == "/mobile/pair", let fragment = components.percentEncodedFragment {
                let wrapped = URLComponents(string: "fabric://fragment?\(fragment)")?
                    .queryItems?
                    .first(where: { $0.name == "pair" })?
                    .value
                guard let wrapped else { return nil }
                return parse(wrapped)
            }
            guard components.fragment == nil else { return nil }

            let token = components.queryItems?.first(where: { $0.name == "token" })?.value
            var bare = components
            bare.queryItems = nil
            guard let baseString = bare.string, let base = validatedBaseURL(baseString) else {
                return nil
            }
            if let token, !token.isEmpty {
                return PairingPayload(baseURL: base, gated: false, token: token)
            }
            return PairingPayload(baseURL: base, gated: true, token: nil)
        }

        return nil
    }

    private static func validatedBaseURL(_ raw: String) -> URL? {
        guard
            let components = URLComponents(string: raw),
            components.scheme == "http" || components.scheme == "https",
            !(components.host ?? "").isEmpty,
            components.user == nil,
            components.password == nil,
            components.query == nil,
            components.fragment == nil
        else { return nil }
        return components.url
    }
}
