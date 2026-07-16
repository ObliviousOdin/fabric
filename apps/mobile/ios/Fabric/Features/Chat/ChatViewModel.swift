import Foundation
import Observation

/// One transcript row. Assistant messages accumulate `message.delta` text
/// while `streaming` is true; `message.complete` finalizes them.
struct TranscriptMessage: Identifiable, Equatable {
    enum Role: Equatable {
        case user
        case assistant
        case system
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
    private(set) var sessionReady = false
    private(set) var sessionError: String?

    private let api: GatewayAPI
    private let resumeStoredSessionId: String?
    private var sessionId: String?
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

    func send(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let sessionId, !trimmed.isEmpty else { return }
        messages.append(TranscriptMessage(role: .user, text: trimmed))
        busy = true
        do {
            try await api.submitPrompt(sessionId: sessionId, text: trimmed)
        } catch {
            busy = false
            messages.append(TranscriptMessage(role: .system, text: "Send failed: \(error.localizedDescription)"))
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
