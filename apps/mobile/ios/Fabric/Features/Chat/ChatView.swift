import SwiftUI

/// Chat transcript + composer for one Fabric session, with the same
/// dispatch/remote-control surface the TUI composer exposes: slash
/// commands, steering, background tasks, and process control.
struct ChatView: View {
    @Environment(AppModel.self) private var appModel

    let resumeStoredSessionId: String?
    let title: String

    @State private var model: ChatViewModel?
    @State private var draft = ""

    var body: some View {
        Group {
            if let model {
                ChatContentView(model: model, draft: $draft)
            } else {
                ProgressView()
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if model == nil {
                let vm = ChatViewModel(
                    api: appModel.api,
                    resumeStoredSessionId: resumeStoredSessionId
                )
                model = vm
                await vm.start()
            }
        }
        .onDisappear {
            model?.stop()
        }
    }
}

private struct ChatContentView: View {
    @Bindable var model: ChatViewModel
    @Binding var draft: String

    @State private var showCommandCatalog = false
    @State private var showProcesses = false
    @State private var showLiveView = false
    @State private var promptAnswer = ""

    var body: some View {
        VStack(spacing: 0) {
            if let sessionError = model.sessionError {
                ContentUnavailableView(
                    "Session unavailable",
                    systemImage: "exclamationmark.triangle",
                    description: Text(sessionError)
                )
            } else {
                transcript
            }

            if let approval = model.pendingApproval {
                approvalBanner(approval)
            }

            if let prompt = model.pendingPrompt {
                promptBanner(prompt)
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
                    Button {
                        let text = draft
                        draft = ""
                        Task { await model.sendInBackground(text) }
                    } label: {
                        Label("Run draft in background", systemImage: "moon.zzz")
                    }
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    Button {
                        showProcesses = true
                    } label: {
                        Label("Background processes…", systemImage: "terminal")
                    }
                    Button {
                        showLiveView = true
                    } label: {
                        Label("Live screen view…", systemImage: "display")
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
                .disabled(!model.sessionReady)
            }
        }
        .sheet(isPresented: $showCommandCatalog) {
            CommandCatalogSheet(api: model.api) { command in
                draft = command + " "
                showCommandCatalog = false
            }
        }
        .sheet(isPresented: $showProcesses) {
            ProcessListSheet(api: model.api, sessionId: model.sessionId)
        }
        .sheet(isPresented: $showLiveView) {
            LiveViewSheet(api: model.api)
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
            .disabled(!model.sessionReady)

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
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                Button {
                    Task { await model.interrupt() }
                } label: {
                    Image(systemName: "stop.circle.fill")
                        .font(.title2)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
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
                .disabled(
                    !model.sessionReady
                        || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
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
            }
        case .assistant:
            HStack {
                Text(message.text.isEmpty && message.streaming ? "…" : message.text)
                    .font(.subheadline)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(FabricTheme.surfaceRaised)
                    .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
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
        }
    }
}
