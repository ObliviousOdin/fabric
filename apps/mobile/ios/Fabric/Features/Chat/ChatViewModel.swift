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

    var responseMethod: String {
        switch kind {
        case .clarify: return "clarify.respond"
        case .sudo: return "sudo.respond"
        case .secret: return "secret.respond"
        }
    }
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

/// One user intent awaiting a durable create receipt. Its stable key is held
/// only in memory so a timeout/reconnect retry cannot create a second Job.
private struct PendingDurableBackgroundMutation: Equatable {
    let text: String
    let title: String
    let idempotencyKey: String
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
    /// Server-issued Work namespace that fences durable background mutations
    /// and the in-memory Job recovery path. It does not render a Work UI.
    private(set) var workIdentity: FabricWorkSessionIdentity?
    /// Sanitized public Job after-states keyed by their server-issued IDs.
    /// This is intentionally in-memory until the Work projection UI lands.
    private(set) var durableBackgroundJobs: [String: FabricWorkJobSummary] = [:]
    /// Reference-only current Work state. It is populated exclusively by
    /// validated bootstrap/delta pages, never by an event hint.
    private(set) var durableWorkProjection: FabricWorkProjection?

    let api: GatewayAPI
    private(set) var storedSessionId: String?
    private(set) var sessionId: String?
    private var unsubscribe: (() -> Void)?
    private var pendingEvents: [GatewayEvent] = []
    private var interactionQueue = PendingInteractionQueue()
    private var bootstrapGeneration = 0
    private var starting = false
    private let supportsMethod: (String) -> Bool
    private let durableWorkNegotiation: () -> GatewayCapabilityNegotiation?
    private let workGatewayID: () -> String?
    private var pendingDurableBackgroundMutations: [PendingDurableBackgroundMutation] = []
    private var workSyncInFlight = false
    private var workSyncNeedsAnotherPass = false

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

    init(
        api: GatewayAPI,
        resumeStoredSessionId: String?,
        supportsMethod: @escaping (String) -> Bool,
        durableWorkNegotiation: @escaping () -> GatewayCapabilityNegotiation? = { nil },
        workGatewayID: @escaping () -> String? = { nil }
    ) {
        self.api = api
        self.storedSessionId = resumeStoredSessionId
        self.supportsMethod = supportsMethod
        self.durableWorkNegotiation = durableWorkNegotiation
        self.workGatewayID = workGatewayID
    }

    func supportsGatewayMethod(_ method: String) -> Bool {
        supportsMethod(method)
    }

    /// A durable-capable gateway never falls through to `prompt.background`.
    /// The server-issued Work profile identity is also required before this
    /// client can bind a Job to the current session scope.
    var canSendInBackground: Bool {
        if durableWorkNegotiation()?.supportsDurableWork == true {
            return workIdentity != nil
        }
        return supportsMethod("prompt.background")
    }

    private func canCall(_ method: String, action: String) -> Bool {
        guard supportsMethod(method) else {
            messages.append(TranscriptMessage(
                role: .system,
                text: "\(action) is unavailable on this gateway."
            ))
            return false
        }
        return true
    }

    private func installWorkIdentity(_ identity: FabricWorkSessionIdentity?) {
        // A gateway profile change is a new Work namespace. Do not show or
        // refresh Job IDs that were learned under the previous one.
        if workIdentity?.profileID != identity?.profileID {
            durableBackgroundJobs.removeAll()
            durableWorkProjection = nil
            // A raw prompt retry must never cross the server-issued profile
            // boundary. The user can submit a new intent after a profile
            // change, with a new idempotency key.
            pendingDurableBackgroundMutations.removeAll()
        }
        workIdentity = identity
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
        let method = storedSessionId == nil ? "session.create" : "session.resume"
        guard supportsMethod(method) else {
            sessionError = "This gateway does not support the required \(method) control."
            return
        }
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
            installWorkIdentity(live.workIdentity)
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
            Task { [weak self] in
                await self?.retryPendingDurableBackgroundMutations()
                await self?.syncDurableWork()
                await self?.refreshDurableBackgroundJobs()
            }
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
        guard supportsMethod("session.resume") else {
            sessionError = "This gateway does not support session.resume."
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
            installWorkIdentity(live.workIdentity)
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
            Task { [weak self] in
                await self?.retryPendingDurableBackgroundMutations()
                await self?.syncDurableWork()
                await self?.refreshDurableBackgroundJobs()
            }
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
        // Never retain raw background prompt text after this chat surface is
        // discarded. Durable public Job summaries remain server-authoritative.
        pendingDurableBackgroundMutations.removeAll()
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

        guard canCall("prompt.submit", action: "Sending messages") else { return }
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
        guard canCall("session.steer", action: "Steering") else { return }
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
        guard canCall("slash.exec", action: "Slash commands") else { return }
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

    /// Run the text as a detached background task. On a truthfully advertised
    /// Work gateway this is an idempotent `job.create`; legacy
    /// `prompt.background` remains only for gateways that do not advertise
    /// Durable Work at all.
    func sendInBackground(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let sessionId, !trimmed.isEmpty else { return }
        if let negotiation = durableWorkNegotiation(), negotiation.supportsDurableWork {
            guard workIdentity != nil else {
                messages.append(TranscriptMessage(
                    role: .system,
                    text: "Durable background work is unavailable until this session provides a valid Work profile identity."
                ))
                return
            }
            await submitDurableBackgroundWork(
                sessionID: sessionId,
                text: trimmed,
                negotiation: negotiation
            )
            return
        }

        guard canCall("prompt.background", action: "Background work") else { return }
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

    private func submitDurableBackgroundWork(
        sessionID: String,
        text: String,
        negotiation: GatewayCapabilityNegotiation
    ) async {
        let title = "Background work"
        let existing = pendingDurableBackgroundMutations.first {
            $0.text == text && $0.title == title
        }
        let mutation = existing ?? PendingDurableBackgroundMutation(
            text: text,
            title: title,
            idempotencyKey: UUID().uuidString
        )
        if existing == nil {
            pendingDurableBackgroundMutations.append(mutation)
            messages.append(TranscriptMessage(role: .user, text: text))
        }

        do {
            let receipt = try await api.createBackgroundWork(
                sessionID: sessionID,
                text: mutation.text,
                title: mutation.title,
                idempotencyKey: mutation.idempotencyKey,
                negotiation: negotiation
            )
            pendingDurableBackgroundMutations.removeAll {
                $0.idempotencyKey == mutation.idempotencyKey
            }
            durableBackgroundJobs[receipt.job.jobID] = receipt.job
            Task { [weak self] in
                await self?.syncDurableWork()
            }
            let taskID = receipt.taskID ?? receipt.job.runtimeSessionID
            messages.append(TranscriptMessage(
                role: .info,
                text: "Background Job started \(receipt.job.jobID)\(taskID.map { " (\($0))" } ?? "")."
            ))
        } catch {
            // Preserve the exact idempotency key only when the outcome may be
            // unknown. A later explicit retry replays the original receipt
            // instead of creating a duplicate Job. Never fall back to the
            // legacy RPC after this durable attempt.
            if !Self.mayNeedDurableBackgroundRetry(error) {
                pendingDurableBackgroundMutations.removeAll {
                    $0.idempotencyKey == mutation.idempotencyKey
                }
            }
            messages.append(TranscriptMessage(
                role: .system,
                text: "Background Job failed: \(error.localizedDescription)"
            ))
        }
    }

    private func refreshDurableBackgroundJobs() async {
        guard let sessionId,
              workIdentity != nil,
              let negotiation = durableWorkNegotiation(),
              negotiation.supportsDurableWork
        else { return }
        let generation = bootstrapGeneration
        let jobIDs = Array(durableBackgroundJobs.keys)
        for jobID in jobIDs {
            do {
                let job = try await api.getWorkJob(
                    sessionID: sessionId,
                    jobID: jobID,
                    negotiation: negotiation
                )
                guard generation == bootstrapGeneration, self.sessionId == sessionId else { return }
                durableBackgroundJobs[jobID] = job
            } catch {
                // The ledger remains authoritative; leave the last sanitized
                // after-state visible until a later Work event/reconnect can
                // refresh it. Do not turn a refresh failure into legacy work.
            }
        }
    }

    private func retryPendingDurableBackgroundMutations() async {
        guard let sessionId,
              workIdentity != nil,
              let negotiation = durableWorkNegotiation(),
              negotiation.supportsDurableWork
        else { return }
        // Snapshot before awaiting: a receipt removes the matching mutation.
        let mutations = pendingDurableBackgroundMutations
        for mutation in mutations {
            await submitDurableBackgroundWork(
                sessionID: sessionId,
                text: mutation.text,
                negotiation: negotiation
            )
        }
    }

    /// Bootstrap or advance the one fenced Work projection for this chat. A
    /// `work.changed` event only calls this method; it never supplies state.
    private func syncDurableWork() async {
        guard let sessionId,
              let identity = workIdentity,
              let gatewayID = workGatewayID(),
              let scope = identity.syncScope(gatewayID: gatewayID),
              let negotiation = durableWorkNegotiation(),
              negotiation.supportsDurableWork
        else { return }

        if workSyncInFlight {
            workSyncNeedsAnotherPass = true
            return
        }
        workSyncInFlight = true
        defer {
            workSyncInFlight = false
            if workSyncNeedsAnotherPass {
                workSyncNeedsAnotherPass = false
                Task { [weak self] in
                    await self?.syncDurableWork()
                }
            }
        }

        do {
            var state: FabricWorkProjection
            if let existing = durableWorkProjection,
               existing.gatewayID == scope.gatewayID,
               existing.profileID == scope.profileID {
                state = existing
            } else {
                state = try FabricWorkProjectionReducer.create(scope: scope)
            }
            var mode: FabricWorkProjectionPhase =
                state.phase == .empty || state.phase == .bootstrapping ? .bootstrapping : .syncing
            var pages = 0

            while pages < 1_000 {
                pages += 1
                let response: FabricWorkGatewayResponse
                let context: FabricWorkSyncRequestContext
                switch mode {
                case .bootstrapping:
                    let token = state.nextPageToken
                    context = FabricWorkSyncRequestContext(scope: scope, pageToken: token)
                    response = try await api.syncWork(
                        sessionID: sessionId,
                        request: .bootstrap(pageToken: token, limit: FabricWorkLimits.syncPageItems),
                        negotiation: negotiation
                    )
                case .syncing:
                    guard let ledgerID = state.ledgerID, let cursor = state.cursor else {
                        mode = .bootstrapping
                        continue
                    }
                    context = FabricWorkSyncRequestContext(scope: scope, after: cursor)
                    response = try await api.syncWork(
                        sessionID: sessionId,
                        request: .delta(
                            ledgerID: ledgerID,
                            after: cursor,
                            limit: FabricWorkLimits.syncPageItems
                        ),
                        negotiation: negotiation
                    )
                case .empty, .current:
                    // This local state machine uses only bootstrap/syncing.
                    return
                }

                switch response {
                case .page(let page):
                    state = try FabricWorkProjectionReducer.apply(state, page: page, context: context)
                    durableWorkProjection = state
                    refreshKnownJobStates(from: state)
                    if state.phase == .current { return }
                    mode = page.mode == "bootstrap" ? .bootstrapping : .syncing
                case .reset(let reset):
                    state = try FabricWorkProjectionReducer.applyCursorReset(
                        state,
                        reset: reset,
                        scope: scope
                    )
                    durableWorkProjection = state
                    durableBackgroundJobs.removeAll()
                    mode = .bootstrapping
                }
            }
        } catch {
            // A malformed page/RPC failure never updates `state` outside the
            // reducer. Later event hints or reconnect recovery retry safely.
        }
    }

    private func refreshKnownJobStates(from projection: FabricWorkProjection) {
        for jobID in Array(durableBackgroundJobs.keys) {
            if let job = projection.jobs[jobID] {
                durableBackgroundJobs[jobID] = job
            }
        }
    }

    private static func mayNeedDurableBackgroundRetry(_ error: Error) -> Bool {
        guard let gatewayError = error as? GatewayClientError else { return false }
        switch gatewayError {
        case .notConnected, .connectFailed, .socketClosed, .requestTimedOut:
            return true
        case .rpc(_, _, let data):
            return (data as? [String: Any])?["retryable"] as? Bool == true
        }
    }

    func interrupt() async {
        guard canCall("session.interrupt", action: "Interrupting a turn") else { return }
        guard let sessionId else { return }
        try? await api.interrupt(sessionId: sessionId)
    }

    func respondToApproval(allow: Bool) async {
        guard canCall("approval.respond", action: "Approval responses") else { return }
        guard let sessionId, let approval = pendingApproval else { return }
        let interaction = PendingInteraction.approval(approval)
        let generation = bootstrapGeneration
        do {
            try await api.respondToApproval(
                sessionId: sessionId,
                requestId: approval.requestId,
                choice: allow ? "once" : "deny"
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
        guard let sessionId, let prompt = pendingPrompt else { return }
        guard canCall(prompt.responseMethod, action: "Prompt responses") else { return }
        let interaction = PendingInteraction.prompt(prompt)
        let generation = bootstrapGeneration
        do {
            switch prompt.kind {
            case .clarify:
                try await api.respondToClarify(
                    sessionId: sessionId,
                    requestId: prompt.requestId,
                    answer: answer
                )
            case .sudo:
                try await api.respondToSudo(
                    sessionId: sessionId,
                    requestId: prompt.requestId,
                    password: answer
                )
            case .secret:
                try await api.respondToSecret(
                    sessionId: sessionId,
                    requestId: prompt.requestId,
                    value: answer
                )
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
        case "session.info":
            // A refreshed snapshot may carry a new profile namespace. If the
            // gateway provides an invalid *or missing* one, fail closed by
            // clearing the old binding rather than retaining a stale profile
            // namespace. A legacy gateway cannot manufacture a Work identity.
            installWorkIdentity(FabricWorkSessionIdentity.from(sessionInfo: event.payload))

        case "work.changed":
            // A hint never mutates local Job state by itself. It only wakes a
            // typed bootstrap/delta reconciliation; the helper applies its
            // own capability, session, and profile-identity gates.
            Task { [weak self] in
                await self?.syncDurableWork()
                await self?.refreshDurableBackgroundJobs()
            }

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
            guard
                let requestId = event.payload["request_id"] as? String,
                !requestId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }
            enqueueInteraction(.prompt(PendingPrompt(
                kind: .clarify,
                requestId: requestId,
                question: event.payload["question"] as? String ?? "The agent has a question.",
                choices: event.payload["choices"] as? [String] ?? []
            )))

        case "sudo.request":
            guard
                let requestId = event.payload["request_id"] as? String,
                !requestId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }
            enqueueInteraction(.prompt(PendingPrompt(
                kind: .sudo,
                requestId: requestId,
                question: event.payload["prompt"] as? String ?? "Administrator password requested.",
                choices: []
            )))

        case "secret.request":
            guard
                let requestId = event.payload["request_id"] as? String,
                !requestId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }
            enqueueInteraction(.prompt(PendingPrompt(
                kind: .secret,
                requestId: requestId,
                question: event.payload["prompt"] as? String ?? "A secret value was requested.",
                choices: []
            )))

        case "background.complete":
            let taskId = event.payload["task_id"] as? String
            let jobID = event.payload["job_id"] as? String
            let text = event.payloadText ?? ""
            messages.append(TranscriptMessage(
                role: .info,
                text: "Background task\(taskId.map { " \($0)" } ?? "") finished:\n\(text)"
            ))
            if let jobID, durableBackgroundJobs[jobID] != nil {
                Task { [weak self] in
                    await self?.syncDurableWork()
                    await self?.refreshDurableBackgroundJobs()
                }
            }

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
