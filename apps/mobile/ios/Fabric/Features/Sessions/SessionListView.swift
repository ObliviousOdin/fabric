import Foundation
import Observation
import SwiftUI

/// One device-local pin. The server still owns every session title and all
/// session lifecycle state; mobile persists only this gateway/session pair.
struct SessionLibraryPin: Codable, Hashable {
    let gatewayID: String
    let sessionKey: String
}

/// Durable, device-local pin storage. Gateway IDs fence identical session
/// keys from different saved servers without inferring any project identity.
struct SessionLibraryPinStore {
    private static let storageKey = "fabric.mobile.session-pins.v1"

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func pinnedSessionKeys(for gatewayID: String) -> Set<String> {
        Set(
            allPins()
                .filter { $0.gatewayID == gatewayID }
                .map(\.sessionKey)
        )
    }

    func setPinned(_ pinned: Bool, gatewayID: String, sessionKey: String) {
        guard !gatewayID.isEmpty, !sessionKey.isEmpty else { return }
        var pins = allPins()
        let pin = SessionLibraryPin(gatewayID: gatewayID, sessionKey: sessionKey)
        if pinned {
            pins.insert(pin)
        } else {
            pins.remove(pin)
        }
        persist(pins)
    }

    private func allPins() -> Set<SessionLibraryPin> {
        guard
            let data = defaults.data(forKey: Self.storageKey),
            let pins = try? JSONDecoder().decode([SessionLibraryPin].self, from: data)
        else { return [] }
        return Set(pins.filter { !$0.gatewayID.isEmpty && !$0.sessionKey.isEmpty })
    }

    private func persist(_ pins: Set<SessionLibraryPin>) {
        let stablePins = pins.sorted {
            if $0.gatewayID != $1.gatewayID { return $0.gatewayID < $1.gatewayID }
            return $0.sessionKey < $1.sessionKey
        }
        guard let data = try? JSONEncoder().encode(stablePins) else { return }
        defaults.set(data, forKey: Self.storageKey)
    }
}

/// A duplicate-free, deterministic projection of the two existing session
/// RPCs. Search and pinning are local presentation concerns; the projection
/// never writes or substitutes server titles.
struct SessionLibraryProjection {
    enum Item: Identifiable, Hashable {
        case active(session: ActiveSession, history: SessionSummary?)
        case recent(SessionSummary)

        var id: String {
            switch self {
            case .active(let session, _):
                return "active:\(Self.activeIdentity(session))"
            case .recent(let session):
                return "recent:\(session.id)"
            }
        }

        var durableSessionKey: String? {
            let key: String
            switch self {
            case .active(let session, _): key = session.sessionKey
            case .recent(let session): key = session.id
            }
            return key.isEmpty ? nil : key
        }

        var resumeSessionKey: String {
            durableSessionKey ?? ""
        }

        var displayTitle: String {
            switch self {
            case .active(let session, let history):
                if !session.title.isEmpty { return session.title }
                if let history, !history.title.isEmpty { return history.title }
                if !session.preview.isEmpty { return session.preview }
                return "Untitled session"
            case .recent(let session):
                return session.displayTitle
            }
        }

        var stableID: String {
            durableSessionKey ?? id
        }

        var isActive: Bool {
            if case .active = self { return true }
            return false
        }

        var activeSession: ActiveSession? {
            guard case .active(let session, _) = self else { return nil }
            return session
        }

        func matches(_ foldedQuery: String) -> Bool {
            guard !foldedQuery.isEmpty else { return true }
            let fields: [String]
            switch self {
            case .active(let session, let history):
                fields = [
                    session.title,
                    session.preview,
                    history?.title ?? "",
                    history?.preview ?? "",
                    history?.source ?? "",
                ]
            case .recent(let session):
                fields = [session.title, session.preview, session.source]
            }
            return fields.contains { Self.fold($0).contains(foldedQuery) }
        }

        fileprivate static func activeIdentity(_ session: ActiveSession) -> String {
            session.sessionKey.isEmpty
                ? "runtime:\(session.id)"
                : "session:\(session.sessionKey)"
        }

        fileprivate static func fold(_ value: String) -> String {
            value.folding(
                options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive],
                locale: Locale(identifier: "en_US_POSIX")
            )
        }
    }

    let pinned: [Item]
    let active: [Item]
    let recent: [Item]

    init(
        sessions: [SessionSummary],
        activeSessions: [ActiveSession],
        pinnedSessionKeys: Set<String>,
        query: String
    ) {
        let uniqueSessions = Self.uniqueSessions(sessions)
        let historyByID = Dictionary(
            uniqueKeysWithValues: uniqueSessions.map { ($0.id, $0) }
        )
        let uniqueActive = Self.uniqueActiveSessions(activeSessions)
        let activeItems = uniqueActive.map { session in
            Item.active(session: session, history: historyByID[session.sessionKey])
        }
        let activeDurableKeys = Set(activeItems.compactMap(\.durableSessionKey))
        let recentItems = uniqueSessions
            .filter { !activeDurableKeys.contains($0.id) }
            .map(Item.recent)

        let foldedQuery = Item.fold(
            query.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        let visibleActive = activeItems.filter { $0.matches(foldedQuery) }
        let visibleRecent = recentItems.filter { $0.matches(foldedQuery) }

        // `session.list` is already ordered by the gateway's effective
        // last-active timestamp. SessionSummary.startedAt is creation time,
        // not recency, so historical rows must retain their server order.
        let pinnedActive = visibleActive
            .filter { item in
                guard let key = item.durableSessionKey else { return false }
                return pinnedSessionKeys.contains(key)
            }
            .sorted(by: Self.activeOrder)
        let pinnedRecent = visibleRecent.filter { item in
            guard let key = item.durableSessionKey else { return false }
            return pinnedSessionKeys.contains(key)
        }
        pinned = pinnedActive + pinnedRecent
        active = visibleActive
            .filter { item in
                guard let key = item.durableSessionKey else { return true }
                return !pinnedSessionKeys.contains(key)
            }
            .sorted(by: Self.activeOrder)
        recent = visibleRecent
            .filter { item in
                guard let key = item.durableSessionKey else { return true }
                return !pinnedSessionKeys.contains(key)
            }
    }

    private static func uniqueSessions(_ sessions: [SessionSummary]) -> [SessionSummary] {
        var seenIDs: Set<String> = []
        var unique: [SessionSummary] = []
        for session in sessions {
            guard seenIDs.insert(session.id).inserted else { continue }
            unique.append(session)
        }
        return unique
    }

    private static func uniqueActiveSessions(
        _ sessions: [ActiveSession]
    ) -> [ActiveSession] {
        var byIdentity: [String: ActiveSession] = [:]
        for session in sessions {
            let identity = Item.activeIdentity(session)
            guard let existing = byIdentity[identity] else {
                byIdentity[identity] = session
                continue
            }
            if session.lastActive > existing.lastActive
                || (session.lastActive == existing.lastActive && session.id < existing.id) {
                byIdentity[identity] = session
            }
        }
        return Array(byIdentity.values)
    }

    private static func activeOrder(_ lhs: Item, _ rhs: Item) -> Bool {
        guard
            case .active(let lhsSession, _) = lhs,
            case .active(let rhsSession, _) = rhs
        else { return lhs.stableID < rhs.stableID }
        if lhsSession.lastActive != rhsSession.lastActive {
            return lhsSession.lastActive > rhsSession.lastActive
        }
        return lhs.stableID < rhs.stableID
    }
}

/// The existing gateway calls needed by the session library. Keeping this
/// narrow makes the view's asynchronous publication and lifecycle fencing
/// testable without creating another transport or RPC surface.
@MainActor
protocol SessionLibraryLoading {
    func listSessions(limit: Int) async throws -> [SessionSummary]
    func activeSessions(currentSessionId: String?) async throws -> [ActiveSession]
}

extension GatewayAPI: SessionLibraryLoading {}

/// One authoritative socket/gateway identity for a library refresh.
struct SessionLibraryLoadContext: Equatable, Hashable {
    let gatewayID: String
    let connectionGeneration: Int
}

/// Testable coordinator for the two-stage session library load. Historical
/// sessions publish as soon as `session.list` completes; optional live status
/// can fail, be absent, or finish later without hiding resumable history.
@Observable
@MainActor
final class SessionLibraryModel {
    private(set) var sessions: [SessionSummary] = []
    private(set) var activeSessions: [ActiveSession] = []
    private(set) var isLoading = false
    private(set) var isLoadingActiveSessions = false
    private(set) var loadError: String?
    private(set) var activeSessionsUnavailable = false

    private var context: SessionLibraryLoadContext?
    private var requestGeneration = 0

    func reload(
        using loader: any SessionLibraryLoading,
        context requestedContext: SessionLibraryLoadContext,
        supportsSessionList: Bool,
        supportsActiveSessions: Bool,
        unavailableMessage: String? = nil
    ) async {
        guard !Task.isCancelled else { return }

        if context != requestedContext {
            requestGeneration += 1
            context = requestedContext
            sessions = []
            activeSessions = []
            isLoading = false
            isLoadingActiveSessions = false
            loadError = nil
            activeSessionsUnavailable = false
        }

        requestGeneration += 1
        let request = requestGeneration
        isLoading = true
        isLoadingActiveSessions = false
        loadError = nil

        guard supportsSessionList else {
            sessions = []
            activeSessions = []
            activeSessionsUnavailable = true
            isLoading = false
            isLoadingActiveSessions = false
            loadError = unavailableMessage ?? "Session listing is unavailable on this gateway."
            return
        }

        do {
            let loadedSessions = try await loader.listSessions(limit: 100)
            if finishIfCancelled(request: request, context: requestedContext) { return }
            guard isCurrent(request: request, context: requestedContext) else { return }

            // Publish the authoritative history before the optional live
            // request. Clear the previous live decoration at this boundary so
            // stale process state never appears beside the new history page.
            sessions = loadedSessions
            activeSessions = []
            activeSessionsUnavailable = !supportsActiveSessions
            isLoading = false
            isLoadingActiveSessions = supportsActiveSessions
            loadError = nil

            guard supportsActiveSessions else { return }

            do {
                let loadedActiveSessions = try await loader.activeSessions(currentSessionId: nil)
                if finishIfCancelled(
                    request: request,
                    context: requestedContext,
                    cancelledActiveStatus: true
                ) { return }
                guard isCurrent(request: request, context: requestedContext) else { return }
                activeSessions = loadedActiveSessions
                activeSessionsUnavailable = false
                isLoadingActiveSessions = false
            } catch {
                if finishIfCancelled(
                    request: request,
                    context: requestedContext,
                    cancelledActiveStatus: true
                ) { return }
                guard isCurrent(request: request, context: requestedContext) else { return }
                activeSessions = []
                activeSessionsUnavailable = true
                isLoadingActiveSessions = false
            }
        } catch {
            if finishIfCancelled(request: request, context: requestedContext) { return }
            guard isCurrent(request: request, context: requestedContext) else { return }
            isLoading = false
            loadError = error.localizedDescription
        }
    }

    func invalidate() {
        requestGeneration += 1
        context = nil
        sessions = []
        activeSessions = []
        isLoading = false
        isLoadingActiveSessions = false
        loadError = nil
        activeSessionsUnavailable = false
    }

    private func finishIfCancelled(
        request: Int,
        context requestedContext: SessionLibraryLoadContext,
        cancelledActiveStatus: Bool = false
    ) -> Bool {
        guard Task.isCancelled else { return false }
        if isCurrent(request: request, context: requestedContext) {
            isLoading = false
            if cancelledActiveStatus {
                isLoadingActiveSessions = false
                activeSessions = []
                activeSessionsUnavailable = true
            }
        }
        return true
    }

    private func isCurrent(
        request: Int,
        context requestedContext: SessionLibraryLoadContext
    ) -> Bool {
        requestGeneration == request && context == requestedContext
    }
}

/// Searchable session library: device-local pins first, live gateway sessions
/// second, and historical `session.list` rows last. `session.active_list`
/// remains optional decoration and can never block the historical library.
struct SessionListView: View {
    @Environment(AppModel.self) private var appModel

    @State private var model = SessionLibraryModel()
    @State private var pinnedSessionKeys: Set<String> = []
    @State private var searchQuery = ""

    private let pinStore = SessionLibraryPinStore()

    var body: some View {
        let projection = SessionLibraryProjection(
            sessions: model.sessions,
            activeSessions: model.activeSessions,
            pinnedSessionKeys: pinnedSessionKeys,
            query: searchQuery
        )

        List {
            Section {
                GatewayExecutionCard(negotiation: appModel.capabilityNegotiation)
            }

            Section {
                NavigationLink {
                    ChatView(resumeStoredSessionId: nil, title: "New chat")
                } label: {
                    Label("New chat", systemImage: "plus.bubble")
                        .frame(minHeight: FabricTheme.minTarget)
                }
                .disabled(!appModel.supportsGatewayMethod("session.create"))
            }

            if !projection.pinned.isEmpty {
                Section("Pinned on this device") {
                    ForEach(projection.pinned) { item in
                        sessionLink(item, isPinned: true)
                    }
                }
            }

            if !projection.active.isEmpty {
                Section("Active now") {
                    ForEach(projection.active) { item in
                        sessionLink(item, isPinned: false)
                    }
                }
            }

            if model.isLoadingActiveSessions {
                Section {
                    Label("Updating live status…", systemImage: "arrow.triangle.2.circlepath")
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                        .accessibilityLabel("Updating live session status")
                }
            } else if model.activeSessionsUnavailable {
                Section {
                    Label(
                        "Live status is unavailable. Recent and pinned sessions are still available.",
                        systemImage: "bolt.slash"
                    )
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .accessibilityLabel("Live session status unavailable")
                    .accessibilityValue("Recent and pinned sessions remain available")
                }
            }

            Section {
                if model.isLoading && model.sessions.isEmpty {
                    ProgressView("Loading sessions")
                } else if let loadError = model.loadError {
                    Text(loadError)
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.danger)
                } else if projection.recent.isEmpty {
                    Text(emptyRecentMessage(projection: projection))
                        .foregroundStyle(FabricTheme.textMuted)
                }

                ForEach(projection.recent) { item in
                    sessionLink(item, isPinned: false)
                }
            } header: {
                Text("Recent sessions")
            } footer: {
                Text("Pins are saved only on this device and only for this Fabric server. Swipe a session to pin or unpin it.")
            }
        }
        .searchable(text: $searchQuery, prompt: "Search sessions")
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
                        .frame(width: FabricTheme.minTarget, height: FabricTheme.minTarget)
                }
                .accessibilityLabel("Server menu")
            }
        }
        .refreshable {
            if appModel.phase == .connected { await reload() }
        }
        .task(id: appModel.connectionGeneration) {
            prepareForCurrentGateway()
            if appModel.phase == .connected { await reload() }
        }
    }

    @ViewBuilder
    private func sessionLink(_ item: SessionLibraryProjection.Item, isPinned: Bool) -> some View {
        let link = NavigationLink {
            ChatView(resumeStoredSessionId: item.resumeSessionKey, title: item.displayTitle)
        } label: {
            switch item {
            case .active(let session, let history):
                ActiveSessionRow(
                    session: session,
                    source: history?.source ?? "",
                    displayTitle: item.displayTitle,
                    isPinned: isPinned
                )
            case .recent(let session):
                RecentSessionRow(session: session, isPinned: isPinned)
            }
        }
        .frame(minHeight: FabricTheme.minTarget)
        .disabled(
            item.resumeSessionKey.isEmpty
                || !appModel.supportsGatewayMethod("session.resume")
        )
        .swipeActions(edge: .leading, allowsFullSwipe: true) {
            if item.durableSessionKey != nil {
                Button {
                    togglePin(item, currentlyPinned: isPinned)
                } label: {
                    Label(
                        isPinned ? "Unpin from this device" : "Pin on this device",
                        systemImage: isPinned ? "pin.slash" : "pin"
                    )
                }
                .tint(isPinned ? FabricTheme.textMuted : FabricTheme.action)
            }
        }
        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
            if let session = item.activeSession,
               session.status == "working" || session.status == "starting",
               appModel.supportsGatewayMethod("session.interrupt") {
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
        if item.durableSessionKey == nil {
            link
        } else {
            link.accessibilityAction(
                named: Text(isPinned ? "Unpin from this device" : "Pin on this device")
            ) {
                togglePin(item, currentlyPinned: isPinned)
            }
        }
    }

    private func emptyRecentMessage(projection: SessionLibraryProjection) -> String {
        if !searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return projection.pinned.isEmpty && projection.active.isEmpty
                ? "No sessions match your search."
                : "No other sessions match your search."
        }
        if model.sessions.isEmpty { return "No sessions yet." }
        return "Active or pinned sessions are shown above."
    }

    private func prepareForCurrentGateway() {
        model.invalidate()
        searchQuery = ""
        guard let gatewayID = appModel.activeGatewayId else {
            pinnedSessionKeys = []
            return
        }
        pinnedSessionKeys = pinStore.pinnedSessionKeys(for: gatewayID)
    }

    private func togglePin(_ item: SessionLibraryProjection.Item, currentlyPinned: Bool) {
        guard
            let gatewayID = appModel.activeGatewayId,
            let sessionKey = item.durableSessionKey
        else { return }
        pinStore.setPinned(!currentlyPinned, gatewayID: gatewayID, sessionKey: sessionKey)
        pinnedSessionKeys = pinStore.pinnedSessionKeys(for: gatewayID)
    }

    private func reload() async {
        guard
            appModel.phase == .connected,
            let gatewayID = appModel.activeGatewayId
        else { return }

        await model.reload(
            using: appModel.api,
            context: SessionLibraryLoadContext(
                gatewayID: gatewayID,
                connectionGeneration: appModel.connectionGeneration
            ),
            supportsSessionList: appModel.supportsGatewayMethod("session.list"),
            supportsActiveSessions: appModel.supportsGatewayMethod("session.active_list"),
            unavailableMessage: appModel.capabilityNegotiation?.blockingMessage
        )
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
    let source: String
    let displayTitle: String
    let isPinned: Bool

    private var statusColor: Color {
        FabricTheme.sessionStatusColor(session.status)
    }

    private var accessibilityValue: String {
        var parts: [String] = []
        if isPinned { parts.append("Pinned on this device") }
        parts.append(ConversationHomeModel.statusLabel(for: session.status))
        if !session.preview.isEmpty { parts.append(session.preview) }
        if !source.isEmpty { parts.append("Source \(source)") }
        if !session.model.isEmpty { parts.append("Model \(session.model)") }
        parts.append("\(session.messageCount) messages")
        return parts.joined(separator: ", ")
    }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Circle()
                .fill(statusColor)
                .frame(width: 8, height: 8)
                .padding(.top, 6)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(displayTitle)
                        .foregroundStyle(FabricTheme.text)
                        .lineLimit(2)
                    if isPinned {
                        Image(systemName: "pin.fill")
                            .font(.caption)
                            .foregroundStyle(FabricTheme.action)
                            .accessibilityHidden(true)
                    }
                }
                if !session.preview.isEmpty {
                    Text(session.preview)
                        .font(.caption)
                        .foregroundStyle(FabricTheme.textMuted)
                        .lineLimit(2)
                }
                HStack(spacing: 8) {
                    Text(ConversationHomeModel.statusLabel(for: session.status))
                    if !source.isEmpty { Text(source) }
                    if !session.model.isEmpty { Text(session.model) }
                    Text("\(session.messageCount) messages")
                }
                .font(.caption)
                .foregroundStyle(FabricTheme.textMuted)
            }
        }
        .padding(.vertical, 4)
        .frame(minHeight: FabricTheme.minTarget)
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(displayTitle)
        .accessibilityValue(accessibilityValue)
        .accessibilityHint("Opens this conversation")
    }
}

private struct RecentSessionRow: View {
    let session: SessionSummary
    let isPinned: Bool

    private var accessibilityValue: String {
        var parts: [String] = []
        if isPinned { parts.append("Pinned on this device") }
        if !session.preview.isEmpty { parts.append(session.preview) }
        if !session.source.isEmpty { parts.append("Source \(session.source)") }
        parts.append("\(session.messageCount) messages")
        return parts.joined(separator: ", ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text(session.displayTitle)
                    .foregroundStyle(FabricTheme.text)
                    .lineLimit(2)
                if isPinned {
                    Image(systemName: "pin.fill")
                        .font(.caption)
                        .foregroundStyle(FabricTheme.action)
                        .accessibilityHidden(true)
                }
            }
            if !session.preview.isEmpty && session.preview != session.displayTitle {
                Text(session.preview)
                    .font(.caption)
                    .foregroundStyle(FabricTheme.textMuted)
                    .lineLimit(2)
            }
            HStack(spacing: 8) {
                if session.startedAt > 0 {
                    Text(
                        Date(timeIntervalSince1970: session.startedAt),
                        format: .relative(presentation: .named)
                    )
                }
                if !session.source.isEmpty { Text(session.source) }
                Text("\(session.messageCount) messages")
            }
            .font(.caption)
            .foregroundStyle(FabricTheme.textMuted)
        }
        .padding(.vertical, 4)
        .frame(minHeight: FabricTheme.minTarget)
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(session.displayTitle)
        .accessibilityValue(accessibilityValue)
        .accessibilityHint("Opens this conversation")
    }
}
