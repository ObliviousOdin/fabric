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
        mutationInFlight: Bool
    ) -> Bool {
        status.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "running"
            && supportsKill
            && !mutationInFlight
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
    @State private var killInFlightId: String?
    @State private var killFeedback: ProcessKillFeedback?
    @State private var killTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            List {
                if let killFeedback {
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
                    .disabled(loadState == .loading || killInFlightId != nil)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .task(id: sessionId) { await reload() }
            .onDisappear {
                loadGeneration += 1
                killTask?.cancel()
                killTask = nil
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
                        !RemoteControlPresentation.canStopProcess(
                            status: process.status,
                            supportsKill: supportsMethod("process.kill"),
                            mutationInFlight: killInFlightId != nil
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
            killFeedback = nil
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
        guard killInFlightId == nil else { return }
        guard supportsMethod("process.kill") else {
            killFeedback = .rejected
            return
        }
        guard let requestedSessionId = sessionId else { return }

        // Claim the mutation synchronously with the confirmation action so a
        // rapid second tap cannot enqueue another non-idempotent stop request
        // before the asynchronous task starts.
        killInFlightId = process.id
        killFeedback = nil
        killTask = Task {
            await kill(process, requestedSessionId: requestedSessionId)
        }
    }

    private func kill(
        _ process: BackgroundProcess,
        requestedSessionId: String
    ) async {
        defer {
            if sessionId == requestedSessionId {
                killInFlightId = nil
                killTask = nil
            }
        }

        do {
            try await api.killProcess(
                sessionId: requestedSessionId,
                processId: process.id
            )
            guard !Task.isCancelled, sessionId == requestedSessionId else { return }
            await reload()
        } catch is CancellationError {
            return
        } catch {
            guard !Task.isCancelled, sessionId == requestedSessionId else { return }
            // A timeout or disconnect can happen after the gateway acted. Do
            // not replay this mutation: offer only a read-only refresh.
            killFeedback = ProcessKillFeedback.classify(error)
        }
    }
}
