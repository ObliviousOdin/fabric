import SwiftUI

/// Session picker backed by the `session.list` RPC: resume an existing
/// conversation or start a new one.
struct SessionListView: View {
    @Environment(AppModel.self) private var appModel

    @State private var sessions: [SessionSummary] = []
    @State private var loading = false
    @State private var loadError: String?

    var body: some View {
        List {
            Section {
                NavigationLink {
                    ChatView(resumeStoredSessionId: nil, title: "New chat")
                } label: {
                    Label("New chat", systemImage: "plus.bubble")
                }
            }

            Section("Recent sessions") {
                if loading && sessions.isEmpty {
                    ProgressView()
                } else if let loadError {
                    Text(loadError)
                        .font(.footnote)
                        .foregroundStyle(.red)
                } else if sessions.isEmpty {
                    Text("No sessions yet.")
                        .foregroundStyle(.secondary)
                }

                ForEach(sessions) { session in
                    NavigationLink {
                        ChatView(resumeStoredSessionId: session.id, title: session.displayTitle)
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(session.displayTitle)
                                .lineLimit(1)
                            HStack(spacing: 8) {
                                if session.startedAt > 0 {
                                    Text(
                                        Date(timeIntervalSince1970: session.startedAt),
                                        format: .relative(presentation: .named)
                                    )
                                }
                                if !session.source.isEmpty {
                                    Text(session.source)
                                }
                                Text("\(session.messageCount) messages")
                            }
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle("Sessions")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("Disconnect") {
                    appModel.disconnect()
                }
            }
        }
        .refreshable { await reload() }
        .task { await reload() }
    }

    private func reload() async {
        loading = true
        defer { loading = false }
        do {
            sessions = try await appModel.api.listSessions()
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }
}
