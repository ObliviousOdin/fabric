import Foundation

/// Parsed `fabric://pair` payload from a pairing QR
/// (emitted by `fabric serve --qr`; contract in `fabric_cli/mobile_pairing.py`).
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
            for item in components.queryItems ?? [] {
                switch item.name {
                case "url": urlString = item.value
                case "auth": auth = item.value ?? "gated"
                case "token": token = item.value
                default: break
                }
            }
            guard
                let urlString,
                let url = URL(string: urlString),
                url.scheme == "http" || url.scheme == "https"
            else { return nil }
            let gated = auth != "token" || (token ?? "").isEmpty
            return PairingPayload(baseURL: url, gated: gated, token: gated ? nil : token)
        }

        if components.scheme == "http" || components.scheme == "https" {
            guard let url = URL(string: trimmed) else { return nil }
            let token = components.queryItems?.first(where: { $0.name == "token" })?.value
            var bare = components
            bare.queryItems = nil
            let base = bare.url ?? url
            if let token, !token.isEmpty {
                return PairingPayload(baseURL: base, gated: false, token: token)
            }
            return PairingPayload(baseURL: base, gated: true, token: nil)
        }

        return nil
    }
}
