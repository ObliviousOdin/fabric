import SwiftUI

/// Chat transcript + composer for one Fabric session.
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

    private func approvalBanner(_ approval: PendingApproval) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Approval requested", systemImage: "hand.raised")
                .font(.subheadline.weight(.semibold))
            if let command = approval.command, !command.isEmpty {
                Text(command)
                    .font(.caption.monospaced())
                    .lineLimit(4)
            }
            HStack {
                Button("Deny", role: .destructive) {
                    Task { await model.respondToApproval(allow: false) }
                }
                .buttonStyle(.bordered)
                Button("Allow") {
                    Task { await model.respondToApproval(allow: true) }
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(.yellow.opacity(0.15))
    }

    private var composer: some View {
        HStack(spacing: 8) {
            TextField("Message Fabric…", text: $draft, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...5)
                .disabled(!model.sessionReady)

            if model.busy {
                Button {
                    Task { await model.interrupt() }
                } label: {
                    Image(systemName: "stop.circle.fill")
                        .font(.title2)
                }
            } else {
                Button {
                    let text = draft
                    draft = ""
                    Task { await model.send(text) }
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title2)
                }
                .disabled(
                    !model.sessionReady
                        || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
            }
        }
        .padding()
    }
}

private struct MessageBubble: View {
    let message: TranscriptMessage

    var body: some View {
        switch message.role {
        case .user:
            HStack {
                Spacer(minLength: 40)
                Text(message.text)
                    .padding(10)
                    .background(Color.accentColor.opacity(0.9))
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
            }
        case .assistant:
            HStack {
                Text(message.text.isEmpty && message.streaming ? "…" : message.text)
                    .padding(10)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 14))
                Spacer(minLength: 40)
            }
        case .system:
            Text(message.text)
                .font(.caption)
                .foregroundStyle(.red)
                .frame(maxWidth: .infinity, alignment: .center)
        }
    }
}
