import Foundation

/// Row shape returned by the `session.list` RPC
/// (see `tui_gateway/server.py`, `@method("session.list")`).
struct SessionSummary: Identifiable, Hashable {
    let id: String
    let title: String
    let preview: String
    let startedAt: TimeInterval
    let messageCount: Int
    let source: String

    var displayTitle: String {
        if !title.isEmpty { return title }
        if !preview.isEmpty { return preview }
        return "Untitled session"
    }
}

/// Result of `session.create` / `session.resume`.
struct LiveSession {
    let sessionId: String
    let storedSessionId: String?
}

/// Public body of `GET /api/status`. Only the fields the client needs;
/// `authRequired` distinguishes an OAuth-gated gateway from legacy token
/// auth (`authModeFromStatus` in `apps/desktop/electron/connection-config.ts`).
struct GatewayStatus {
    let authRequired: Bool
    let raw: [String: Any]
}

enum GatewayAPIError: LocalizedError {
    case badURL
    case httpStatus(Int, body: String)

    var errorDescription: String? {
        switch self {
        case .badURL:
            return "Gateway URL must be http:// or https://"
        case .httpStatus(let code, let body):
            return body.isEmpty ? "HTTP \(code)" : "HTTP \(code): \(body)"
        }
    }
}

/// Typed wrappers around the raw JSON-RPC client for the methods the mobile
/// slice uses. Method names and parameter shapes mirror the desktop
/// renderer's call sites (`use-session-actions`, `use-prompt-actions`).
struct GatewayAPI {
    let client: JsonRpcGatewayClient

    // MARK: - REST (pre-socket)

    /// Public liveness probe; also classifies the gateway's auth mode.
    static func probeStatus(baseURL: URL) async throws -> GatewayStatus {
        let statusURL = baseURL.appending(path: "api/status")
        var request = URLRequest(url: statusURL, timeoutInterval: 10)
        request.httpMethod = "GET"
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw GatewayAPIError.badURL
        }
        guard (200..<300).contains(http.statusCode) else {
            throw GatewayAPIError.httpStatus(http.statusCode, body: String(decoding: data, as: UTF8.self))
        }
        let body = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        return GatewayStatus(authRequired: body["auth_required"] as? Bool ?? false, raw: body)
    }

    /// `ws(s)://host[/prefix]/api/ws?token=…` — the token-mode WS URL, same
    /// construction as `buildGatewayWsUrl` in the desktop connection config.
    static func websocketURL(baseURL: URL, token: String) throws -> URL {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              let scheme = components.scheme, scheme == "http" || scheme == "https"
        else {
            throw GatewayAPIError.badURL
        }
        components.scheme = scheme == "https" ? "wss" : "ws"
        let prefix = components.path.hasSuffix("/") ? String(components.path.dropLast()) : components.path
        components.path = prefix + "/api/ws"
        components.queryItems = [URLQueryItem(name: "token", value: token)]
        guard let url = components.url else { throw GatewayAPIError.badURL }
        return url
    }

    // MARK: - Sessions

    func listSessions(limit: Int = 100) async throws -> [SessionSummary] {
        let result = try await client.requestObject("session.list", params: ["limit": limit])
        let rows = result["sessions"] as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let id = row["id"] as? String else { return nil }
            return SessionSummary(
                id: id,
                title: row["title"] as? String ?? "",
                preview: row["preview"] as? String ?? "",
                startedAt: (row["started_at"] as? NSNumber)?.doubleValue ?? 0,
                messageCount: (row["message_count"] as? NSNumber)?.intValue ?? 0,
                source: row["source"] as? String ?? ""
            )
        }
    }

    func createSession(profile: String? = nil) async throws -> LiveSession {
        var params: [String: Any] = ["cols": 96, "source": "mobile"]
        if let profile, !profile.isEmpty { params["profile"] = profile }
        let result = try await client.requestObject("session.create", params: params)
        return LiveSession(
            sessionId: result["session_id"] as? String ?? "",
            storedSessionId: result["stored_session_id"] as? String
        )
    }

    func resumeSession(storedSessionId: String) async throws -> LiveSession {
        let result = try await client.requestObject(
            "session.resume",
            params: ["session_id": storedSessionId, "cols": 96]
        )
        return LiveSession(
            sessionId: result["session_id"] as? String ?? storedSessionId,
            storedSessionId: storedSessionId
        )
    }

    // MARK: - Turns

    func submitPrompt(sessionId: String, text: String) async throws {
        _ = try await client.request(
            "prompt.submit",
            params: ["session_id": sessionId, "text": text]
        )
    }

    func interrupt(sessionId: String) async throws {
        _ = try await client.request("session.interrupt", params: ["session_id": sessionId])
    }

    /// `choice` is "allow" or "deny"; `all` resolves every queued approval
    /// (see `tools/approval.py`, `resolve_gateway_approval`).
    func respondToApproval(sessionId: String, choice: String, all: Bool = false) async throws {
        _ = try await client.request(
            "approval.respond",
            params: ["session_id": sessionId, "choice": choice, "all": all]
        )
    }
}
