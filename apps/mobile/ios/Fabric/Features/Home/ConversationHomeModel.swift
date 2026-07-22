import Foundation
import Observation
import CryptoKit

struct ConversationHomeSnapshot: Codable, Equatable {
    static let version = 1

    let schemaVersion: Int
    let gatewayID: String
    let sessions: [SessionSummary]
    let activeSessions: [ActiveSession]
    let updatedAt: Date

    init(
        gatewayID: String,
        sessions: [SessionSummary],
        activeSessions: [ActiveSession],
        updatedAt: Date
    ) {
        schemaVersion = Self.version
        self.gatewayID = gatewayID
        self.sessions = Array(sessions.prefix(16))
        self.activeSessions = Array(activeSessions.prefix(16))
        self.updatedAt = updatedAt
    }
}

/// Bounded, presentation-only Home snapshot storage. Session metadata can be
/// sensitive, so files use complete data protection. This cache is never sent
/// to the model or treated as gateway authority; a successful reload replaces
/// it immediately.
struct ConversationHomeSnapshotStore {
    static let requiredFileProtection = FileProtectionType.complete

    struct Policy {
        let maximumEncodedBytes: Int
        let maximumDirectoryBytes: Int
        let maximumSnapshots: Int
        let maximumAge: TimeInterval

        static let production = Policy(
            maximumEncodedBytes: 512 * 1_024,
            maximumDirectoryBytes: 4 * 1_024 * 1_024,
            maximumSnapshots: 16,
            maximumAge: 30 * 24 * 60 * 60
        )
    }

    private let directoryURL: URL
    private let fileManager: FileManager
    private let policy: Policy

    init(
        directoryURL: URL? = nil,
        fileManager: FileManager = .default,
        policy: Policy = .production
    ) {
        self.fileManager = fileManager
        self.policy = policy
        if let directoryURL {
            self.directoryURL = directoryURL
        } else {
            let base = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
                ?? fileManager.temporaryDirectory
            self.directoryURL = base
                .appending(path: "Fabric", directoryHint: .isDirectory)
                .appending(path: "HomeSnapshots", directoryHint: .isDirectory)
        }
    }

    func load(gatewayID: String, now: Date = Date()) -> ConversationHomeSnapshot? {
        let url = snapshotURL(gatewayID: gatewayID)
        do {
            try secureDirectory()
            prune()
            guard try isSecureItem(url),
                  try fileSize(at: url) > 0,
                  try fileSize(at: url) <= policy.maximumEncodedBytes else {
                try? fileManager.removeItem(at: url)
                return nil
            }
            let data = try Data(contentsOf: url, options: .mappedIfSafe)
            guard data.count <= policy.maximumEncodedBytes else {
                try? fileManager.removeItem(at: url)
                return nil
            }
            let snapshot = try JSONDecoder().decode(ConversationHomeSnapshot.self, from: data)
            guard snapshot.schemaVersion == ConversationHomeSnapshot.version,
                  snapshot.gatewayID == gatewayID,
                  now.timeIntervalSince(snapshot.updatedAt) >= 0,
                  now.timeIntervalSince(snapshot.updatedAt) <= policy.maximumAge else {
                try? fileManager.removeItem(at: url)
                return nil
            }
            try fileManager.setAttributes(
                [.modificationDate: Date()],
                ofItemAtPath: url.path
            )
            prune()
            return snapshot
        } catch {
            // Missing, corrupt, oversized, stale, or incorrectly protected
            // presentation data must never be painted as a trusted snapshot.
            try? fileManager.removeItem(at: url)
            return nil
        }
    }

    func save(_ snapshot: ConversationHomeSnapshot) {
        guard !snapshot.gatewayID.isEmpty,
              let data = try? JSONEncoder().encode(snapshot),
              data.count <= policy.maximumEncodedBytes else { return }
        let url = snapshotURL(gatewayID: snapshot.gatewayID)
        do {
            try secureDirectory()
            try data.write(to: url, options: [.atomic])
            try fileManager.setAttributes(
                [.protectionKey: Self.requiredFileProtection],
                ofItemAtPath: url.path
            )
            try excludeFromBackup(url)
            guard try isSecureItem(url) else {
                throw CocoaError(.fileWriteNoPermission)
            }
            prune()
        } catch {
            // Presentation caching is best-effort and must never block Home.
            try? fileManager.removeItem(at: url)
        }
    }

    func removeAll() {
        try? fileManager.removeItem(at: directoryURL)
    }

    /// Internal inspection seam for behavioral protection and eviction tests.
    func snapshotURL(gatewayID: String) -> URL {
        let digest = SHA256.hash(data: Data(gatewayID.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        return directoryURL.appending(path: "\(digest).json")
    }

    private func secureDirectory() throws {
        try fileManager.createDirectory(
            at: directoryURL,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: Self.requiredFileProtection]
        )
        try fileManager.setAttributes(
            [.protectionKey: Self.requiredFileProtection],
            ofItemAtPath: directoryURL.path
        )
        try excludeFromBackup(directoryURL)
        guard try isSecureItem(directoryURL) else {
            throw CocoaError(.fileWriteNoPermission)
        }
    }

    private func excludeFromBackup(_ url: URL) throws {
        var mutableURL = url
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try mutableURL.setResourceValues(values)
    }

    private func isSecureItem(_ url: URL) throws -> Bool {
        let attributes = try fileManager.attributesOfItem(atPath: url.path)
        let rawProtection = attributes[.protectionKey]
        #if targetEnvironment(simulator)
        // CoreSimulator host files may omit NSFileProtectionKey. Explicitly
        // weaker protection still fails closed; physical devices must report
        // `.complete` below.
        let hasCompleteProtection = rawProtection == nil
            || Self.hasRequiredFileProtection(rawProtection)
        #else
        let hasCompleteProtection = Self.hasRequiredFileProtection(rawProtection)
        #endif
        let values = try url.resourceValues(forKeys: [.isExcludedFromBackupKey])
        return hasCompleteProtection && values.isExcludedFromBackup == true
    }

    static func hasRequiredFileProtection(_ raw: Any?) -> Bool {
        (raw as? FileProtectionType) == requiredFileProtection
            || (raw as? String) == requiredFileProtection.rawValue
    }

    private func fileSize(at url: URL) throws -> Int {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        return values.fileSize ?? 0
    }

    /// Directory-wide LRU pruning keeps the aggregate presentation footprint
    /// bounded across every server ever paired on this device.
    private func prune(now: Date = Date()) {
        let keys: Set<URLResourceKey> = [
            .contentModificationDateKey,
            .fileSizeKey,
            .isRegularFileKey,
        ]
        guard let urls = try? fileManager.contentsOfDirectory(
            at: directoryURL,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles]
        ) else { return }

        let cutoff = now.addingTimeInterval(-policy.maximumAge)
        var candidates: [(url: URL, modified: Date, size: Int)] = []
        for url in urls where url.pathExtension == "json" {
            guard let values = try? url.resourceValues(forKeys: keys),
                  values.isRegularFile == true,
                  let modified = values.contentModificationDate,
                  let size = values.fileSize,
                  size > 0,
                  size <= policy.maximumEncodedBytes,
                  modified >= cutoff,
                  (try? isSecureItem(url)) == true else {
                try? fileManager.removeItem(at: url)
                continue
            }
            candidates.append((url, modified, size))
        }

        candidates.sort {
            if $0.modified != $1.modified { return $0.modified > $1.modified }
            return $0.url.lastPathComponent < $1.url.lastPathComponent
        }
        var retainedBytes = 0
        for (index, candidate) in candidates.enumerated() {
            let exceedsCount = index >= policy.maximumSnapshots
            let exceedsBytes = retainedBytes + candidate.size > policy.maximumDirectoryBytes
            if exceedsCount || exceedsBytes {
                try? fileManager.removeItem(at: candidate.url)
            } else {
                retainedBytes += candidate.size
            }
        }
    }
}

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
    private let snapshotStore: ConversationHomeSnapshotStore

    init(
        sessions: [SessionSummary] = [],
        activeSessions: [ActiveSession] = [],
        isLoading: Bool = false,
        loadError: String? = nil,
        activeSessionsUnavailable: Bool = false,
        lastUpdated: Date? = nil,
        snapshotStore: ConversationHomeSnapshotStore = ConversationHomeSnapshotStore()
    ) {
        self.sessions = sessions
        self.activeSessions = activeSessions
        self.isLoading = isLoading
        self.loadError = loadError
        self.activeSessionsUnavailable = activeSessionsUnavailable
        self.lastUpdated = lastUpdated
        self.snapshotStore = snapshotStore
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
            if let snapshot = snapshotStore.load(gatewayID: requestedContext.gatewayID) {
                sessions = snapshot.sessions
                activeSessions = snapshot.activeSessions
                lastUpdated = snapshot.updatedAt
            } else {
                sessions = []
                activeSessions = []
                lastUpdated = nil
            }
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
            if let lastUpdated {
                snapshotStore.save(ConversationHomeSnapshot(
                    gatewayID: requestedContext.gatewayID,
                    sessions: sessions,
                    activeSessions: activeSessions,
                    updatedAt: lastUpdated
                ))
            }
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
            loadError = "Couldn't refresh Home. Check the connection and pull to retry."
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
