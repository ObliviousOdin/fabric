import SwiftUI

/// Chat transcript + composer for one Fabric session, with the same
/// dispatch/remote-control surface the TUI composer exposes: slash
/// commands, steering, background tasks, and process control.
struct ChatView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    let resumeStoredSessionId: String?
    let title: String
    let onInitialPromptAttempted: () -> Void

    @State private var model: ChatViewModel?
    @State private var draft = ""
    @State private var initialPromptDispatch: InitialPromptDispatch

    init(
        resumeStoredSessionId: String?,
        title: String,
        initialPrompt: String? = nil,
        onInitialPromptAttempted: @escaping () -> Void = {}
    ) {
        self.resumeStoredSessionId = resumeStoredSessionId
        self.title = title
        self.onInitialPromptAttempted = onInitialPromptAttempted
        _initialPromptDispatch = State(
            initialValue: InitialPromptDispatch(prompt: initialPrompt)
        )
    }

    var body: some View {
        Group {
            if let model {
                ChatContentView(
                    model: model,
                    draft: $draft,
                    recoveryAction: SessionRecoveryAction(
                        storedSessionId: model.storedSessionId
                    ),
                    onRetrySession: {
                        Task { await retrySession(using: model) }
                    },
                    onReturnToConversations: { dismiss() }
                )
            } else {
                ProgressView()
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .task(id: appModel.connectionGeneration) {
            if model == nil {
                let vm = ChatViewModel(
                    api: appModel.api,
                    resumeStoredSessionId: resumeStoredSessionId,
                    supportsMethod: { method in
                        appModel.supportsGatewayMethod(method)
                    },
                    durableWorkNegotiation: {
                        appModel.capabilityNegotiation
                    },
                    workGatewayID: {
                        appModel.activeGatewayId
                    }
                )
                model = vm
                await vm.start()
                await dispatchInitialPromptIfReady(using: vm)
            } else if appModel.phase == .connected {
                if let model {
                    await model.resumeAfterReconnect()
                    await dispatchInitialPromptIfReady(using: model)
                }
            }
        }
        .onChange(of: appModel.phase) { oldPhase, newPhase in
            if oldPhase == .connected, newPhase != .connected {
                model?.connectionDidClose()
            }
        }
        .onDisappear {
            model?.stop()
        }
        .toolbar(.visible, for: .navigationBar)
    }

    private func dispatchInitialPromptIfReady(using model: ChatViewModel) async {
        guard let prompt = initialPromptDispatch.beginIfReady(
            model.canSubmitInitialPrompt,
            onAttempt: onInitialPromptAttempted
        ) else { return }
        // `prompt.submit` is not idempotent. Consume this launch intent before
        // awaiting the network so reconnect/task re-entry cannot submit the
        // same user goal twice. If session bootstrap was interrupted after its
        // durable key was issued, the first successful resume still gets the
        // launch prompt.
        await model.sendInitialPrompt(prompt)
    }

    private func retrySession(using model: ChatViewModel) async {
        // Creating a session is not idempotent. A failed create response can
        // mean the gateway created the session but the client missed the
        // receipt, so only a known durable key is safe to retry.
        guard model.storedSessionId != nil else { return }
        await model.resumeAfterReconnect()
        await dispatchInitialPromptIfReady(using: model)
    }
}

enum SessionRecoveryAction: Equatable {
    case retryResume
    case returnToConversations

    init(storedSessionId: String?) {
        self = storedSessionId?.isEmpty == false
            ? .retryResume
            : .returnToConversations
    }
}

/// One-shot launch intent for the conversation-first home. Keeping this as a
/// tiny value type makes the no-double-submit invariant unit-testable without
/// constructing a live WebSocket client.
struct InitialPromptDispatch: Equatable {
    private let prompt: String?
    private(set) var attempted = false

    init(prompt: String?) {
        let trimmed = prompt?.trimmingCharacters(in: .whitespacesAndNewlines)
        self.prompt = (trimmed?.isEmpty == false) ? trimmed : nil
    }

    mutating func beginIfReady(
        _ ready: Bool,
        onAttempt: () -> Void = {}
    ) -> String? {
        guard ready, !attempted, let prompt else { return nil }
        attempted = true
        // Synchronous by contract: Home clears only the matching launch draft
        // before the non-cancellable JSON-RPC await can yield or complete late.
        onAttempt()
        return prompt
    }
}

private struct ChatContentView: View {
    @Bindable var model: ChatViewModel
    @Binding var draft: String
    let recoveryAction: SessionRecoveryAction
    let onRetrySession: () -> Void
    let onReturnToConversations: () -> Void

    @State private var showCommandCatalog = false
    @State private var showProcesses = false
    @State private var showLiveView = false
    @State private var promptAnswer = ""

    var body: some View {
        VStack(spacing: 0) {
            if let warning = model.persistenceWarning {
                Label(warning, systemImage: "externaldrive.badge.exclamationmark")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.warning)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)
                    .padding(.vertical, 8)
                    .background(FabricTheme.warning.fabricTint())
            }
            if let sessionError = model.sessionError {
                VStack(spacing: 12) {
                    ContentUnavailableView(
                        "Session unavailable",
                        systemImage: "exclamationmark.triangle",
                        description: Text(sessionError)
                    )
                    switch recoveryAction {
                    case .retryResume:
                        Button("Retry session", action: onRetrySession)
                            .buttonStyle(.borderedProminent)
                            .frame(minHeight: FabricTheme.minTarget)
                    case .returnToConversations:
                        Button("Back to conversations", action: onReturnToConversations)
                            .buttonStyle(.borderedProminent)
                            .frame(minHeight: FabricTheme.minTarget)
                            .accessibilityHint("Your goal remains preserved on Home")
                    }
                }
            } else {
                transcript
            }

            if let approval = model.pendingApproval {
                approvalBanner(approval)
                    .disabled(
                        !model.sessionReady
                            || !model.supportsGatewayMethod("approval.respond")
                    )
            }

            if let prompt = model.pendingPrompt {
                promptBanner(prompt)
                    .disabled(
                        !model.sessionReady
                            || !model.supportsGatewayMethod(prompt.responseMethod)
                    )
            }

            if let status = model.statusLine {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.mini)
                    Text(status)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Spacer()
                }
                .padding(.horizontal)
                .padding(.vertical, 4)
            }

            composer
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button {
                        showCommandCatalog = true
                    } label: {
                        Label("Commands…", systemImage: "slash.circle")
                    }
                    .disabled(
                        !model.supportsGatewayMethod("commands.catalog")
                            || !model.supportsGatewayMethod("slash.exec")
                    )
                    Button {
                        let text = draft
                        draft = ""
                        Task { await model.sendInBackground(text) }
                    } label: {
                        Label("Run draft in background", systemImage: "moon.zzz")
                    }
                    .disabled(
                        draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || !model.canSendInBackground
                    )
                    Button {
                        showProcesses = true
                    } label: {
                        Label("Background processes…", systemImage: "terminal")
                    }
                    .disabled(!model.supportsGatewayMethod("process.list"))
                    Button {
                        showLiveView = true
                    } label: {
                        Label("Live screen view…", systemImage: "display")
                    }
                    .disabled(!model.supportsGatewayMethod("computer.screenshot"))
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
                .accessibilityLabel("Chat actions")
                .disabled(!model.sessionReady)
            }
        }
        .sheet(isPresented: $showCommandCatalog) {
            CommandCatalogSheet(
                api: model.api,
                supportsMethod: model.supportsGatewayMethod
            ) { command in
                draft = command + " "
                showCommandCatalog = false
            }
        }
        .sheet(isPresented: $showProcesses) {
            ProcessListSheet(
                api: model.api,
                sessionId: model.sessionId,
                supportsMethod: model.supportsGatewayMethod
            )
        }
        .sheet(isPresented: $showLiveView) {
            LiveViewSheet(api: model.api, supportsMethod: model.supportsGatewayMethod)
        }
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(model.messages) { message in
                        MessageBubble(message: message)
                            .id(message.id)
                    }
                }
                .padding()
            }
            .onChange(of: model.messages) {
                if let lastId = model.messages.last?.id {
                    proxy.scrollTo(lastId, anchor: .bottom)
                }
            }
        }
    }

    /// Waiting-for-approval banner. Status language per the design contract:
    /// an amber marker + explicit label, with the status color held to a
    /// tint and an edge marker — never a fully saturated panel.
    private func approvalBanner(_ approval: PendingApproval) -> some View {
        HStack(spacing: 0) {
            Rectangle()
                .fill(FabricTheme.warning)
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Circle()
                        .fill(FabricTheme.warning)
                        .frame(width: 8, height: 8)
                    Text("Waiting for approval")
                        .font(.subheadline.weight(.semibold))
                }
                if let command = approval.command, !command.isEmpty {
                    Text(command)
                        .font(.caption.monospaced())
                        .lineLimit(4)
                }
                HStack {
                    Button("Allow") {
                        Task { await model.respondToApproval(allow: true) }
                    }
                    .buttonStyle(.borderedProminent)
                    Button("Deny", role: .destructive) {
                        Task { await model.respondToApproval(allow: false) }
                    }
                    .buttonStyle(.bordered)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
        .background(FabricTheme.warning.fabricTint())
        .fixedSize(horizontal: false, vertical: true)
    }

    /// Blocking agent prompt: clarify choices as buttons, plus a free-text
    /// (or secure, for sudo/secret) answer field.
    private func promptBanner(_ prompt: PendingPrompt) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(
                prompt.kind == .clarify ? "The agent has a question" : "Credential requested",
                systemImage: prompt.kind == .clarify ? "questionmark.bubble" : "key"
            )
            .font(.subheadline.weight(.semibold))

            Text(prompt.question)
                .font(.callout)

            if !prompt.choices.isEmpty {
                ForEach(prompt.choices, id: \.self) { choice in
                    Button(choice) {
                        promptAnswer = ""
                        Task { await model.respondToPrompt(choice) }
                    }
                    .buttonStyle(.bordered)
                }
            }

            HStack {
                Group {
                    if prompt.isSecureEntry {
                        SecureField("Answer", text: $promptAnswer)
                    } else {
                        TextField("Answer", text: $promptAnswer)
                    }
                }
                .textFieldStyle(.roundedBorder)

                Button("Send") {
                    let answer = promptAnswer
                    promptAnswer = ""
                    Task { await model.respondToPrompt(answer) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(promptAnswer.isEmpty)

                Button("Dismiss", role: .cancel) {
                    promptAnswer = ""
                    Task { await model.respondToPrompt("") }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(FabricTheme.info.fabricTint())
    }

    private var composer: some View {
        HStack(spacing: 8) {
            TextField(
                model.busy ? "Steer the running turn…" : "Message Fabric… (/ for commands)",
                text: $draft,
                axis: .vertical
            )
            .textFieldStyle(.roundedBorder)
            .lineLimit(1...5)
            .disabled(
                !model.sessionReady
                    || !model.supportsGatewayMethod(draftDispatchMethod)
            )

            if model.busy {
                // Steering send: injects the note without interrupting. The
                // active-thread color marks it as touching the live turn.
                Button {
                    let text = draft
                    draft = ""
                    Task { await model.send(text) }
                } label: {
                    Image(systemName: "arrow.uturn.right.circle.fill")
                        .font(.title2)
                        .foregroundStyle(FabricTheme.threadActive)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .accessibilityLabel("Steer running turn")
                .disabled(
                    draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || !model.supportsGatewayMethod("session.steer")
                )

                Button {
                    Task { await model.interrupt() }
                } label: {
                    Image(systemName: "stop.circle.fill")
                        .font(.title2)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .accessibilityLabel("Interrupt running turn")
                .disabled(!model.supportsGatewayMethod("session.interrupt"))
            } else {
                Button {
                    let text = draft
                    draft = ""
                    Task { await model.send(text) }
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title2)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .accessibilityLabel("Send message")
                .disabled(
                    !model.sessionReady
                        || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || !model.supportsGatewayMethod(draftDispatchMethod)
                )
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .disabled(!model.sessionReady)
    }

    private var draftDispatchMethod: String {
        if model.busy { return "session.steer" }
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.hasPrefix("/") ? "slash.exec" : "prompt.submit"
    }
}

private struct MessageBubble: View {
    let message: TranscriptMessage

    var body: some View {
        switch message.role {
        // Purple marks user-controlled elements (contract): the user's own
        // words are the one solid-accent surface in the transcript.
        case .user:
            HStack {
                Spacer(minLength: 40)
                Text(message.text)
                    .font(.subheadline)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(FabricTheme.action)
                    .foregroundStyle(FabricTheme.textOnBrand)
                    .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
                    .accessibilityLabel("You")
                    .accessibilityValue(message.text)
            }
        case .assistant:
            HStack {
                Text(message.text.isEmpty && message.streaming ? "…" : message.text)
                    .font(.subheadline)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(FabricTheme.surfaceRaised)
                    .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
                    .accessibilityLabel("Fabric")
                    .accessibilityValue(
                        message.text.isEmpty && message.streaming ? "Streaming response" : message.text
                    )
                Spacer(minLength: 40)
            }
        // Technical output (slash results, task notices): mono on an inset
        // surface, full width — a ledger row, not a speech bubble.
        case .info:
            Text(message.text)
                .font(.caption.monospaced())
                .foregroundStyle(FabricTheme.textMuted)
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(FabricTheme.surfaceInset)
                .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radius))
                .accessibilityLabel("Information")
                .accessibilityValue(message.text)
        // Failures read as status, not as chat: danger dot + left-aligned copy.
        case .system:
            HStack(spacing: 8) {
                Circle()
                    .fill(FabricTheme.danger)
                    .frame(width: 8, height: 8)
                Text(message.text)
                    .font(.caption)
                    .foregroundStyle(FabricTheme.danger)
                Spacer(minLength: 0)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Error")
            .accessibilityValue(message.text)
        }
    }
}
