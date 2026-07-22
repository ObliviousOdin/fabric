import Observation
import SwiftUI
import UIKit

/// Social Studio for iOS: a Compose tab that turns a brief into a post prompt
/// handed to a fresh chat (mirroring ConversationHomeView's launch flow), and a
/// Library tab that lists conversations which already produced a post so the
/// caption can be copied and pasted. Text-first v1 — the caption is always
/// shown; inbound workspace images are a separate gateway capability and are
/// intentionally not rendered here yet.
struct SocialStudioView: View {
    @Environment(AppModel.self) private var appModel

    @State private var tab = 0
    @State private var draft = ""
    @State private var goal: SocialGoal = .authority
    @State private var tone: SocialTone = .candid
    @State private var format: SocialFormat = .hookStory
    @State private var includeImage = true
    @State private var launch: SocialChatLaunch?
    @State private var library = SocialLibraryModel()

    var body: some View {
        VStack(spacing: 0) {
            Picker("View", selection: $tab) {
                Text("Compose").tag(0)
                Text("Library").tag(1)
            }
            .pickerStyle(.segmented)
            .padding()

            if tab == 0 {
                composer
            } else {
                libraryList
            }
        }
        .navigationTitle("Social Studio")
        .navigationDestination(item: $launch) { destination in
            ChatView(
                resumeStoredSessionId: destination.storedSessionID,
                title: destination.title,
                initialPrompt: destination.initialPrompt,
                onInitialPromptAttempted: {}
            )
        }
    }

    private var composer: some View {
        Form {
            Section("Brief") {
                TextField("What's the post about?", text: $draft, axis: .vertical)
                    .lineLimit(4...8)
            }

            Section {
                Picker("Goal", selection: $goal) {
                    ForEach(SocialGoal.allCases) { Text($0.label).tag($0) }
                }
                Picker("Voice", selection: $tone) {
                    ForEach(SocialTone.allCases) { Text($0.label).tag($0) }
                }
                Picker("Format", selection: $format) {
                    ForEach(SocialFormat.allCases) { Text($0.label).tag($0) }
                }
                Toggle("Include a matching image", isOn: $includeImage)
            }

            Section {
                Button("Draft in chat") {
                    let prompt = SocialPrompt.build(
                        SocialRequest(
                            brief: draft,
                            channel: .linkedin,
                            goal: goal,
                            tone: tone,
                            format: format,
                            includeImage: includeImage
                        )
                    )
                    launch = SocialChatLaunch(storedSessionID: nil, title: "New chat", initialPrompt: prompt)
                }
                .disabled(
                    draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || appModel.phase != .connected
                )
            } footer: {
                Text("This opens a fresh chat with the prepared brief so you can review it before sending.")
            }
        }
    }

    private var libraryList: some View {
        Group {
            if library.loading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if library.entries.isEmpty {
                ContentUnavailableView(
                    "No posts yet",
                    systemImage: "megaphone",
                    description: Text("Draft one in Compose. When the agent writes a post it shows up here to copy.")
                )
            } else {
                List(library.entries) { entry in
                    SocialCardView(entry: entry) {
                        launch = SocialChatLaunch(
                            storedSessionID: entry.session.id,
                            title: entry.session.displayTitle,
                            initialPrompt: nil
                        )
                    }
                }
                .listStyle(.plain)
            }
        }
        .task {
            await library.load(appModel: appModel)
        }
    }
}

private struct SocialChatLaunch: Identifiable, Hashable {
    let id = UUID()
    let storedSessionID: String?
    let title: String
    let initialPrompt: String?
}

private struct SocialCardView: View {
    let entry: SocialSessionEntry
    let onOpen: () -> Void

    var body: some View {
        let latest = entry.artifacts[entry.artifacts.count - 1]
        VStack(alignment: .leading, spacing: 8) {
            Text(entry.session.displayTitle)
                .font(.headline)
            Text(latest.caption)
                .font(.body)
            HStack(spacing: 12) {
                Button {
                    UIPasteboard.general.string = latest.caption
                } label: {
                    Label("Copy caption", systemImage: "doc.on.doc")
                }
                .buttonStyle(.borderedProminent)

                Button("Open", action: onOpen)
                    .buttonStyle(.bordered)
            }
        }
        .padding(.vertical, 4)
    }
}

/// A conversation that produced at least one post-ready artifact.
struct SocialSessionEntry: Identifiable {
    let session: SessionSummary
    let artifacts: [SocialArtifact]
    var id: String { session.id }
}

@Observable
final class SocialLibraryModel {
    var loading = true
    var entries: [SocialSessionEntry] = []

    func load(appModel: AppModel) async {
        loading = true
        defer { loading = false }

        guard appModel.supportsGatewayMethod("session.list"),
            appModel.supportsGatewayMethod("session.resume") else {
            entries = []
            return
        }

        do {
            let sessions = try await appModel.api.listSessions(limit: 20).filter { $0.messageCount > 0 }
            var result: [SocialSessionEntry] = []
            for session in sessions {
                if let live = try? await appModel.api.resumeSession(storedSessionId: session.id) {
                    let artifacts = SocialExtraction.extract(live.messages.map(SocialMessageAdapter.init))
                    if !artifacts.isEmpty {
                        result.append(SocialSessionEntry(session: session, artifacts: artifacts))
                    }
                }
            }
            entries = result
        } catch {
            entries = []
        }
    }
}

private struct SocialMessageAdapter: SocialSourceMessage {
    let role: String
    let content: String?
    let timestamp: Int?

    init(_ message: SessionTranscriptMessage) {
        role = message.role.rawValue
        content = message.text
        timestamp = nil
    }
}
