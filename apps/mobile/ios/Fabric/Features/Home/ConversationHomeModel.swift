import Foundation
import Observation

/// The advertised gateway surface used by the conversation-first home.
///
/// Durable Work intentionally does not participate here: until the gateway
/// advertises that reviewed contract, the production home is an honest
/// projection of resumable conversations and live sessions.
@MainActor
protocol ConversationHomeLoading {
    func listSessions(limit: Int) async throws -> [SessionSummary]
    func activeSessions(currentSessionId: String?) async throws -> [ActiveSession]
}

extension GatewayAPI: ConversationHomeLoading {}

/// The authority fence for one home refresh. A response from an older socket
/// or a different saved gateway must never replace the current home.
struct ConversationHomeLoadContext: Equatable, Hashable {
    let gatewayID: String
    let connectionGeneration: Int
}

/// Small, app-facing store for the session-backed home. It deliberately owns
/// only list state; transcripts and live event folding stay in ChatViewModel.
@Observable
@MainActor
final class ConversationHomeModel {
    private(set) var sessions: [SessionSummary]
    private(set) var activeSessions: [ActiveSession]
    private(set) var isLoading: Bool
    private(set) var loadError: String?
    private(set) var activeSessionsUnavailable: Bool
    private(set) var lastUpdated: Date?

    private var context: ConversationHomeLoadContext?
    private var requestGeneration = 0

    init(
        sessions: [SessionSummary] = [],
        activeSessions: [ActiveSession] = [],
        isLoading: Bool = false,
        loadError: String? = nil,
        activeSessionsUnavailable: Bool = false,
        lastUpdated: Date? = nil
    ) {
        self.sessions = sessions
        self.activeSessions = activeSessions
        self.isLoading = isLoading
        self.loadError = loadError
        self.activeSessionsUnavailable = activeSessionsUnavailable
        self.lastUpdated = lastUpdated
    }

    var hasSnapshot: Bool { lastUpdated != nil }

    /// One prominent live conversation, matching the approved home hierarchy.
    /// Waiting work is more urgent than running work, then starting work; a
    /// stable id tie-break prevents rows from jumping at equal timestamps.
    var highlightedSession: ActiveSession? {
        rankedActiveSessions.first
    }

    var additionalActiveCount: Int {
        max(0, rankedActiveSessions.count - 1)
    }

    /// Recent is a two-row briefing, not a second full session browser. Any
    /// conversation actually represented by the active section is excluded so
    /// the same object does not appear twice. `session.active_list` may also
    /// contain idle or future-status rows; those remain eligible for Recent
    /// because fail-closed status handling keeps them out of the active card.
    var recentSessions: [SessionSummary] {
        let liveKeys = Set(rankedActiveSessions.map(\.sessionKey))
        return sessions
            .filter { !liveKeys.contains($0.id) }
            .prefix(2)
            .map { $0 }
    }

    func reload(
        using loader: any ConversationHomeLoading,
        context requestedContext: ConversationHomeLoadContext,
        supportsActiveSessions: Bool
    ) async {
        if context != requestedContext {
            requestGeneration += 1
            context = requestedContext
            sessions = []
            activeSessions = []
            lastUpdated = nil
            loadError = nil
            activeSessionsUnavailable = false
        }

        requestGeneration += 1
        let request = requestGeneration
        isLoading = true
        loadError = nil

        do {
            // Over-fetch a small bounded page so live rows can be removed
            // without leaving the two-row Recent briefing empty. Load these
            // sequentially: if the authoritative Recent request fails, no
            // detached live-status request can outlive this refresh and stack
            // behind the gateway timeout.
            let loadedSessions = try await loader.listSessions(limit: 16)
            if Task.isCancelled {
                if requestGeneration == request, context == requestedContext {
                    isLoading = false
                }
                return
            }
            guard requestGeneration == request,
                  context == requestedContext else { return }

            let loadedActiveSessions: [ActiveSession]
            let activeUnavailable: Bool
            if supportsActiveSessions {
                do {
                    loadedActiveSessions = try await loader.activeSessions(currentSessionId: nil)
                    activeUnavailable = false
                } catch {
                    loadedActiveSessions = []
                    activeUnavailable = true
                }
            } else {
                loadedActiveSessions = []
                // `session.active_list` is optional. Absence means we cannot
                // truthfully claim there is no work in progress.
                activeUnavailable = true
            }

            if Task.isCancelled {
                if requestGeneration == request, context == requestedContext {
                    isLoading = false
                }
                return
            }
            guard requestGeneration == request,
                  context == requestedContext else { return }
            sessions = loadedSessions
            activeSessions = loadedActiveSessions
            activeSessionsUnavailable = activeUnavailable
            lastUpdated = Date()
            isLoading = false
            loadError = nil
        } catch {
            if Task.isCancelled {
                if requestGeneration == request, context == requestedContext {
                    isLoading = false
                }
                return
            }
            guard requestGeneration == request,
                  context == requestedContext else { return }
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
        loadError = nil
        activeSessionsUnavailable = false
        lastUpdated = nil
    }

    static func statusLabel(for status: String) -> String {
        switch status {
        case "waiting": return "Needs attention"
        case "working": return "Running"
        case "starting": return "Starting"
        case "idle": return "Ready"
        default: return "Status unavailable"
        }
    }

    private var rankedActiveSessions: [ActiveSession] {
        activeSessions
            .filter { ["waiting", "working", "starting"].contains($0.status) }
            .sorted { lhs, rhs in
                let lhsPriority = Self.priority(for: lhs.status)
                let rhsPriority = Self.priority(for: rhs.status)
                if lhsPriority != rhsPriority { return lhsPriority < rhsPriority }
                if lhs.lastActive != rhs.lastActive { return lhs.lastActive > rhs.lastActive }
                return lhs.id < rhs.id
            }
    }

    private static func priority(for status: String) -> Int {
        switch status {
        case "waiting": return 0
        case "working": return 1
        case "starting": return 2
        default: return 3
        }
    }
}
