import Foundation
import Observation

/// One transcript row. Assistant messages accumulate `message.delta` text
/// while `streaming` is true; `message.complete` finalizes them.
struct TranscriptMessage: Identifiable, Equatable {
    enum Role: Equatable {
        case user
        case assistant
        /// Errors and failures — rendered prominently.
        case system
        /// Neutral local notices (slash output, steer/background confirmations).
        case info
    }

    let id: UUID
    let role: Role
    var text: String
    var streaming: Bool

    init(role: Role, text: String, streaming: Bool = false) {
        self.id = UUID()
        self.role = role
        self.text = text
        self.streaming = streaming
    }
}

/// A pending `approval.request` awaiting an allow/deny. The command string
/// arrives pre-redacted from the server.
struct PendingApproval: Equatable {
    let command: String?
    let summary: String?
}

/// A blocking prompt from the agent: `clarify.request` (question + optional
/// choices), `sudo.request` (password), or `secret.request` (secret value).
/// Answered via the matching `*.respond` RPC keyed by `requestId`.
struct PendingPrompt: Equatable {
    enum Kind: Equatable {
        case clarify
        case sudo
        case secret
    }

    let kind: Kind
    let requestId: String
    let question: String
    let choices: [String]

    var isSecureEntry: Bool { kind != .clarify }
}

/// Wires one chat session to the gateway event stream: creates or resumes
/// the runtime session, submits prompts, and folds streaming events into a
/// renderable transcript. Event names/payloads match the shared contract in
/// `apps/shared/src/json-rpc-gateway.ts` and `tui_gateway/server.py`.
@Observable
@MainActor
final class ChatViewModel {
    private(set) var messages: [TranscriptMessage] = []
    private(set) var statusLine: String?
    private(set) var busy = false
    private(set) var pendingApproval: PendingApproval?
    private(set) var pendingPrompt: PendingPrompt?
    private(set) var sessionReady = false
    private(set) var sessionError: String?

    let api: GatewayAPI
    private let resumeStoredSessionId: String?
    private(set) var sessionId: String?
    private var unsubscribe: (() -> Void)?

    init(api: GatewayAPI, resumeStoredSessionId: String?) {
        self.api = api
        self.resumeStoredSessionId = resumeStoredSessionId
    }

    func start() async {
        guard sessionId == nil else { return }
        subscribeToEvents()
        do {
            let live: LiveSession
            if let resumeStoredSessionId {
                live = try await api.resumeSession(storedSessionId: resumeStoredSessionId)
            } else {
                live = try await api.createSession()
            }
            guard !live.sessionId.isEmpty else {
                sessionError = "Gateway returned no session id."
                return
            }
            sessionId = live.sessionId
            sessionReady = true
        } catch {
            sessionError = error.localizedDescription
        }
    }

    func stop() {
        unsubscribe?()
        unsubscribe = nil
    }

    /// Route a composer submit the way the TUI does: a busy turn gets a
    /// steering note, "/..." dispatches a slash command, everything else is
    /// a normal prompt.
    func send(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let sessionId, !trimmed.isEmpty else { return }

        if busy {
            await steer(trimmed)
            return
        }

        if trimmed.hasPrefix("/") {
            await execSlash(trimmed)
            return
        }

        messages.append(TranscriptMessage(role: .user, text: trimmed))
        busy = true
        do {
            try await api.submitPrompt(sessionId: sessionId, text: trimmed)
        } catch {
            busy = false
            messages.append(TranscriptMessage(role: .system, text: "Send failed: \(error.localizedDescription)"))
        }
    }

    /// Inject a note into the running turn without interrupting it.
    func steer(_ text: String) async {
        guard let sessionId else { return }
        do {
            let queued = try await api.steer(sessionId: sessionId, text: text)
            messages.append(TranscriptMessage(
                role: .info,
                text: queued
                    ? "Steering note queued — the agent sees it on its next step."
                    : "Steering rejected: no turn is accepting notes right now."
            ))
        } catch {
            messages.append(TranscriptMessage(role: .system, text: "Steer failed: \(error.localizedDescription)"))
        }
    }

    /// Dispatch a slash command (`/status`, `/model`, skills, quick commands…).
    func execSlash(_ command: String) async {
        guard let sessionId else { return }
        messages.append(TranscriptMessage(role: .user, text: command))
        do {
            let output = try await api.execSlashCommand(sessionId: sessionId, command: command)
            if let output, !output.isEmpty {
                messages.append(TranscriptMessage(role: .info, text: output))
            }
        } catch {
            messages.append(TranscriptMessage(role: .system, text: "Command failed: \(error.localizedDescription)"))
        }
    }

    /// Run the text as a detached background task; the result comes back as
    /// a `background.complete` event even while other turns run.
    func sendInBackground(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let sessionId, !trimmed.isEmpty else { return }
        messages.append(TranscriptMessage(role: .user, text: trimmed))
        do {
            let taskId = try await api.submitBackgroundPrompt(sessionId: sessionId, text: trimmed)
            messages.append(TranscriptMessage(
                role: .info,
                text: "Background task started\(taskId.map { " (\($0))" } ?? "")."
            ))
        } catch {
            messages.append(TranscriptMessage(role: .system, text: "Background task failed: \(error.localizedDescription)"))
        }
    }

    func interrupt() async {
        guard let sessionId else { return }
        try? await api.interrupt(sessionId: sessionId)
    }

    func respondToApproval(allow: Bool) async {
        guard let sessionId else { return }
        pendingApproval = nil
        do {
            try await api.respondToApproval(sessionId: sessionId, choice: allow ? "allow" : "deny")
        } catch {
            messages.append(TranscriptMessage(role: .system, text: "Approval reply failed: \(error.localizedDescription)"))
        }
    }

    /// Answer the pending clarify/sudo/secret prompt. An empty answer is a
    /// valid "dismiss" (the server releases the wait with an empty string).
    func respondToPrompt(_ answer: String) async {
        guard let prompt = pendingPrompt else { return }
        pendingPrompt = nil
        do {
            switch prompt.kind {
            case .clarify:
                try await api.respondToClarify(requestId: prompt.requestId, answer: answer)
            case .sudo:
                try await api.respondToSudo(requestId: prompt.requestId, password: answer)
            case .secret:
                try await api.respondToSecret(requestId: prompt.requestId, value: answer)
            }
        } catch {
            messages.append(TranscriptMessage(role: .system, text: "Prompt reply failed: \(error.localizedDescription)"))
        }
    }

    // MARK: - Event folding

    private func subscribeToEvents() {
        let client = api.client
        let previous = client.onEvent
        // The client dispatches events on the main queue; assumeIsolated keeps
        // delivery synchronous so streaming deltas stay ordered.
        client.onEvent = { [weak self] event in
            previous?(event)
            MainActor.assumeIsolated {
                self?.handle(event)
            }
        }
        unsubscribe = { client.onEvent = previous }
    }

    private func handle(_ event: GatewayEvent) {
        // Events carry the runtime session id; ignore other sessions' traffic.
        if let eventSession = event.sessionId, let ours = sessionId, eventSession != ours {
            return
        }

        switch event.type {
        case "message.start":
            busy = true
            statusLine = nil
            messages.append(TranscriptMessage(role: .assistant, text: "", streaming: true))

        case "message.delta":
            guard let text = event.payloadText else { return }
            appendToStreamingAssistant(text)

        case "message.complete":
            busy = false
            statusLine = nil
            if var last = messages.last, last.role == .assistant, last.streaming {
                // The complete frame carries the final text; prefer it when the
                // streamed buffer is empty (some paths emit complete-only).
                if last.text.isEmpty, let text = event.payloadText {
                    last.text = text
                }
                last.streaming = false
                messages[messages.count - 1] = last
            } else if let text = event.payloadText, !text.isEmpty {
                messages.append(TranscriptMessage(role: .assistant, text: text))
            }

        case "thinking.delta":
            statusLine = "Thinking…"

        case "status.update":
            let kind = event.payload["kind"] as? String
            let text = event.payload["text"] as? String
            statusLine = text ?? kind

        case "tool.start":
            let name = (event.payload["name"] as? String)
                ?? (event.payload["tool"] as? String)
                ?? "tool"
            statusLine = "Running \(name)…"

        case "tool.complete":
            statusLine = nil

        case "approval.request":
            pendingApproval = PendingApproval(
                command: event.payload["command"] as? String,
                summary: event.payload["summary"] as? String
            )

        case "clarify.request":
            guard let requestId = event.payload["request_id"] as? String else { return }
            pendingPrompt = PendingPrompt(
                kind: .clarify,
                requestId: requestId,
                question: event.payload["question"] as? String ?? "The agent has a question.",
                choices: event.payload["choices"] as? [String] ?? []
            )

        case "sudo.request":
            guard let requestId = event.payload["request_id"] as? String else { return }
            pendingPrompt = PendingPrompt(
                kind: .sudo,
                requestId: requestId,
                question: event.payload["prompt"] as? String ?? "Administrator password requested.",
                choices: []
            )

        case "secret.request":
            guard let requestId = event.payload["request_id"] as? String else { return }
            pendingPrompt = PendingPrompt(
                kind: .secret,
                requestId: requestId,
                question: event.payload["prompt"] as? String ?? "A secret value was requested.",
                choices: []
            )

        case "background.complete":
            let taskId = event.payload["task_id"] as? String
            let text = event.payloadText ?? ""
            messages.append(TranscriptMessage(
                role: .info,
                text: "Background task\(taskId.map { " \($0)" } ?? "") finished:\n\(text)"
            ))

        case "error":
            busy = false
            let message = (event.payload["message"] as? String) ?? "Unknown gateway error"
            messages.append(TranscriptMessage(role: .system, text: message))

        default:
            break
        }
    }

    private func appendToStreamingAssistant(_ text: String) {
        if var last = messages.last, last.role == .assistant, last.streaming {
            last.text += text
            messages[messages.count - 1] = last
        } else {
            messages.append(TranscriptMessage(role: .assistant, text: text, streaming: true))
        }
    }
}
