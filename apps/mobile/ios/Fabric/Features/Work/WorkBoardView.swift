import SwiftUI

// Phone kanban for the Durable Work inbox. The board is fail-closed: it only
// renders live data when the gateway advertises the complete `durable_work`
// contract and a chat session has published a runtime context (FMB-002). The
// tab itself is hidden entirely until the capability is advertised — this
// screen is reached only in that advertised state or from a DEBUG fixture.

/// What the board should show right now. `.ready` carries the inbox snapshot so
/// the screen can both project a `WorkBoardPresentation` and resolve a tapped
/// card back to its full summary for the detail sheet.
enum WorkBoardState: Equatable {
    case unavailable
    case noContext
    case ready(WorkBoardReadyState)
}

struct WorkBoardReadyState: Equatable {
    let sections: FabricWorkInboxSections
    let availability: FabricWorkInboxAvailability
    let isRefreshing: Bool
    let syncError: String?
    let lastUpdated: Date?

    var presentation: WorkBoardPresentation { WorkBoardPresentation.make(from: sections) }

    func summaries(for lane: WorkLaneKind) -> [FabricWorkInboxJobSummary] {
        switch lane {
        case .needsAttention: return sections.needsAttention
        case .active: return sections.active
        case .done: return sections.completed
        }
    }
}

/// Live tab entry. Reads the shared inbox off `AppModel` and provides the
/// gateway-backed mutation closures.
struct WorkBoardView: View {
    @Environment(AppModel.self) private var appModel

    var body: some View {
        WorkBoardScreen(
            state: state,
            onRefresh: { await appModel.refreshWork() },
            onCancel: { await appModel.cancelWorkJob($0) },
            onRespond: { await appModel.respondToWorkAttention($0, action: $1) }
        )
        .navigationTitle("Work")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var state: WorkBoardState {
        guard appModel.supportsDurableWork else { return .unavailable }
        guard appModel.workContext != nil else { return .noContext }
        return .ready(
            WorkBoardReadyState(
                sections: appModel.workInbox.sections,
                availability: appModel.workInbox.availability,
                isRefreshing: appModel.workInbox.isRefreshing,
                syncError: appModel.workInbox.syncError,
                lastUpdated: appModel.workInbox.lastUpdated
            )
        )
    }
}

/// Pure board content, shared by the live tab and the DEBUG fixture. It never
/// touches `AppModel`; every side effect goes through the injected closures.
struct WorkBoardScreen: View {
    let state: WorkBoardState
    let onRefresh: () async -> Void
    let onCancel: (String) async -> FabricWorkInboxCancellationResult
    let onRespond: (String, String) async -> FabricWorkInboxAttentionResult

    @State private var lane: WorkLaneKind = .needsAttention
    @State private var selectedJob: FabricWorkInboxJobSummary?

    var body: some View {
        content
            .background(FabricTheme.canvas.ignoresSafeArea())
            .task { await onRefresh() }
            .sheet(item: $selectedJob) { job in
                NavigationStack {
                    WorkJobDetailView(job: job, onCancel: onCancel, onRespond: onRespond)
                }
            }
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .unavailable:
            ContentUnavailableView(
                "Work isn't available",
                systemImage: "tray",
                description: Text("This Fabric server doesn't offer the Work inbox yet.")
            )
        case .noContext:
            ContentUnavailableView(
                "No work to sync",
                systemImage: "bubble.left.and.bubble.right",
                description: Text("Open or start a conversation and Fabric will sync its background work here.")
            )
        case .ready(let ready):
            readyBoard(ready)
        }
    }

    private func readyBoard(_ ready: WorkBoardReadyState) -> some View {
        let presentation = ready.presentation
        return ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Picker("Lane", selection: $lane) {
                    ForEach(WorkLaneKind.allCases) { kind in
                        Text("\(kind.title) (\(presentation.lane(kind).count))").tag(kind)
                    }
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("work-board-lane-picker")

                if let banner = bannerData(ready) {
                    WorkBoardBanner(text: banner.text, tone: banner.tone)
                }

                let summaries = ready.summaries(for: lane)
                if summaries.isEmpty {
                    emptyLane
                } else {
                    ForEach(summaries) { summary in
                        Button {
                            selectedJob = summary
                        } label: {
                            WorkCardView(card: WorkCardPresentation(job: summary))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("work-card-\(summary.id)")
                    }
                }

                if lane == .needsAttention, !presentation.unboundAttention.isEmpty {
                    unboundAttentionSection(presentation.unboundAttention)
                }

                if presentation.unsupportedCount > 0 {
                    Text("\(presentation.unsupportedCount) item\(presentation.unsupportedCount == 1 ? "" : "s") need a newer app version to act on.")
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(20)
        }
        .refreshable { await onRefresh() }
    }

    private var emptyLane: some View {
        Text("Nothing here right now.")
            .font(.body)
            .foregroundStyle(FabricTheme.textMuted)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 24)
    }

    private func bannerData(_ ready: WorkBoardReadyState) -> (text: String, tone: WorkStatusTone)? {
        if let error = ready.syncError {
            return (error, .attention)
        }
        if ready.availability == .stale {
            return ("Showing the last synced work. Pull to refresh.", .neutral)
        }
        if ready.availability == .syncing || ready.isRefreshing {
            return ("Syncing work…", .neutral)
        }
        return nil
    }

    private func unboundAttentionSection(_ badges: [WorkAttentionBadge]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Other open requests")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(FabricTheme.text)
            ForEach(badges) { badge in
                HStack(spacing: 8) {
                    Image(systemName: badge.blocking ? "exclamationmark.circle.fill" : "circle")
                        .foregroundStyle(badge.blocking ? FabricTheme.warning : FabricTheme.textMuted)
                        .accessibilityHidden(true)
                    Text(badge.sensitive ? "\(badge.label) (sensitive)" : badge.label)
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.text)
                    Spacer()
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
    }
}

private struct WorkBoardBanner: View {
    let text: String
    let tone: WorkStatusTone

    var body: some View {
        Text(text)
            .font(.footnote)
            .foregroundStyle(tone == .attention ? FabricTheme.warning : FabricTheme.textMuted)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .background(
                (tone == .attention ? FabricTheme.warning : FabricTheme.textMuted).fabricTint(),
                in: RoundedRectangle(cornerRadius: FabricTheme.radiusChip)
            )
    }
}

struct WorkCardView: View {
    let card: WorkCardPresentation

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(card.title)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(FabricTheme.text)
                    .lineLimit(2)
                Spacer(minLength: 8)
                WorkStatusChip(label: card.statusLabel, tone: card.statusTone)
            }

            if let subtitle = card.subtitle {
                Text(subtitle)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .lineLimit(3)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            if !card.attention.isEmpty {
                WorkAttentionChips(badges: card.attention)
            }

            HStack(spacing: 12) {
                Text(WorkTimeFormat.relative(millis: card.updatedAt))
                    .font(.caption)
                    .foregroundStyle(FabricTheme.textMuted)
                Spacer()
                if card.hasErrorPreview {
                    Label("Error", systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundStyle(FabricTheme.danger)
                        .labelStyle(.titleAndIcon)
                } else if card.hasResultPreview {
                    Label("Result", systemImage: "doc.text")
                        .font(.caption)
                        .foregroundStyle(FabricTheme.textMuted)
                        .labelStyle(.titleAndIcon)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
        .overlay {
            RoundedRectangle(cornerRadius: FabricTheme.radiusLarge)
                .stroke(FabricTheme.border, lineWidth: 1)
        }
    }
}

struct WorkStatusChip: View {
    let label: String
    let tone: WorkStatusTone

    var body: some View {
        Text(label)
            .font(.caption.weight(.semibold))
            .foregroundStyle(WorkStatusPalette.color(tone))
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(
                WorkStatusPalette.color(tone).fabricTint(),
                in: Capsule()
            )
            .fixedSize()
    }
}

struct WorkAttentionChips: View {
    let badges: [WorkAttentionBadge]

    var body: some View {
        HStack(spacing: 6) {
            ForEach(badges) { badge in
                Text(badge.sensitive ? "\(badge.label) 🔒" : badge.label)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(badge.blocking ? FabricTheme.warning : FabricTheme.textMuted)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 2)
                    .background(
                        (badge.blocking ? FabricTheme.warning : FabricTheme.textMuted).fabricTint(),
                        in: Capsule()
                    )
            }
        }
    }
}

enum WorkStatusPalette {
    static func color(_ tone: WorkStatusTone) -> Color {
        switch tone {
        case .neutral: return FabricTheme.textMuted
        case .running: return FabricTheme.action
        case .attention: return FabricTheme.warning
        case .success: return FabricTheme.success
        case .failure: return FabricTheme.danger
        case .cancelled: return FabricTheme.textMuted
        }
    }
}

enum WorkTimeFormat {
    /// Contract timestamps are epoch milliseconds; render a live relative label.
    static func relative(millis: Int) -> String {
        guard millis > 0 else { return "—" }
        let date = Date(timeIntervalSince1970: TimeInterval(millis) / 1000)
        return date.formatted(.relative(presentation: .named))
    }
}
