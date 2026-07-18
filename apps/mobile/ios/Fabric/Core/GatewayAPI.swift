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

/// One visible transcript row returned in `session.resume.messages`.
struct SessionTranscriptMessage: Equatable {
    enum Role: String, Equatable {
        case user
        case assistant
        case system
        case tool
    }

    let role: Role
    let text: String
    let reasoning: String?

    init(role: Role, text: String, reasoning: String? = nil) {
        self.role = role
        self.text = text
        self.reasoning = reasoning
    }

    init?(payload: [String: Any]) {
        guard
            let rawRole = payload["role"] as? String,
            let role = Role(rawValue: rawRole)
        else { return nil }

        let text: String
        if role == .tool {
            text = (payload["context"] as? String)
                ?? (payload["name"] as? String)
                ?? ""
        } else {
            text = (payload["text"] as? String)
                ?? (payload["content"] as? String)
                ?? ""
        }

        let reasoning = role == .assistant
            ? Self.firstReasoning(
                in: payload,
                keys: ["reasoning", "reasoning_content", "reasoning_details", "codex_reasoning_items"]
            )
            : nil
        guard
            !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !(reasoning?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
        else {
            return nil
        }
        self.role = role
        self.text = text
        self.reasoning = reasoning
    }

    private static func firstReasoning(in payload: [String: Any], keys: [String]) -> String? {
        keys.lazy.compactMap { reasoningText(payload[$0]) }.first
    }

    private static func reasoningText(_ value: Any?) -> String? {
        if let text = value as? String {
            return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : text
        }
        if let values = value as? [Any] {
            let parts = values.compactMap(reasoningText)
            return parts.isEmpty ? nil : parts.joined(separator: "\n")
        }
        if let object = value as? [String: Any] {
            for key in ["text", "summary", "content", "reasoning"] {
                if let text = reasoningText(object[key]) { return text }
            }
            guard JSONSerialization.isValidJSONObject(object),
                  let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
            else { return nil }
            return String(data: data, encoding: .utf8)
        }
        return nil
    }
}

/// Current turn returned by `session.resume.inflight` when the agent is active.
struct SessionInflight: Equatable {
    let user: String
    let assistant: String
    let streaming: Bool

    init(user: String, assistant: String, streaming: Bool) {
        self.user = user
        self.assistant = assistant
        self.streaming = streaming
    }

    init?(payload: [String: Any]) {
        user = payload["user"] as? String ?? ""
        assistant = payload["assistant"] as? String ?? ""
        streaming = payload["streaming"] as? Bool ?? false
        guard !user.isEmpty || !assistant.isEmpty || streaming else { return nil }
    }
}

/// Result of `session.create` / `session.resume`.
struct LiveSession {
    let sessionId: String
    let storedSessionId: String?
    let messages: [SessionTranscriptMessage]
    let running: Bool
    let inflight: SessionInflight?
    let historyVersion: Int?
    let pendingInteractions: [GatewayEvent]

    init(
        sessionId: String,
        storedSessionId: String?,
        messages: [SessionTranscriptMessage] = [],
        running: Bool = false,
        inflight: SessionInflight? = nil,
        historyVersion: Int? = nil,
        pendingInteractions: [GatewayEvent] = []
    ) {
        self.sessionId = sessionId
        self.storedSessionId = storedSessionId
        self.messages = messages
        self.running = running
        self.inflight = inflight
        self.historyVersion = historyVersion
        self.pendingInteractions = pendingInteractions
    }

    init(resumePayload: [String: Any], storedSessionId: String) {
        let runtimeSessionId = resumePayload["session_id"] as? String ?? storedSessionId
        sessionId = runtimeSessionId
        self.storedSessionId = (resumePayload["session_key"] as? String)
            ?? (resumePayload["stored_session_id"] as? String)
            ?? (resumePayload["resumed"] as? String)
            ?? storedSessionId
        let rows = resumePayload["messages"] as? [[String: Any]] ?? []
        messages = rows.compactMap(SessionTranscriptMessage.init(payload:))
        running = resumePayload["running"] as? Bool ?? false
        inflight = (resumePayload["inflight"] as? [String: Any]).flatMap(SessionInflight.init(payload:))
        historyVersion = (resumePayload["history_version"] as? NSNumber)?.intValue
        pendingInteractions = (resumePayload["pending_interactions"] as? [[String: Any]] ?? [])
            .compactMap { interaction in
                guard let type = interaction["type"] as? String else { return nil }
                return GatewayEvent(
                    type: type,
                    sessionId: runtimeSessionId,
                    payload: interaction["payload"] as? [String: Any] ?? [:]
                )
            }
    }
}

/// Row shape returned by the `session.active_list` RPC — live in-memory
/// sessions on the gateway, unlike the historical `session.list`
/// (see `_session_live_item` in `tui_gateway/server.py`).
struct ActiveSession: Identifiable, Hashable {
    let id: String
    let sessionKey: String
    let title: String
    let preview: String
    /// "working" | "waiting" | "starting" | "idle" (`_session_live_status`).
    let status: String
    let model: String
    let messageCount: Int
    let lastActive: TimeInterval
    let current: Bool

    init?(payload: [String: Any]) {
        guard let id = payload["id"] as? String else { return nil }
        self.id = id
        sessionKey = payload["session_key"] as? String ?? id
        title = payload["title"] as? String ?? ""
        preview = payload["preview"] as? String ?? ""
        status = payload["status"] as? String ?? "idle"
        model = payload["model"] as? String ?? ""
        messageCount = (payload["message_count"] as? NSNumber)?.intValue ?? 0
        lastActive = (payload["last_active"] as? NSNumber)?.doubleValue ?? 0
        current = payload["current"] as? Bool ?? false
    }
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

/// A read-only screen capture from `computer.screenshot`.
struct ScreenCapture {
    let image: Data
    let width: Int
    let height: Int
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
/// `authRequired` distinguishes a gated gateway (provider login + WS tickets)
/// from legacy token auth (`authModeFromStatus` in
/// `apps/desktop/electron/connection-config.ts`).
struct GatewayStatus {
    let authRequired: Bool
    let raw: [String: Any]
}

/// Row from `GET /api/auth/providers` (gated gateways only).
struct AuthProviderInfo: Identifiable, Hashable {
    let name: String
    let displayName: String
    let supportsPassword: Bool
    /// Provider requires a TOTP second factor — show a code field.
    let requiresTotp: Bool
    var id: String { name }
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

    /// Process-scoped, non-persistent cookie session for gated login. The
    /// access and refresh cookies never enter URLSession's shared on-disk jar.
    static let httpSession: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = true
        configuration.httpCookieAcceptPolicy = .always
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        return URLSession(configuration: configuration)
    }()

    static func clearAuthSession() {
        let storage = httpSession.configuration.httpCookieStorage
        storage?.cookies?.forEach { storage?.deleteCookie($0) }
    }

    // MARK: - REST (pre-socket)

    /// Public liveness probe; also classifies the gateway's auth mode.
    static func probeStatus(baseURL: URL) async throws -> GatewayStatus {
        let statusURL = baseURL.appending(path: "api/status")
        var request = URLRequest(url: statusURL, timeoutInterval: 10)
        request.httpMethod = "GET"
        let (data, response) = try await httpSession.data(for: request)
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
        try websocketURL(baseURL: baseURL, authParam: ("token", token))
    }

    /// `ws(s)://…/api/ws?ticket=…` — the gated-mode WS URL. Tickets are
    /// single-use with a 30s TTL: mint one immediately before every connect.
    static func websocketURL(baseURL: URL, ticket: String) throws -> URL {
        try websocketURL(baseURL: baseURL, authParam: ("ticket", ticket))
    }

    private static func websocketURL(baseURL: URL, authParam: (String, String)) throws -> URL {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              let scheme = components.scheme, scheme == "http" || scheme == "https"
        else {
            throw GatewayAPIError.badURL
        }
        components.scheme = scheme == "https" ? "wss" : "ws"
        let prefix = components.path.hasSuffix("/") ? String(components.path.dropLast()) : components.path
        components.path = prefix + "/api/ws"
        components.queryItems = [URLQueryItem(name: authParam.0, value: authParam.1)]
        guard let url = components.url else { throw GatewayAPIError.badURL }
        return url
    }

    // MARK: - Gated auth (provider login + WS tickets)
    // The ephemeral session stores the cookies set by `/auth/password-login`,
    // so ticket minting is authenticated without persistence across launches.

    /// `GET /api/auth/providers` — which sign-in options this gateway offers.
    static func listAuthProviders(baseURL: URL) async throws -> [AuthProviderInfo] {
        let url = baseURL.appending(path: "api/auth/providers")
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.httpMethod = "GET"
        let (data, response) = try await httpSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw GatewayAPIError.httpStatus(code, body: String(decoding: data, as: UTF8.self))
        }
        let body = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        let rows = body["providers"] as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let name = row["name"] as? String else { return nil }
            return AuthProviderInfo(
                name: name,
                displayName: row["display_name"] as? String ?? name,
                supportsPassword: row["supports_password"] as? Bool ?? false,
                requiresTotp: row["requires_totp"] as? Bool ?? false
            )
        }
    }

    /// `POST /auth/password-login` — authenticates and stores the session
    /// cookies. 401 means bad credentials; 429 rate-limited.
    static func passwordLogin(
        baseURL: URL,
        provider: String,
        username: String,
        password: String,
        otp: String = ""
    ) async throws {
        let url = baseURL.appending(path: "auth/password-login")
        var request = URLRequest(url: url, timeoutInterval: 15)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "provider": provider,
            "username": username,
            "password": password,
            "otp": otp,
        ])
        let (data, response) = try await httpSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw GatewayAPIError.httpStatus(code, body: detail ?? "Sign-in failed")
        }
    }

    /// `POST /api/auth/ws-ticket` — single-use 30s WS credential for the
    /// cookie session. A 401 here means the session has expired (or was
    /// never established): re-run `passwordLogin`.
    static func mintWsTicket(baseURL: URL) async throws -> String {
        let url = baseURL.appending(path: "api/auth/ws-ticket")
        var request = URLRequest(url: url, timeoutInterval: 15)
        request.httpMethod = "POST"
        let (data, response) = try await httpSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw GatewayAPIError.httpStatus(code, body: String(decoding: data, as: UTF8.self))
        }
        let body = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        guard let ticket = body["ticket"] as? String, !ticket.isEmpty else {
            throw GatewayAPIError.httpStatus(500, body: "Gateway returned no ticket")
        }
        return ticket
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
            params: ["session_id": storedSessionId, "cols": 96, "source": "mobile"]
        )
        return LiveSession(resumePayload: result, storedSessionId: storedSessionId)
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
    func respondToApproval(
        sessionId: String,
        requestId: String,
        choice: String,
        all: Bool = false
    ) async throws {
        _ = try await client.request(
            "approval.respond",
            params: [
                "session_id": sessionId,
                "request_id": requestId,
                "choice": choice,
                "all": all,
            ]
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
        return rows.compactMap(ActiveSession.init(payload:))
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

    // MARK: - Computer use (live view)

    /// A read-only screen capture from the gateway host (`computer.screenshot`).
    /// The gateway returns a plain PNG (no overlays, no accessibility data).
    func captureScreen() async throws -> ScreenCapture {
        let result = try await client.requestObject("computer.screenshot")
        guard
            let b64 = result["png_b64"] as? String,
            let data = Data(base64Encoded: b64)
        else {
            throw GatewayClientError.rpc(message: "Live view unavailable on this server.")
        }
        return ScreenCapture(
            image: data,
            width: (result["width"] as? NSNumber)?.intValue ?? 0,
            height: (result["height"] as? NSNumber)?.intValue ?? 0
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
