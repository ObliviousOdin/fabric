import SwiftUI

/// Session picker: live gateway sessions (`session.active_list`) with
/// remote-control actions on top, the historical `session.list` below.
struct SessionListView: View {
    @Environment(AppModel.self) private var appModel

    @State private var sessions: [SessionSummary] = []
    @State private var activeSessions: [ActiveSession] = []
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

            if !activeSessions.isEmpty {
                Section("Active now") {
                    ForEach(activeSessions) { session in
                        NavigationLink {
                            ChatView(
                                resumeStoredSessionId: session.sessionKey,
                                title: session.title.isEmpty ? "Untitled session" : session.title
                            )
                        } label: {
                            ActiveSessionRow(session: session)
                        }
                        .swipeActions {
                            if session.status == "working" || session.status == "starting" {
                                Button(role: .destructive) {
                                    Task {
                                        try? await appModel.api.interrupt(sessionId: session.id)
                                        await reload()
                                    }
                                } label: {
                                    Label("Interrupt", systemImage: "stop.circle")
                                }
                            }
                        }
                    }
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
        .navigationTitle(appModel.activeGateway?.label ?? "Sessions")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    // disconnect() returns to the gateway library, which is
                    // the server switcher — pick another saved server there.
                    Button {
                        appModel.disconnect()
                    } label: {
                        Label("Switch server", systemImage: "arrow.left.arrow.right")
                    }
                    Button(role: .destructive) {
                        appModel.disconnect()
                    } label: {
                        Label("Disconnect", systemImage: "bolt.horizontal")
                    }
                } label: {
                    Image(systemName: "server.rack")
                }
                .accessibilityLabel("Server menu")
            }
        }
        .refreshable {
            if appModel.phase == .connected { await reload() }
        }
        .task(id: appModel.connectionGeneration) {
            if appModel.phase == .connected { await reload() }
        }
    }

    private func reload() async {
        loading = true
        defer { loading = false }
        do {
            // These RPCs are independent. Loading them concurrently avoids
            // making the initial sessions screen pay two network round trips.
            async let recent: [SessionSummary] = appModel.api.listSessions()
            async let active: [ActiveSession]? = try? appModel.api.activeSessions()
            let (loadedSessions, loadedActiveSessions) = try await (recent, active)
            sessions = loadedSessions
            // Live sessions are best-effort decoration; the historical list
            // is the primary content.
            activeSessions = loadedActiveSessions ?? []
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }
}

/// A live gateway session reopened through its stable stored-session key.
/// Running sessions expose interrupt as a row swipe action.
private struct ActiveSessionRow: View {
    let session: ActiveSession

    // Contract status language: working rides the active-thread purple,
    // waiting is amber, starting is info; idle stays neutral.
    private var statusColor: Color {
        FabricTheme.sessionStatusColor(session.status)
    }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Circle()
                        .fill(statusColor)
                        .frame(width: 8, height: 8)
                    Text(session.title.isEmpty ? "Untitled session" : session.title)
                        .lineLimit(1)
                }
                if !session.preview.isEmpty {
                    Text(session.preview)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                HStack(spacing: 8) {
                    Text(session.status)
                    if !session.model.isEmpty {
                        Text(session.model)
                    }
                    Text("\(session.messageCount) messages")
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }
}
