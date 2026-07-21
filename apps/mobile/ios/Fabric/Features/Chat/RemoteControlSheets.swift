import SwiftUI

enum RemoteControlLoadState: Equatable {
    case loading
    case loaded
    case unavailable(String)
    case failed(String)
}

struct RemoteControlLoadIdentity: Equatable {
    let generation: Int
    let sessionId: String?

    func isCurrent(generation: Int, sessionId: String?) -> Bool {
        self.generation == generation && self.sessionId == sessionId
    }
}

enum ProcessKillFeedback: Equatable {
    case rejected
    case outcomeUnknown

    static func classify(_ error: Error) -> ProcessKillFeedback {
        if let gatewayError = error as? GatewayClientError,
           case .rpc = gatewayError {
            return .rejected
        }
        return .outcomeUnknown
    }

    var title: String {
        switch self {
        case .rejected: "Process was not stopped"
        case .outcomeUnknown: "Stop result unknown"
        }
    }

    var message: String {
        switch self {
        case .rejected:
            "The gateway rejected the stop request. Refresh status before trying again."
        case .outcomeUnknown:
            "The stop request may have reached the gateway, but its result was not confirmed. Refresh status before trying again."
        }
    }
}

struct ProcessKillMutationIdentity: Equatable {
    let generation: Int
    let sessionId: String
    let processId: String
}

struct ProcessKillMutationState: Equatable {
    private(set) var inFlight: ProcessKillMutationIdentity?
    private(set) var feedback: ProcessKillFeedback?
    private var generation = 0

    mutating func begin(
        sessionId: String,
        processId: String
    ) -> ProcessKillMutationIdentity? {
        guard inFlight == nil else { return nil }
        generation += 1
        let identity = ProcessKillMutationIdentity(
            generation: generation,
            sessionId: sessionId,
            processId: processId
        )
        inFlight = identity
        feedback = nil
        return identity
    }

    func isCurrent(_ identity: ProcessKillMutationIdentity) -> Bool {
        inFlight == identity
    }

    mutating func record(
        _ feedback: ProcessKillFeedback,
        for identity: ProcessKillMutationIdentity
    ) {
        guard isCurrent(identity) else { return }
        self.feedback = feedback
    }

    @discardableResult
    mutating func finish(_ identity: ProcessKillMutationIdentity) -> Bool {
        guard isCurrent(identity) else { return false }
        inFlight = nil
        return true
    }

    mutating func reset() {
        generation += 1
        inFlight = nil
        feedback = nil
    }

    mutating func didLoadAuthoritativeSnapshot() {
        feedback = nil
    }

    func canStop(
        status: String,
        supportsKill: Bool,
        loadState: RemoteControlLoadState
    ) -> Bool {
        RemoteControlPresentation.canStopProcess(
            status: status,
            supportsKill: supportsKill,
            mutationInFlight: inFlight != nil,
            hasAuthoritativeSnapshot: loadState == .loaded && feedback == nil
        )
    }
}

enum RemoteControlPresentation {
    static let outputCharacterLimit = 4_000

    static func filteredCategories(
        _ categories: [SlashCommandCategory],
        query: String
    ) -> [SlashCommandCategory] {
        let normalizedQuery = normalized(query)
        guard !normalizedQuery.isEmpty else { return categories }

        return categories.compactMap { category in
            let commands = category.commands.filter { command in
                normalized(command.name).contains(normalizedQuery)
                    || normalized(command.detail).contains(normalizedQuery)
            }
            guard !commands.isEmpty else { return nil }
            return SlashCommandCategory(name: category.name, commands: commands)
        }
    }

    static func boundedOutput(_ output: String) -> String {
        String(output.suffix(outputCharacterLimit))
    }

    static func statusLabel(_ status: String) -> String {
        let normalizedStatus = status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalizedStatus.isEmpty else { return "Unknown" }
        return normalizedStatus.prefix(1).uppercased() + normalizedStatus.dropFirst()
    }

    static func statusColor(_ status: String) -> Color {
        switch status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "running": FabricTheme.threadActive
        case "failed", "error": FabricTheme.danger
        case "waiting": FabricTheme.warning
        case "starting": FabricTheme.info
        default: FabricTheme.textMuted
        }
    }

    static func canStopProcess(
        status: String,
        supportsKill: Bool,
        mutationInFlight: Bool,
        hasAuthoritativeSnapshot: Bool
    ) -> Bool {
        status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "running"
            && supportsKill
            && !mutationInFlight
            && hasAuthoritativeSnapshot
    }

    private static func normalized(_ value: String) -> String {
        value
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(
                options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive],
                locale: Locale(identifier: "en_US_POSIX")
            )
            .lowercased(with: Locale(identifier: "en_US_POSIX"))
    }
}

private struct RemoteControlStatusRow: View {
    let title: String
    let message: String
    let systemImage: String
    let tone: Color
    let retryTitle: String?
    let onRetry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: systemImage)
                .font(.headline)
                .foregroundStyle(tone)
            Text(message)
                .font(.footnote)
                .foregroundStyle(FabricTheme.textMuted)
            if let retryTitle {
                Button(retryTitle, action: onRetry)
                    .frame(minHeight: FabricTheme.minTarget)
            }
        }
        .padding(.vertical, 4)
    }
}

/// The slash-command catalog (`commands.catalog`), grouped by category.
/// Tapping a command hands it back to the composer for arguments.
struct CommandCatalogSheet: View {
    let api: GatewayAPI
    let supportsMethod: (String) -> Bool
    let onSelect: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var categories: [SlashCommandCategory] = []
    @State private var searchText = ""
    @State private var loadState: RemoteControlLoadState = .loading
    @State private var loadGeneration = 0

    private var filtered: [SlashCommandCategory] {
        RemoteControlPresentation.filteredCategories(categories, query: searchText)
    }

    var body: some View {
        NavigationStack {
            List {
                switch loadState {
                case .loading where categories.isEmpty:
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("Loading commands…")
                            .foregroundStyle(FabricTheme.textMuted)
                    }
                    .frame(minHeight: FabricTheme.minTarget)

                case .unavailable(let message):
                    RemoteControlStatusRow(
                        title: "Commands unavailable",
                        message: message,
                        systemImage: "slash.circle",
                        tone: FabricTheme.info,
                        retryTitle: nil,
                        onRetry: {}
                    )

                case .failed(let message):
                    RemoteControlStatusRow(
                        title: "Couldn’t load commands",
                        message: message,
                        systemImage: "exclamationmark.triangle",
                        tone: FabricTheme.danger,
                        retryTitle: "Retry"
                    ) {
                        Task { await reload() }
                    }

                case .loaded where categories.isEmpty:
                    ContentUnavailableView(
                        "No commands available",
                        systemImage: "slash.circle",
                        description: Text("This gateway returned an empty command catalog.")
                    )

                case .loaded where filtered.isEmpty:
                    ContentUnavailableView.search(text: searchText)

                default:
                    EmptyView()
                }

                ForEach(filtered) { category in
                    Section(category.name) {
                        ForEach(category.commands) { command in
                            Button {
                                onSelect(command.name)
                            } label: {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(command.name)
                                        .font(.body.monospaced())
                                    if !command.detail.isEmpty {
                                        Text(command.detail)
                                            .font(.caption)
                                            .foregroundStyle(FabricTheme.textMuted)
                                            .lineLimit(2)
                                    }
                                }
                                .frame(
                                    maxWidth: .infinity,
                                    minHeight: FabricTheme.minTarget,
                                    alignment: .leading
                                )
                            }
                            .foregroundStyle(FabricTheme.text)
                            .disabled(!supportsMethod("slash.exec"))
                        }
                    }
                }
            }
            .searchable(text: $searchText, prompt: "Filter commands")
            .navigationTitle("Commands")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .task { await reload() }
            .onDisappear { loadGeneration += 1 }
        }
    }

    private func reload() async {
        loadGeneration += 1
        let identity = RemoteControlLoadIdentity(generation: loadGeneration, sessionId: nil)

        guard supportsMethod("commands.catalog"), supportsMethod("slash.exec") else {
            categories = []
            loadState = .unavailable(
                "This gateway does not advertise both command discovery and command execution."
            )
            return
        }

        loadState = .loading
        do {
            let result = try await api.commandCatalog()
            guard
                !Task.isCancelled,
                identity.isCurrent(generation: loadGeneration, sessionId: nil)
            else { return }
            categories = result
            loadState = .loaded
        } catch is CancellationError {
            return
        } catch {
            guard identity.isCurrent(generation: loadGeneration, sessionId: nil) else { return }
            loadState = .failed(
                "The command catalog could not be loaded. Check the gateway connection and try again."
            )
        }
    }
}

/// Background processes owned by this session (`process.list`), with
/// confirmation-gated kill control and a bounded, selectable output tail.
struct ProcessListSheet: View {
    let api: GatewayAPI
    let sessionId: String?
    let supportsMethod: (String) -> Bool

    @Environment(\.dismiss) private var dismiss
    @State private var processes: [BackgroundProcess] = []
    @State private var loadState: RemoteControlLoadState = .loading
    @State private var loadGeneration = 0
    @State private var processToKill: BackgroundProcess?
    @State private var killMutation = ProcessKillMutationState()
    @State private var killTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            List {
                if let killFeedback = killMutation.feedback {
                    Section {
                        VStack(alignment: .leading, spacing: 10) {
                            Label(
                                killFeedback.title,
                                systemImage: killFeedback == .outcomeUnknown
                                    ? "questionmark.circle"
                                    : "exclamationmark.triangle"
                            )
                            .font(.headline)
                            .foregroundStyle(
                                killFeedback == .outcomeUnknown
                                    ? FabricTheme.warning
                                    : FabricTheme.danger
                            )
                            Text(killFeedback.message)
                                .font(.footnote)
                                .foregroundStyle(FabricTheme.textMuted)
                            Button("Refresh status") {
                                Task { await reload() }
                            }
                            .frame(minHeight: FabricTheme.minTarget)
                        }
                        .padding(.vertical, 4)
                    }
                }

                switch loadState {
                case .loading where processes.isEmpty:
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("Loading processes…")
                            .foregroundStyle(FabricTheme.textMuted)
                    }
                    .frame(minHeight: FabricTheme.minTarget)

                case .unavailable(let message):
                    RemoteControlStatusRow(
                        title: "Processes unavailable",
                        message: message,
                        systemImage: "terminal",
                        tone: FabricTheme.info,
                        retryTitle: nil,
                        onRetry: {}
                    )

                case .failed(let message):
                    RemoteControlStatusRow(
                        title: "Couldn’t load processes",
                        message: message,
                        systemImage: "exclamationmark.triangle",
                        tone: FabricTheme.danger,
                        retryTitle: "Retry"
                    ) {
                        Task { await reload() }
                    }

                case .loaded where processes.isEmpty:
                    ContentUnavailableView(
                        "No background processes",
                        systemImage: "terminal",
                        description: Text("This session has no running or recently exited processes.")
                    )

                default:
                    EmptyView()
                }

                ForEach(processes) { process in
                    processRow(process)
                }
            }
            .navigationTitle("Processes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        Task { await reload() }
                    } label: {
                        if loadState == .loading {
                            ProgressView()
                        } else {
                            Image(systemName: "arrow.clockwise")
                        }
                    }
                    .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                    .accessibilityLabel("Refresh processes")
                    .disabled(loadState == .loading || killMutation.inFlight != nil)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .task(id: sessionId) {
                resetKillMutation()
                await reload()
            }
            .onDisappear {
                loadGeneration += 1
                resetKillMutation()
            }
            .confirmationDialog(
                "Stop this background process?",
                isPresented: Binding(
                    get: { processToKill != nil },
                    set: { if !$0 { processToKill = nil } }
                ),
                titleVisibility: .visible,
                presenting: processToKill
            ) { process in
                Button("Stop process", role: .destructive) {
                    processToKill = nil
                    startKill(process)
                }
                Button("Cancel", role: .cancel) {
                    processToKill = nil
                }
            } message: { process in
                Text("Stop \(process.command)? Refresh afterward to confirm its final status.")
            }
        }
    }

    @ViewBuilder
    private func processRow(_ process: BackgroundProcess) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(process.command.isEmpty ? "Unnamed process" : process.command)
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                    HStack(spacing: 6) {
                        Circle()
                            .fill(RemoteControlPresentation.statusColor(process.status))
                            .frame(width: 8, height: 8)
                        Text(RemoteControlPresentation.statusLabel(process.status))
                        Text("pid \(process.pid)")
                        Text("up \(process.uptimeSeconds)s")
                    }
                    .font(.caption)
                    .foregroundStyle(FabricTheme.textMuted)
                    .accessibilityElement(children: .combine)
                }
                Spacer(minLength: 8)
                if process.status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                    == "running" {
                    Button("Stop", role: .destructive) {
                        processToKill = process
                    }
                    .buttonStyle(.bordered)
                    .frame(minHeight: FabricTheme.minTarget)
                    .disabled(
                        !killMutation.canStop(
                            status: process.status,
                            supportsKill: supportsMethod("process.kill"),
                            loadState: loadState
                        )
                    )
                    .accessibilityLabel("Stop \(process.command.isEmpty ? "background process" : process.command)")
                }
            }

            if !process.outputTail.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Recent output")
                        .font(.caption)
                        .foregroundStyle(FabricTheme.textMuted)
                    ScrollView(.horizontal) {
                        Text(RemoteControlPresentation.boundedOutput(process.outputTail))
                            .font(.caption.monospaced())
                            .foregroundStyle(FabricTheme.textMuted)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: true, vertical: false)
                    }
                    .frame(maxHeight: 140)
                    .accessibilityLabel("Recent process output")
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func reload() async {
        loadGeneration += 1
        let identity = RemoteControlLoadIdentity(
            generation: loadGeneration,
            sessionId: sessionId
        )

        guard supportsMethod("process.list") else {
            processes = []
            loadState = .unavailable("This gateway does not advertise process listing.")
            return
        }
        guard let requestedSessionId = sessionId else {
            processes = []
            loadState = .unavailable("Open a live session before viewing its processes.")
            return
        }

        loadState = .loading
        do {
            let result = try await api.listProcesses(sessionId: requestedSessionId)
            guard
                !Task.isCancelled,
                identity.isCurrent(generation: loadGeneration, sessionId: sessionId)
            else { return }
            processes = result
            killMutation.didLoadAuthoritativeSnapshot()
            loadState = .loaded
        } catch is CancellationError {
            return
        } catch {
            guard identity.isCurrent(generation: loadGeneration, sessionId: sessionId) else { return }
            loadState = .failed(
                "Process status could not be loaded. Check the gateway connection and try again."
            )
        }
    }

    private func startKill(_ process: BackgroundProcess) {
        guard supportsMethod("process.kill") else {
            // This is not a request receipt. Keep the old snapshot visible but
            // mutation-ineligible until the user refreshes capabilities/state.
            if let requestedSessionId = sessionId,
               let identity = killMutation.begin(
                   sessionId: requestedSessionId,
                   processId: process.id
               ) {
                killMutation.record(.rejected, for: identity)
                _ = killMutation.finish(identity)
            }
            return
        }
        guard let requestedSessionId = sessionId else { return }

        // Claim the mutation synchronously with the confirmation action so a
        // rapid second tap cannot enqueue another non-idempotent stop request
        // before the asynchronous task starts.
        guard let identity = killMutation.begin(
            sessionId: requestedSessionId,
            processId: process.id
        ) else { return }
        killTask = Task {
            await kill(identity)
        }
    }

    private func kill(_ identity: ProcessKillMutationIdentity) async {
        defer {
            if killMutation.finish(identity) {
                killTask = nil
            }
        }

        do {
            let receipt = try await api.killProcess(
                sessionId: identity.sessionId,
                processId: identity.processId
            )
            guard
                !Task.isCancelled,
                sessionId == identity.sessionId,
                killMutation.isCurrent(identity)
            else { return }

            switch receipt {
            case .killed, .alreadyExited:
                await reload()
            case .rejected:
                killMutation.record(.rejected, for: identity)
            }
        } catch is CancellationError {
            return
        } catch {
            guard
                !Task.isCancelled,
                sessionId == identity.sessionId,
                killMutation.isCurrent(identity)
            else { return }
            // A timeout or disconnect can happen after the gateway acted. Do
            // not replay this mutation: offer only a read-only refresh.
            killMutation.record(ProcessKillFeedback.classify(error), for: identity)
        }
    }

    private func resetKillMutation() {
        killTask?.cancel()
        killTask = nil
        processToKill = nil
        killMutation.reset()
    }
}
