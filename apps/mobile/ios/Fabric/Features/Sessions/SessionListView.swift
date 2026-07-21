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
                GatewayExecutionCard(negotiation: appModel.capabilityNegotiation)
            }

            Section {
                NavigationLink {
                    ChatView(resumeStoredSessionId: nil, title: "New chat")
                } label: {
                    Label("New chat", systemImage: "plus.bubble")
                }
                .disabled(!appModel.supportsGatewayMethod("session.create"))
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
                        .disabled(!appModel.supportsGatewayMethod("session.resume"))
                        .swipeActions {
                            if (session.status == "working" || session.status == "starting")
                                && appModel.supportsGatewayMethod("session.interrupt") {
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
                    .disabled(!appModel.supportsGatewayMethod("session.resume"))
                }
            }
        }
        .navigationTitle(appModel.activeGateway?.label ?? "Sessions")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
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
        guard appModel.supportsGatewayMethod("session.list") else {
            sessions = []
            activeSessions = []
            loadError = appModel.capabilityNegotiation?.blockingMessage
                ?? "Session listing is unavailable on this gateway."
            return
        }
        do {
            // These RPCs are independent. Loading them concurrently avoids
            // making the initial sessions screen pay two network round trips.
            async let recent: [SessionSummary] = appModel.api.listSessions()
            let loadedActiveSessions: [ActiveSession]?
            if appModel.supportsGatewayMethod("session.active_list") {
                loadedActiveSessions = try? await appModel.api.activeSessions()
            } else {
                loadedActiveSessions = []
            }
            let loadedSessions = try await recent
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

/// Process-scoped execution semantics negotiated for this live socket. This
/// card is deliberately non-dismissable: mobile is a remote control and must
/// not imply that tools execute on the phone or survive a gateway restart.
private struct GatewayExecutionCard: View {
    let negotiation: GatewayCapabilityNegotiation?

    private var presentation: (title: String, body: String, icon: String, color: Color) {
        switch negotiation {
        case .verified(let capabilities):
            return (
                "Runs on this gateway",
                "Work and tools run on the connected gateway. Active work continues if this phone disconnects, but a gateway restart interrupts it. Keep the gateway host online. Server \(capabilities.server.version).",
                "server.rack",
                FabricTheme.info
            )
        case .legacy:
            return (
                "Compatibility mode",
                "Update Fabric for verified mobile controls. The shipped mobile controls remain available, but this gateway cannot verify execution guarantees.",
                "exclamationmark.arrow.triangle.2.circlepath",
                FabricTheme.warning
            )
        case .incompatible(let minimum):
            return (
                "Mobile update required",
                "This gateway requires mobile contract \(minimum) or newer; this app supports contract \(gatewayClientContractVersion). Session controls are disabled.",
                "arrow.down.app",
                FabricTheme.danger
            )
        case .invalid(let reason):
            return (
                "Gateway contract invalid",
                "Session controls are disabled: \(reason)",
                "exclamationmark.shield",
                FabricTheme.danger
            )
        case .negotiating:
            return (
                "Checking gateway capabilities…",
                "Session controls unlock after the authenticated gateway contract is verified.",
                "checkmark.shield",
                FabricTheme.info
            )
        case nil:
            return (
                "Gateway capabilities unavailable",
                "Reconnect to verify which mobile controls this gateway supports.",
                "wifi.exclamationmark",
                FabricTheme.warning
            )
        }
    }

    var body: some View {
        let presentation = presentation
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: presentation.icon)
                .foregroundStyle(presentation.color)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 4) {
                Text(presentation.title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(presentation.color)
                Text(presentation.body)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(presentation.title)
        .accessibilityValue(presentation.body)
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
