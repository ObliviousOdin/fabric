import SwiftUI

/// The slash-command catalog (`commands.catalog`), grouped by category.
/// Tapping a command hands it back to the composer for arguments.
struct CommandCatalogSheet: View {
    let api: GatewayAPI
    let onSelect: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var categories: [SlashCommandCategory] = []
    @State private var searchText = ""
    @State private var loadError: String?

    private var filtered: [SlashCommandCategory] {
        let query = searchText.trimmingCharacters(in: .whitespaces).lowercased()
        guard !query.isEmpty else { return categories }
        return categories.compactMap { category in
            let commands = category.commands.filter {
                $0.name.lowercased().contains(query) || $0.detail.lowercased().contains(query)
            }
            return commands.isEmpty
                ? nil
                : SlashCommandCategory(name: category.name, commands: commands)
        }
    }

    var body: some View {
        NavigationStack {
            List {
                if let loadError {
                    Text(loadError)
                        .font(.footnote)
                        .foregroundStyle(.red)
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
                                            .foregroundStyle(.secondary)
                                            .lineLimit(2)
                                    }
                                }
                            }
                            .foregroundStyle(.primary)
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
            .task {
                do {
                    categories = try await api.commandCatalog()
                } catch {
                    loadError = error.localizedDescription
                }
            }
        }
    }
}

/// Background processes owned by this session (`process.list`), with
/// kill control and the output tail for a quick health check.
struct ProcessListSheet: View {
    let api: GatewayAPI
    let sessionId: String?

    @Environment(\.dismiss) private var dismiss
    @State private var processes: [BackgroundProcess] = []
    @State private var loading = true
    @State private var loadError: String?

    var body: some View {
        NavigationStack {
            List {
                if let loadError {
                    Text(loadError)
                        .font(.footnote)
                        .foregroundStyle(.red)
                } else if processes.isEmpty && !loading {
                    Text("No background processes for this session.")
                        .foregroundStyle(.secondary)
                }

                ForEach(processes) { process in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Circle()
                                .fill(process.status == "running" ? .green : .gray)
                                .frame(width: 8, height: 8)
                            Text(process.command)
                                .font(.caption.monospaced())
                                .lineLimit(2)
                            Spacer()
                            if process.status == "running" {
                                Button("Kill", role: .destructive) {
                                    Task { await kill(process) }
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                            }
                        }
                        Text("pid \(process.pid) · up \(process.uptimeSeconds)s · \(process.status)")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        if !process.outputTail.isEmpty {
                            Text(process.outputTail.suffix(400))
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                                .lineLimit(6)
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
            .navigationTitle("Processes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        Task { await reload() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Refresh processes")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .task { await reload() }
        }
    }

    private func reload() async {
        guard let sessionId else {
            loadError = "No live session."
            loading = false
            return
        }
        loading = true
        defer { loading = false }
        do {
            processes = try await api.listProcesses(sessionId: sessionId)
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func kill(_ process: BackgroundProcess) async {
        guard let sessionId else { return }
        do {
            try await api.killProcess(sessionId: sessionId, processId: process.id)
            await reload()
        } catch {
            loadError = error.localizedDescription
        }
    }
}
