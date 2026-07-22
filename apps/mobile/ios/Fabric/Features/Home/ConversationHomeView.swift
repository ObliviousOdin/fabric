import SwiftUI
import UIKit

/// The connected mobile home: one outcome composer, one prominent live
/// conversation, and a two-row recent briefing. This surface is intentionally
/// session-backed until the gateway advertises the reviewed Durable Work
/// contract; it never presents a local projection as authoritative Job state.
struct ConversationHomeView: View {
    @Environment(AppModel.self) private var appModel

    @State private var model = ConversationHomeModel()
    @State private var draft = ""
    @State private var launch: ConversationLaunch?
    @State private var showAllConversations = false

    var body: some View {
        ConversationHomeContent(
            model: model,
            draft: $draft,
            gatewayLabel: appModel.activeGateway?.label ?? "Fabric gateway",
            gatewayStatusLabel: gatewayStatusLabel,
            isConnected: appModel.phase == .connected,
            canCreate: appModel.supportsGatewayMethod("session.create")
                && appModel.supportsGatewayMethod("prompt.submit"),
            canResume: appModel.supportsGatewayMethod("session.resume"),
            onStartGoal: startGoal,
            onNewChat: {
                launch = ConversationLaunch(
                    storedSessionID: nil,
                    title: "New chat",
                    initialPrompt: nil
                )
            },
            onOpenActive: { session in
                launch = ConversationLaunch(
                    storedSessionID: session.sessionKey,
                    title: session.title.isEmpty ? "Untitled conversation" : session.title,
                    initialPrompt: nil
                )
            },
            onOpenRecent: { session in
                launch = ConversationLaunch(
                    storedSessionID: session.id,
                    title: session.displayTitle,
                    initialPrompt: nil
                )
            },
            onSeeAll: { showAllConversations = true },
            onRetry: {
                if appModel.phase != .connected {
                    appModel.retryActiveGateway()
                } else {
                    Task { await reload() }
                }
            },
            onSwitchServer: { appModel.disconnect() },
            onDisconnect: { appModel.disconnect() }
        )
        .toolbar(.hidden, for: .navigationBar)
        .navigationDestination(item: $launch) { destination in
            ChatView(
                resumeStoredSessionId: destination.storedSessionID,
                title: destination.title,
                initialPrompt: destination.initialPrompt,
                onInitialPromptAttempted: {
                    guard let attempted = destination.initialPrompt else { return }
                    if draft.trimmingCharacters(in: .whitespacesAndNewlines) == attempted {
                        draft = ""
                    }
                }
            )
        }
        .navigationDestination(isPresented: $showAllConversations) {
            SessionListView()
        }
        .refreshable {
            if appModel.phase == .connected {
                await reload()
            } else {
                appModel.retryActiveGateway()
            }
        }
        .task(id: loadContext) {
            guard appModel.phase == .connected else { return }
            while !Task.isCancelled, appModel.phase == .connected {
                await reload()
                do {
                    try await Task.sleep(for: .seconds(15))
                } catch {
                    break
                }
            }
        }
    }

    private var loadContext: ConversationHomeLoadContext {
        ConversationHomeLoadContext(
            gatewayID: appModel.activeGatewayId ?? "unavailable",
            connectionGeneration: appModel.connectionGeneration
        )
    }

    private var gatewayStatusLabel: String {
        let label = appModel.activeGateway?.label ?? "Fabric gateway"
        switch appModel.phase {
        case .connected:
            return "Connected to \(label)"
        case .connecting, .reconnecting:
            return "Reconnecting to \(label)"
        case .disconnected:
            return "Offline · \(label)"
        }
    }

    private func reload() async {
        guard appModel.phase == .connected, appModel.activeGatewayId != nil else { return }
        await model.reload(
            using: appModel.api,
            context: loadContext,
            supportsActiveSessions: appModel.supportsGatewayMethod("session.active_list")
        )
    }

    private func startGoal(_ prompt: String) {
        launch = ConversationLaunch(
            storedSessionID: nil,
            title: Self.navigationTitle(for: prompt),
            initialPrompt: prompt
        )
    }

    private static func navigationTitle(for prompt: String) -> String {
        let firstLine = prompt
            .split(whereSeparator: \.isNewline)
            .first
            .map(String.init)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            ?? ""
        guard !firstLine.isEmpty else { return "New goal" }
        guard firstLine.count > 52 else { return firstLine }
        return "\(firstLine.prefix(51))…"
    }
}

private struct ConversationLaunch: Identifiable, Hashable {
    let id = UUID()
    let storedSessionID: String?
    let title: String
    let initialPrompt: String?
}

/// Shared render surface used by production and deterministic DEBUG fixtures.
/// All actions arrive as closures so fixture data cannot reach the gateway.
struct ConversationHomeContent: View {
    @Bindable var model: ConversationHomeModel
    @Binding var draft: String

    let gatewayLabel: String
    let gatewayStatusLabel: String
    let isConnected: Bool
    let canCreate: Bool
    let canResume: Bool
    let onStartGoal: (String) -> Void
    let onNewChat: () -> Void
    let onOpenActive: (ActiveSession) -> Void
    let onOpenRecent: (SessionSummary) -> Void
    let onSeeAll: () -> Void
    let onRetry: () -> Void
    let onSwitchServer: () -> Void
    let onDisconnect: () -> Void

    @FocusState private var composerFocused: Bool
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var trimmedDraft: String {
        draft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var accessibilityAnnouncement: String? {
        if !isConnected { return gatewayStatusLabel }
        if let loadError = model.loadError {
            return "Conversations unavailable. \(loadError)"
        }
        if model.activeSessionsUnavailable {
            return "Live status isn't available from this server."
        }
        return nil
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                header
                    .padding(.bottom, 32)

                Text("What should\nwe get done?")
                    .font(.largeTitle.weight(.semibold))
                    .foregroundStyle(FabricTheme.text)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityLabel("What should we get done?")
                    .accessibilityAddTraits(.isHeader)

                composer
                    .padding(.top, 24)

                homeState
                    .padding(.top, 32)
            }
            .padding(.horizontal, 20)
            .padding(.top, 16)
            .padding(.bottom, 40)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(FabricTheme.canvas.ignoresSafeArea())
        .onChange(of: accessibilityAnnouncement) { previous, current in
            guard UIAccessibility.isVoiceOverRunning,
                  let current,
                  current != previous else { return }
            UIAccessibility.post(notification: .announcement, argument: current)
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Menu {
                Text(gatewayStatusLabel)
                Button {
                    onSwitchServer()
                } label: {
                    Label("Switch server", systemImage: "arrow.left.arrow.right")
                }
                Button(role: .destructive) {
                    onDisconnect()
                } label: {
                    Label("Disconnect", systemImage: "bolt.horizontal")
                }
            } label: {
                HStack(spacing: 8) {
                    Image("FabricMark")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 34, height: 34)
                        .accessibilityHidden(true)
                    Text("Fabric")
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(FabricTheme.text)
                    Image(systemName: "chevron.down")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(FabricTheme.textMuted)
                        .accessibilityHidden(true)
                }
                .frame(minHeight: FabricTheme.minTarget)
                .contentShape(Rectangle())
            }
            .accessibilityLabel("Fabric server options")
            .accessibilityValue(gatewayStatusLabel)

            Spacer(minLength: 12)

            Button {
                onNewChat()
            } label: {
                Image(systemName: "plus")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(FabricTheme.text)
                    .frame(width: FabricTheme.minTarget, height: FabricTheme.minTarget)
                    .background(FabricTheme.surfaceRaised, in: Circle())
                    .overlay {
                        Circle().stroke(FabricTheme.border, lineWidth: 1)
                    }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Start a new chat")
            .disabled(!isConnected || !canCreate)
        }
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 12) {
                TextField(
                    "",
                    text: $draft,
                    prompt: Text("Describe an outcome…")
                        .foregroundStyle(FabricTheme.textMuted),
                    axis: .vertical
                )
                    .font(.title3)
                    .foregroundStyle(FabricTheme.text)
                    .lineLimit(3...7)
                    .focused($composerFocused)
                    .accessibilityLabel("Describe an outcome")
                    .frame(minHeight: 132, alignment: .topLeading)
            }
            .padding(16)
            .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
            .overlay {
                RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                    .stroke(
                        composerFocused ? FabricTheme.focus : FabricTheme.controlBorder,
                        lineWidth: composerFocused ? 2 : 1
                    )
            }

            Button {
                let prompt = trimmedDraft
                guard !prompt.isEmpty else { return }
                composerFocused = false
                onStartGoal(prompt)
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "sparkle")
                        .accessibilityHidden(true)
                    Text("Start goal")
                }
                .font(.body.weight(.semibold))
                .foregroundStyle(FabricTheme.textOnBrand)
                .frame(maxWidth: .infinity, minHeight: 52)
                .background(FabricTheme.action, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
            }
            .buttonStyle(.plain)
            .disabled(!isConnected || !canCreate || trimmedDraft.isEmpty)
            .accessibilityHint("Creates a conversation on \(gatewayLabel) and sends this goal to Fabric")
        }
    }

    @ViewBuilder
    private var homeState: some View {
        if !isConnected && !model.hasSnapshot {
            // Root connection chrome owns Retry/Servers so Home does not
            // duplicate recovery controls. Keep the information hierarchy
            // stable while the gateway reconnects.
            recentSection
        } else if model.isLoading && !model.hasSnapshot {
            HomeLoadingPlaceholder()
        } else if let loadError = model.loadError, !model.hasSnapshot {
            recoveryState(
                title: "Conversations unavailable",
                message: loadError,
                icon: "exclamationmark.triangle"
            )
        } else {
            if !isConnected {
                inlineNotice(
                    text: "Offline · showing the last update",
                    icon: "wifi.exclamationmark",
                    color: FabricTheme.warning
                )
                    .padding(.bottom, 20)
            } else if let loadError = model.loadError {
                inlineNotice(
                    text: "Could not refresh: \(loadError)",
                    icon: "arrow.clockwise",
                    color: FabricTheme.warning
                )
                    .padding(.bottom, 20)
            } else if model.activeSessionsUnavailable {
                inlineNotice(
                    text: "Live status isn't available from this server. Recent conversations are current.",
                    icon: "bolt.horizontal.circle",
                    color: FabricTheme.info
                )
                    .padding(.bottom, 20)
            }

            if let active = model.highlightedSession {
                activeSection(active)
            }

            recentSection
                .padding(.top, model.highlightedSession == nil ? 0 : 16)
        }
    }

    private func activeSection(_ session: ActiveSession) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("In progress")

            HStack(spacing: 0) {
                Rectangle()
                    .fill(FabricTheme.threadActive)
                    .frame(width: 3)
                    .accessibilityHidden(true)
                VStack(spacing: 0) {
                    Button {
                        onOpenActive(session)
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "point.3.connected.trianglepath.dotted")
                                .font(.title3)
                                .foregroundStyle(FabricTheme.threadActive)
                                .frame(width: FabricTheme.minTarget, height: FabricTheme.minTarget)
                                .background(FabricTheme.surfaceBrand, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
                                .accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(session.title.isEmpty ? "Untitled conversation" : session.title)
                                    .font(.body.weight(.semibold))
                                    .foregroundStyle(FabricTheme.text)
                                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 2)
                                HStack(spacing: 7) {
                                    Circle()
                                        .fill(FabricTheme.sessionStatusColor(session.status))
                                        .frame(width: 8, height: 8)
                                    Text(ConversationHomeModel.statusLabel(for: session.status))
                                        .font(.caption.weight(.medium))
                                        .foregroundStyle(FabricTheme.sessionStatusColor(session.status))
                                }
                            }
                            Spacer(minLength: 8)
                            Image(systemName: "chevron.right")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(FabricTheme.textMuted)
                                .accessibilityHidden(true)
                        }
                        .padding(12)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(!isConnected || !canResume)

                    Divider().overlay(FabricTheme.border)

                    Group {
                        if dynamicTypeSize.isAccessibilitySize {
                            VStack(alignment: .trailing, spacing: 4) {
                                if model.additionalActiveCount > 0 {
                                    Button("\(model.additionalActiveCount) more active") {
                                        onSeeAll()
                                    }
                                    .buttonStyle(.plain)
                                    .foregroundStyle(FabricTheme.action)
                                    .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget, alignment: .leading)
                                    .disabled(!isConnected || !canResume)
                                }
                                Button("View progress") {
                                    onOpenActive(session)
                                }
                                .buttonStyle(.plain)
                                .font(.subheadline.weight(.medium))
                                .foregroundStyle(FabricTheme.action)
                                .frame(minHeight: FabricTheme.minTarget)
                                .disabled(!isConnected || !canResume)
                            }
                        } else {
                            HStack(spacing: 12) {
                                if model.additionalActiveCount > 0 {
                                    Button("\(model.additionalActiveCount) more active") {
                                        onSeeAll()
                                    }
                                    .buttonStyle(.plain)
                                    .foregroundStyle(FabricTheme.action)
                                    .frame(minHeight: FabricTheme.minTarget)
                                    .disabled(!isConnected || !canResume)
                                }
                                Spacer(minLength: 8)
                                Button("View progress") {
                                    onOpenActive(session)
                                }
                                .buttonStyle(.plain)
                                .font(.subheadline.weight(.medium))
                                .foregroundStyle(FabricTheme.action)
                                .frame(minHeight: FabricTheme.minTarget)
                                .disabled(!isConnected || !canResume)
                            }
                        }
                    }
                    .padding(.horizontal, 14)
                }
            }
            .background(FabricTheme.surfaceRaised, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
            .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
            .overlay {
                RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                    .stroke(FabricTheme.border, lineWidth: 1)
            }
            .accessibilityElement(children: .contain)
        }
    }

    private var recentSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                sectionHeader("Recent")
                Spacer()
                Button("See all") { onSeeAll() }
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(FabricTheme.action)
                    .frame(minHeight: FabricTheme.minTarget)
                    .disabled(!isConnected || !canResume)
            }

            if model.recentSessions.isEmpty {
                Text("Your recent conversations will appear here.")
                    .font(.body)
                    .foregroundStyle(FabricTheme.textMuted)
                    .padding(.vertical, 16)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(model.recentSessions.enumerated()), id: \.element.id) { index, session in
                        if index > 0 {
                            Divider().overlay(FabricTheme.border)
                        }
                        Button {
                            onOpenRecent(session)
                        } label: {
                            RecentConversationRow(session: session)
                        }
                        .buttonStyle(.plain)
                        .disabled(!isConnected || !canResume)
                    }
                }
            }

            if let updated = model.lastUpdated {
                Text(isConnected ? "Updated \(updated.formatted(.relative(presentation: .named)))" : "Last updated \(updated.formatted(.relative(presentation: .named)))")
                    .font(.caption)
                    .foregroundStyle(FabricTheme.textMuted)
                    .accessibilityLabel(isConnected ? "Home updated \(updated.formatted(.relative(presentation: .named)))" : "Home last updated \(updated.formatted(.relative(presentation: .named)))")
            }
        }
    }

    private func sectionHeader(_ text: String) -> some View {
        Text(text)
            .font(.headline.weight(.semibold))
            .foregroundStyle(FabricTheme.text)
            .accessibilityAddTraits(.isHeader)
    }

    private func recoveryState(title: String, message: String, icon: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(title, systemImage: icon)
                .font(.headline.weight(.semibold))
                .foregroundStyle(FabricTheme.text)
            Text(message)
                .font(.body)
                .foregroundStyle(FabricTheme.textMuted)
                .fixedSize(horizontal: false, vertical: true)
            Button("Retry") { onRetry() }
                .buttonStyle(.bordered)
                .frame(minHeight: FabricTheme.minTarget)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
        .overlay {
            RoundedRectangle(cornerRadius: FabricTheme.radius)
                .stroke(FabricTheme.border, lineWidth: 1)
        }
    }

    private func inlineNotice(text: String, icon: String, color: Color) -> some View {
        Label(text, systemImage: icon)
            .font(.footnote)
            .foregroundStyle(color)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(color.fabricTint(), in: RoundedRectangle(cornerRadius: FabricTheme.radius))
    }
}

private struct RecentConversationRow: View {
    let session: SessionSummary

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: "bubble.left.and.text.bubble.right")
                .font(.body)
                .foregroundStyle(FabricTheme.threadActive)
                .frame(width: FabricTheme.minTarget, height: FabricTheme.minTarget)
                .background(FabricTheme.surfaceBrand, in: RoundedRectangle(cornerRadius: FabricTheme.radius))
                .accessibilityHidden(true)
            Text(session.displayTitle)
                .font(.body.weight(.medium))
                .foregroundStyle(FabricTheme.text)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 2)
            Spacer(minLength: 8)
            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(FabricTheme.textMuted)
                .accessibilityHidden(true)
        }
        .padding(.vertical, 8)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityValue("\(session.messageCount) messages")
        .accessibilityHint("Opens this conversation")
    }
}

private struct HomeLoadingPlaceholder: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            RoundedRectangle(cornerRadius: FabricTheme.radiusChip)
                .fill(FabricTheme.surfaceInset)
                .frame(width: 96, height: 16)
            RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                .fill(FabricTheme.surfaceRaised)
                .frame(height: 176)
            RoundedRectangle(cornerRadius: FabricTheme.radiusChip)
                .fill(FabricTheme.surfaceInset)
                .frame(width: 72, height: 16)
            RoundedRectangle(cornerRadius: FabricTheme.radius)
                .fill(FabricTheme.surface)
                .frame(height: 132)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Loading conversations")
    }
}
