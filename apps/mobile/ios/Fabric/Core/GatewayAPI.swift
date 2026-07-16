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

/// Row shape returned by the `session.active_list` RPC — live in-memory
/// sessions on the gateway, unlike the historical `session.list`
/// (see `_session_live_item` in `tui_gateway/server.py`).
struct ActiveSession: Identifiable, Hashable {
    let id: String
    let title: String
    let preview: String
    /// "working" | "waiting" | "starting" | "idle" (`_session_live_status`).
    let status: String
    let model: String
    let messageCount: Int
    let lastActive: TimeInterval
    let current: Bool
}

/// One slash command from `commands.catalog` (name includes the leading `/`).
struct SlashCommand: Identifiable, Hashable {
    let name: String
    let detail: String
    var id: String { name }
}

/// A category of slash commands, in the catalog's display order.
struct SlashCommandCategory: Identifiable, Hashable {
    let name: String
    let commands: [SlashCommand]
    var id: String { name }
}

/// Row shape from `process.list` — background processes owned by a session
/// (see `_session_processes` / `tools/process_registry.py`).
struct BackgroundProcess: Identifiable, Hashable {
    let id: String
    let command: String
    let pid: Int
    /// "running" | "exited".
    let status: String
    let uptimeSeconds: Int
    let outputTail: String
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

    // MARK: - Remote control / dispatch

    /// Inject a mid-turn note without interrupting (`AIAgent.steer`). Returns
    /// true when the gateway queued it, false when the agent rejected it.
    func steer(sessionId: String, text: String) async throws -> Bool {
        let result = try await client.requestObject(
            "session.steer",
            params: ["session_id": sessionId, "text": text]
        )
        return (result["status"] as? String) == "queued"
    }

    /// Run a prompt as a detached background task. The result arrives later
    /// as a `background.complete` event with `{task_id, text}`.
    func submitBackgroundPrompt(sessionId: String, text: String) async throws -> String? {
        let result = try await client.requestObject(
            "prompt.background",
            params: ["session_id": sessionId, "text": text]
        )
        return result["task_id"] as? String
    }

    /// Dispatch a slash command exactly as the TUI composer does. Some
    /// commands return inline `output`; others act via streamed events.
    func execSlashCommand(sessionId: String, command: String) async throws -> String? {
        let result = try await client.requestObject(
            "slash.exec",
            params: ["session_id": sessionId, "command": command]
        )
        return result["output"] as? String
    }

    /// The registry-backed slash-command catalog, grouped by category.
    func commandCatalog() async throws -> [SlashCommandCategory] {
        let result = try await client.requestObject("commands.catalog")
        let categories = result["categories"] as? [[String: Any]] ?? []
        return categories.compactMap { category in
            guard let name = category["name"] as? String else { return nil }
            let pairs = category["pairs"] as? [[Any]] ?? []
            let commands: [SlashCommand] = pairs.compactMap { pair in
                guard let cmdName = pair.first as? String else { return nil }
                return SlashCommand(
                    name: cmdName,
                    detail: pair.count > 1 ? (pair[1] as? String ?? "") : ""
                )
            }
            return commands.isEmpty ? nil : SlashCommandCategory(name: name, commands: commands)
        }
    }

    /// Live gateway sessions (running turns, waiting prompts, idle agents).
    func activeSessions(currentSessionId: String? = nil) async throws -> [ActiveSession] {
        var params: [String: Any] = [:]
        if let currentSessionId { params["current_session_id"] = currentSessionId }
        let result = try await client.requestObject("session.active_list", params: params)
        let rows = result["sessions"] as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let id = row["id"] as? String else { return nil }
            return ActiveSession(
                id: id,
                title: row["title"] as? String ?? "",
                preview: row["preview"] as? String ?? "",
                status: row["status"] as? String ?? "idle",
                model: row["model"] as? String ?? "",
                messageCount: (row["message_count"] as? NSNumber)?.intValue ?? 0,
                lastActive: (row["last_active"] as? NSNumber)?.doubleValue ?? 0,
                current: row["current"] as? Bool ?? false
            )
        }
    }

    /// Background processes owned by a session (preview servers, watchers…).
    func listProcesses(sessionId: String) async throws -> [BackgroundProcess] {
        let result = try await client.requestObject(
            "process.list",
            params: ["session_id": sessionId]
        )
        let rows = result["processes"] as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let id = row["session_id"] as? String else { return nil }
            return BackgroundProcess(
                id: id,
                command: row["command"] as? String ?? "",
                pid: (row["pid"] as? NSNumber)?.intValue ?? 0,
                status: row["status"] as? String ?? "running",
                uptimeSeconds: (row["uptime_seconds"] as? NSNumber)?.intValue ?? 0,
                outputTail: row["output_tail"] as? String ?? ""
            )
        }
    }

    func killProcess(sessionId: String, processId: String) async throws {
        _ = try await client.request(
            "process.kill",
            params: ["session_id": sessionId, "process_id": processId]
        )
    }

    // MARK: - Blocking prompt responses (clarify / sudo / secret)
    // These unblock `_block(...)` waits keyed by `request_id`
    // (`_respond` in `tui_gateway/server.py`).

    func respondToClarify(requestId: String, answer: String) async throws {
        _ = try await client.request(
            "clarify.respond",
            params: ["request_id": requestId, "answer": answer]
        )
    }

    func respondToSudo(requestId: String, password: String) async throws {
        _ = try await client.request(
            "sudo.respond",
            params: ["request_id": requestId, "password": password]
        )
    }

    func respondToSecret(requestId: String, value: String) async throws {
        _ = try await client.request(
            "secret.respond",
            params: ["request_id": requestId, "value": value]
        )
    }
}
