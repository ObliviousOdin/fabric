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

    init?(restoring message: SessionTranscriptMessage) {
        if message.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            guard
                message.role == .assistant,
                let reasoning = message.reasoning,
                !reasoning.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return nil }
            self.init(role: .info, text: "Thinking…\n\(reasoning)")
            return
        }
        let role: Role
        switch message.role {
        case .user:
            role = .user
        case .assistant:
            role = .assistant
        case .system, .tool:
            // Stored system/tool rows are transcript context, not failures.
            role = .info
        }
        self.init(role: role, text: message.text)
    }
}

/// A pending `approval.request` awaiting an allow/deny. The command string
/// arrives pre-redacted from the server.
struct PendingApproval: Equatable {
    let command: String?
    let requestId: String
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

enum PendingInteraction: Equatable {
    case approval(PendingApproval)
    case prompt(PendingPrompt)

    var identity: String {
        switch self {
        case .approval(let approval):
            return "approval:\(approval.requestId)"
        case .prompt(let prompt):
            return "\(prompt.kind):\(prompt.requestId)"
        }
    }
}

struct PendingInteractionQueue {
    private(set) var items: [PendingInteraction] = []

    var first: PendingInteraction? { items.first }

    mutating func enqueue(_ interaction: PendingInteraction) {
        items.removeAll { $0.identity == interaction.identity }
        items.append(interaction)
    }

    mutating func remove(_ interaction: PendingInteraction) {
        items.removeAll { $0.identity == interaction.identity }
    }

    mutating func clear() {
        items.removeAll()
    }
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
    private(set) var persistenceWarning: String?
    private(set) var busy = false
    private(set) var pendingApproval: PendingApproval?
    private(set) var pendingPrompt: PendingPrompt?
    private(set) var sessionReady = false
    private(set) var sessionError: String?

    let api: GatewayAPI
    private(set) var storedSessionId: String?
    private(set) var sessionId: String?
    private var unsubscribe: (() -> Void)?
    private var pendingEvents: [GatewayEvent] = []
    private var interactionQueue = PendingInteractionQueue()
    private var bootstrapGeneration = 0
    private var starting = false

    static func approval(from event: GatewayEvent) -> PendingApproval? {
        guard
            let requestId = event.payload["request_id"] as? String,
            !requestId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return PendingApproval(
            command: event.payload["command"] as? String,
            requestId: requestId,
            summary: (event.payload["summary"] as? String)
                ?? (event.payload["description"] as? String)
        )
    }

    init(api: GatewayAPI, resumeStoredSessionId: String?) {
        self.api = api
        self.storedSessionId = resumeStoredSessionId
    }

    private func enqueueInteraction(_ interaction: PendingInteraction) {
        interactionQueue.enqueue(interaction)
        publishActiveInteraction()
    }

    private func removeInteraction(_ interaction: PendingInteraction) {
        interactionQueue.remove(interaction)
        publishActiveInteraction()
    }

    private func clearInteractions() {
        interactionQueue.clear()
        publishActiveInteraction()
    }

    private func publishActiveInteraction() {
        pendingApproval = nil
        pendingPrompt = nil
        guard let interaction = interactionQueue.first else { return }
        switch interaction {
        case .approval(let approval):
            pendingApproval = approval
        case .prompt(let prompt):
            pendingPrompt = prompt
        }
    }

    func start() async {
        guard sessionId == nil, !starting else { return }
        starting = true
        bootstrapGeneration += 1
        let generation = bootstrapGeneration
        defer {
            if generation == bootstrapGeneration { starting = false }
        }
        subscribeToEvents()
        do {
            let restoring = storedSessionId != nil
            let live: LiveSession
            if let storedSessionId {
                live = try await api.resumeSession(storedSessionId: storedSessionId)
            } else {
                live = try await api.createSession()
            }
            guard generation == bootstrapGeneration, !Task.isCancelled else { return }
            guard !live.sessionId.isEmpty else {
                pendingEvents.removeAll()
                sessionError = "Gateway returned no session id."
                return
            }
            guard let durableId = live.storedSessionId, !durableId.isEmpty else {
                pendingEvents.removeAll()
                sessionError = "Gateway returned no durable session key. Check Active sessions before starting another chat."
                return
            }
            storedSessionId = durableId
            if restoring {
                messages = Self.restoredMessages(from: live)
                busy = live.running
            }
            sessionId = live.sessionId
            let events = Self.eventsForReplay(
                pendingEvents,
                live: live,
                restoredMessages: messages
            ) + live.pendingInteractions
            pendingEvents.removeAll()
            for event in events {
                handle(event)
            }
            sessionReady = true
            sessionError = nil
        } catch {
            guard generation == bootstrapGeneration, !Task.isCancelled else { return }
            pendingEvents.removeAll()
            sessionError = storedSessionId == nil
                ? "Session creation outcome is unknown. Check Active sessions before starting another chat."
                : error.localizedDescription
        }
    }

    func connectionDidClose() {
        bootstrapGeneration += 1
        starting = false
        sessionId = nil
        sessionReady = false
        pendingEvents.removeAll()
        clearInteractions()
        statusLine = nil
    }

    func resumeAfterReconnect() async {
        guard let storedSessionId, !storedSessionId.isEmpty, !starting else {
            if self.storedSessionId == nil {
                sessionError = "Session creation outcome is unknown. Check Active sessions before starting another chat."
            }
            return
        }

        if sessionId != nil {
            connectionDidClose()
        }
        starting = true
        bootstrapGeneration += 1
        let generation = bootstrapGeneration
        defer {
            if generation == bootstrapGeneration { starting = false }
        }
        subscribeToEvents()

        do {
            let live = try await api.resumeSession(storedSessionId: storedSessionId)
            guard generation == bootstrapGeneration, !Task.isCancelled else { return }
            guard !live.sessionId.isEmpty,
                  let durableId = live.storedSessionId,
                  !durableId.isEmpty else {
                pendingEvents.removeAll()
                sessionError = "Gateway returned an invalid resume snapshot."
                return
            }

            let restored = Self.restoredMessages(from: live)
            messages = restored
            busy = live.running
            clearInteractions()
            statusLine = nil
            self.storedSessionId = durableId
            sessionId = live.sessionId
            let events = Self.eventsForReplay(
                pendingEvents,
                live: live,
                restoredMessages: restored
            ) + live.pendingInteractions
            pendingEvents.removeAll()
            for event in events { handle(event) }
            sessionReady = true
            sessionError = nil
        } catch {
            guard generation == bootstrapGeneration, !Task.isCancelled else { return }
            pendingEvents.removeAll()
            sessionError = error.localizedDescription
        }
    }

    func stop() {
        bootstrapGeneration += 1
        starting = false
        unsubscribe?()
        unsubscribe = nil
        pendingEvents.removeAll()
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
        guard let sessionId, let approval = pendingApproval else { return }
        let interaction = PendingInteraction.approval(approval)
        let generation = bootstrapGeneration
        do {
            try await api.respondToApproval(
                sessionId: sessionId,
                requestId: approval.requestId,
                choice: allow ? "allow" : "deny"
            )
            guard generation == bootstrapGeneration else { return }
            removeInteraction(interaction)
        } catch {
            guard generation == bootstrapGeneration else { return }
            messages.append(TranscriptMessage(role: .system, text: "Approval reply failed: \(error.localizedDescription)"))
        }
    }

    /// Answer the pending clarify/sudo/secret prompt. An empty answer is a
    /// valid "dismiss" (the server releases the wait with an empty string).
    func respondToPrompt(_ answer: String) async {
        guard let prompt = pendingPrompt else { return }
        let interaction = PendingInteraction.prompt(prompt)
        let generation = bootstrapGeneration
        do {
            switch prompt.kind {
            case .clarify:
                try await api.respondToClarify(requestId: prompt.requestId, answer: answer)
            case .sudo:
                try await api.respondToSudo(requestId: prompt.requestId, password: answer)
            case .secret:
                try await api.respondToSecret(requestId: prompt.requestId, value: answer)
            }
            guard generation == bootstrapGeneration else { return }
            removeInteraction(interaction)
        } catch {
            guard generation == bootstrapGeneration else { return }
            messages.append(TranscriptMessage(role: .system, text: "Prompt reply failed: \(error.localizedDescription)"))
        }
    }

    // MARK: - Event folding

    private func subscribeToEvents() {
        guard unsubscribe == nil else { return }
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
        guard sessionId != nil else {
            // `session.resume` and live events share one socket. Buffer anything
            // that arrives while the resume RPC is in flight, then replay it
            // after the stored transcript is installed so history is not
            // overwritten and live deltas are not lost.
            pendingEvents.append(event)
            return
        }
        // Events carry the runtime session id; ignore other sessions' traffic.
        if let eventSession = event.sessionId, let ours = sessionId, eventSession != ours {
            return
        }

        switch event.type {
        case "message.start":
            busy = true
            statusLine = nil
            clearInteractions()
            messages.append(TranscriptMessage(role: .assistant, text: "", streaming: true))

        case "message.delta":
            guard let text = event.payloadText else { return }
            appendToStreamingAssistant(text)

        case "message.complete":
            busy = false
            statusLine = nil
            if var last = messages.last, last.role == .assistant, last.streaming {
                // The complete frame is authoritative. This also repairs a
                // resumed in-flight turn when deltas emitted before reconnect
                // are absent from the local streaming buffer.
                if let text = event.payloadText, !text.isEmpty {
                    last.text = text
                }
                last.streaming = false
                messages[messages.count - 1] = last
            } else if let text = event.payloadText, !text.isEmpty {
                messages.append(TranscriptMessage(role: .assistant, text: text))
            }
            if event.payload["history_persisted"] is Bool {
                persistenceWarning = Self.persistenceWarning(from: event)
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
            guard let approval = Self.approval(from: event) else { return }
            enqueueInteraction(.approval(approval))

        case "clarify.request":
            guard let requestId = event.payload["request_id"] as? String else { return }
            enqueueInteraction(.prompt(PendingPrompt(
                kind: .clarify,
                requestId: requestId,
                question: event.payload["question"] as? String ?? "The agent has a question.",
                choices: event.payload["choices"] as? [String] ?? []
            )))

        case "sudo.request":
            guard let requestId = event.payload["request_id"] as? String else { return }
            enqueueInteraction(.prompt(PendingPrompt(
                kind: .sudo,
                requestId: requestId,
                question: event.payload["prompt"] as? String ?? "Administrator password requested.",
                choices: []
            )))

        case "secret.request":
            guard let requestId = event.payload["request_id"] as? String else { return }
            enqueueInteraction(.prompt(PendingPrompt(
                kind: .secret,
                requestId: requestId,
                question: event.payload["prompt"] as? String ?? "A secret value was requested.",
                choices: []
            )))

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

    static func restoredMessages(from live: LiveSession) -> [TranscriptMessage] {
        var restored = live.messages.compactMap(TranscriptMessage.init(restoring:))
        if let inflight = live.inflight {
            if !inflight.user.isEmpty {
                restored.append(TranscriptMessage(role: .user, text: inflight.user))
            }
            if !inflight.assistant.isEmpty || inflight.streaming {
                restored.append(TranscriptMessage(
                    role: .assistant,
                    text: inflight.assistant,
                    streaming: inflight.streaming
                ))
            }
        }
        return restored
    }

    static func persistenceWarning(from event: GatewayEvent) -> String? {
        guard event.payload["history_persisted"] as? Bool == false else { return nil }
        if let warning = event.payload["warning"] as? String {
            let trimmed = warning.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { return trimmed }
        }
        return "This response completed but could not be saved to session history."
    }

    /// Remove only stream frames already represented by the resume snapshot.
    /// This is boundary-scoped; identical replies from separate turns remain.
    static func eventsForReplay(
        _ events: [GatewayEvent],
        live: LiveSession,
        restoredMessages: [TranscriptMessage]
    ) -> [GatewayEvent] {
        if live.inflight != nil {
            var completingSnapshotTurn = true
            return events.filter { event in
                guard event.sessionId == nil || event.sessionId == live.sessionId else { return true }
                guard completingSnapshotTurn else { return true }
                switch event.type {
                case "message.start", "message.delta":
                    return false
                case "message.complete":
                    completingSnapshotTurn = false
                    return true
                default:
                    return true
                }
            }
        }

        let bufferedTurnTypes = Set([
            "approval.request", "clarify.request", "message.delta", "message.start",
            "reasoning.available", "reasoning.delta", "secret.request", "status.update",
            "sudo.request", "thinking.delta", "tool.complete", "tool.generating",
            "tool.progress", "tool.start",
        ])
        var replay: [GatewayEvent] = []
        var turn: [GatewayEvent] = []

        func flushTurn() {
            replay.append(contentsOf: turn)
            turn.removeAll(keepingCapacity: true)
        }

        for event in events {
            guard event.sessionId == nil || event.sessionId == live.sessionId else {
                replay.append(event)
                continue
            }

            if event.type == "message.complete" {
                let covered: Bool
                if let snapshotVersion = live.historyVersion,
                   event.payload["history_persisted"] as? Bool == true,
                   let eventVersion = (event.payload["history_version"] as? NSNumber)?.intValue {
                    covered = eventVersion <= snapshotVersion
                } else {
                    covered = false
                }

                if covered {
                    turn.removeAll(keepingCapacity: true)
                    continue
                }
                flushTurn()
                replay.append(event)
                continue
            }

            if bufferedTurnTypes.contains(event.type) {
                turn.append(event)
            } else {
                flushTurn()
                replay.append(event)
            }
        }

        flushTurn()
        return replay
    }
}
