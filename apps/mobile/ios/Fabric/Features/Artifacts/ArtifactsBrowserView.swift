import SwiftUI
import UIKit

// A browser for the images, files, and links an agent produced in a session,
// derived client-side from transcripts (no server artifact index exists yet).
// Genuinely external images (http/https/data URLs) preview inline via
// AsyncImage; workspace files and file-path images show as cards with a
// copy-path action. Fetching authenticated workspace-file bytes for inline
// preview/Quick Look, and a server-indexed `artifact.list`/`artifact.fetch`
// path, are deliberate follow-ups.

enum ArtifactFilter: String, CaseIterable, Identifiable {
    case all
    case images
    case files
    case links

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all: return "All"
        case .images: return "Images"
        case .files: return "Files"
        case .links: return "Links"
        }
    }

    var kind: TranscriptArtifactKind? {
        switch self {
        case .all: return nil
        case .images: return .image
        case .files: return .file
        case .links: return .link
        }
    }

    func matches(_ artifact: TranscriptArtifact) -> Bool {
        guard let kind else { return true }
        return artifact.kind == kind
    }
}

@MainActor @Observable
final class ArtifactsLibraryModel {
    var loading = true
    var artifacts: [TranscriptArtifact] = []

    /// Load recent sessions and derive their artifacts. Mirrors
    /// `SocialLibraryModel.load`: gated on the transcript methods, bounded to a
    /// recent window, and published incrementally so results appear as sessions
    /// resolve.
    func load(appModel: AppModel) async {
        loading = true
        defer { loading = false }

        guard appModel.supportsGatewayMethod("session.list"),
              appModel.supportsGatewayMethod("session.transcript") else {
            artifacts = []
            return
        }

        do {
            let sessions = try await appModel.api.listSessions(limit: 30)
                .filter { $0.messageCount > 0 }
            var collected: [TranscriptArtifact] = []
            for session in sessions {
                if let messages = try? await appModel.api.sessionTranscript(storedSessionId: session.id) {
                    collected.append(
                        contentsOf: TranscriptArtifactExtraction.collect(
                            session: session,
                            messages: messages
                        )
                    )
                    artifacts = collected
                }
            }
            artifacts = collected
        } catch {
            artifacts = []
        }
    }

    func filtered(_ filter: ArtifactFilter) -> [TranscriptArtifact] {
        artifacts.filter(filter.matches)
    }

    func count(_ filter: ArtifactFilter) -> Int {
        filtered(filter).count
    }
}

struct ArtifactsBrowserView: View {
    @Environment(AppModel.self) private var appModel
    @State private var model = ArtifactsLibraryModel()
    @State private var filter: ArtifactFilter = .all

    private var supported: Bool {
        appModel.supportsGatewayMethod("session.list")
            && appModel.supportsGatewayMethod("session.transcript")
    }

    var body: some View {
        Group {
            if supported {
                content
            } else {
                ContentUnavailableView(
                    "Artifacts unavailable",
                    systemImage: "photo.on.rectangle.angled",
                    description: Text("This Fabric server can't list session artifacts.")
                )
            }
        }
        .background(FabricTheme.canvas.ignoresSafeArea())
        .navigationTitle("Artifacts")
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load(appModel: appModel) }
        .refreshable { await model.load(appModel: appModel) }
    }

    @ViewBuilder
    private var content: some View {
        let items = model.filtered(filter)
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Picker("Filter", selection: $filter) {
                    ForEach(ArtifactFilter.allCases) { option in
                        Text("\(option.title) (\(model.count(option)))").tag(option)
                    }
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("artifacts-filter")

                if model.loading && model.artifacts.isEmpty {
                    ProgressView("Scanning sessions…")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 32)
                } else if items.isEmpty {
                    Text("No \(filter == .all ? "artifacts" : filter.title.lowercased()) found in recent sessions.")
                        .font(.body)
                        .foregroundStyle(FabricTheme.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 24)
                } else {
                    ForEach(items) { artifact in
                        ArtifactRowView(artifact: artifact)
                    }
                }
            }
            .padding(20)
        }
    }
}

/// One artifact row: an inline thumbnail for external images, otherwise a typed
/// card. Links and external images open in the browser; every row can copy its
/// value.
struct ArtifactRowView: View {
    let artifact: TranscriptArtifact

    @Environment(\.openURL) private var openURL

    private var externalURL: URL? {
        guard artifact.value.hasPrefix("http://") || artifact.value.hasPrefix("https://") else {
            return nil
        }
        return URL(string: artifact.value)
    }

    private var isPreviewableImage: Bool {
        guard artifact.kind == .image else { return false }
        let lower = artifact.value.lowercased()
        return lower.hasPrefix("http://") || lower.hasPrefix("https://") || lower.hasPrefix("data:image/")
    }

    var body: some View {
        Group {
            if let externalURL {
                Button {
                    openURL(externalURL)
                } label: { rowBody }
                .buttonStyle(.plain)
            } else {
                rowBody
            }
        }
        .contextMenu {
            Button {
                UIPasteboard.general.string = artifact.value
            } label: {
                Label("Copy value", systemImage: "doc.on.doc")
            }
            if let externalURL {
                Button {
                    openURL(externalURL)
                } label: {
                    Label("Open link", systemImage: "safari")
                }
            }
        }
        .accessibilityIdentifier("artifact-row-\(artifact.id)")
    }

    private var rowBody: some View {
        HStack(alignment: .top, spacing: 12) {
            thumbnail
            VStack(alignment: .leading, spacing: 4) {
                Text(artifact.label)
                    .font(.body.weight(.medium))
                    .foregroundStyle(FabricTheme.text)
                    .lineLimit(2)
                Text(artifact.value)
                    .font(.caption)
                    .foregroundStyle(FabricTheme.textMuted)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Text(artifact.sessionTitle)
                    .font(.caption2)
                    .foregroundStyle(FabricTheme.textMuted)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
        .overlay {
            RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                .stroke(FabricTheme.border, lineWidth: 1)
        }
    }

    @ViewBuilder
    private var thumbnail: some View {
        if isPreviewableImage, let url = URL(string: artifact.value) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFill()
                case .failure:
                    kindIcon
                case .empty:
                    ProgressView()
                @unknown default:
                    kindIcon
                }
            }
            .frame(width: 56, height: 56)
            .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radiusChip))
        } else {
            kindIcon
        }
    }

    private var kindIcon: some View {
        Image(systemName: symbol)
            .font(.title3)
            .foregroundStyle(FabricTheme.textMuted)
            .frame(width: 56, height: 56)
            .background(FabricTheme.surfaceInset, in: RoundedRectangle(cornerRadius: FabricTheme.radiusChip))
    }

    private var symbol: String {
        switch artifact.kind {
        case .image: return "photo"
        case .file: return "doc"
        case .link: return "link"
        }
    }
}
