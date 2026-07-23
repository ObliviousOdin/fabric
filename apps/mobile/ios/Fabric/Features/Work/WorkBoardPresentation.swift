import Foundation

// Pure, view-independent projection of the Durable Work inbox into a phone
// kanban board: three lanes (Needs attention / Active / Done), plus the
// unbound-attention and unsupported tallies the inbox keeps separate. All
// mapping here is deterministic and synchronous so it can be unit-tested
// without SwiftUI or a live gateway.

/// Semantic tone for a Job status chip. The view maps each case to a color.
enum WorkStatusTone: Equatable {
    case neutral
    case running
    case attention
    case success
    case failure
    case cancelled
}

/// A short chip describing one open Attention on a Job (or an unbound one).
struct WorkAttentionBadge: Identifiable, Equatable {
    let id: String
    let label: String
    let blocking: Bool
    let sensitive: Bool

    init(id: String, label: String, blocking: Bool, sensitive: Bool) {
        self.id = id
        self.label = label
        self.blocking = blocking
        self.sensitive = sensitive
    }

    init(summary: FabricWorkInboxAttentionSummary) {
        self.init(
            id: summary.id,
            label: WorkBoardPresentation.attentionLabel(for: summary.kind),
            blocking: summary.blocking,
            sensitive: summary.sensitive
        )
    }
}

/// One board card. Result and error bodies are never copied here — only their
/// availability and an exact transcript route, matching the inbox summary.
struct WorkCardPresentation: Identifiable, Equatable {
    let id: String
    let title: String
    let subtitle: String?
    let statusLabel: String
    let statusTone: WorkStatusTone
    let attention: [WorkAttentionBadge]
    let updatedAt: Int
    let canCancel: Bool
    let hasTranscriptRoute: Bool
    let hasResultPreview: Bool
    let hasErrorPreview: Bool

    init(
        id: String,
        title: String,
        subtitle: String?,
        statusLabel: String,
        statusTone: WorkStatusTone,
        attention: [WorkAttentionBadge],
        updatedAt: Int,
        canCancel: Bool,
        hasTranscriptRoute: Bool,
        hasResultPreview: Bool,
        hasErrorPreview: Bool
    ) {
        self.id = id
        self.title = title
        self.subtitle = subtitle
        self.statusLabel = statusLabel
        self.statusTone = statusTone
        self.attention = attention
        self.updatedAt = updatedAt
        self.canCancel = canCancel
        self.hasTranscriptRoute = hasTranscriptRoute
        self.hasResultPreview = hasResultPreview
        self.hasErrorPreview = hasErrorPreview
    }

    init(job: FabricWorkInboxJobSummary) {
        let style = WorkBoardPresentation.statusStyle(for: job.status)
        let trimmedSummary = job.summary?.trimmingCharacters(in: .whitespacesAndNewlines)
        self.init(
            id: job.id,
            title: job.title,
            subtitle: (trimmedSummary?.isEmpty ?? true) ? nil : trimmedSummary,
            statusLabel: style.label,
            statusTone: style.tone,
            attention: job.attention.map(WorkAttentionBadge.init(summary:)),
            updatedAt: job.updatedAt,
            canCancel: job.canCancel,
            hasTranscriptRoute: job.transcriptRoute != nil,
            hasResultPreview: job.hasResultPreview,
            hasErrorPreview: job.hasErrorPreview
        )
    }
}

enum WorkLaneKind: String, CaseIterable, Identifiable {
    case needsAttention
    case active
    case done

    var id: String { rawValue }

    var title: String {
        switch self {
        case .needsAttention: return "Needs attention"
        case .active: return "Active"
        case .done: return "Done"
        }
    }

    var systemImage: String {
        switch self {
        case .needsAttention: return "exclamationmark.bubble"
        case .active: return "bolt.horizontal"
        case .done: return "checkmark.circle"
        }
    }
}

struct WorkLanePresentation: Equatable {
    let kind: WorkLaneKind
    let cards: [WorkCardPresentation]

    var count: Int { cards.count }
    var isEmpty: Bool { cards.isEmpty }
}

struct WorkBoardPresentation: Equatable {
    /// Always the three lanes, in display order.
    let lanes: [WorkLanePresentation]
    /// Open Attention not attributable to a needs-attention Job, surfaced
    /// separately instead of being silently dropped.
    let unboundAttention: [WorkAttentionBadge]
    /// Compatible-but-not-actionable subjects (future kinds/statuses). Shown as
    /// a count so they remain discoverable without a mutation surface.
    let unsupportedCount: Int

    func lane(_ kind: WorkLaneKind) -> WorkLanePresentation {
        lanes.first { $0.kind == kind } ?? WorkLanePresentation(kind: kind, cards: [])
    }

    var isEmpty: Bool {
        lanes.allSatisfy(\.isEmpty) && unboundAttention.isEmpty && unsupportedCount == 0
    }

    static func make(from sections: FabricWorkInboxSections) -> WorkBoardPresentation {
        WorkBoardPresentation(
            lanes: [
                WorkLanePresentation(
                    kind: .needsAttention,
                    cards: sections.needsAttention.map(WorkCardPresentation.init(job:))
                ),
                WorkLanePresentation(
                    kind: .active,
                    cards: sections.active.map(WorkCardPresentation.init(job:))
                ),
                WorkLanePresentation(
                    kind: .done,
                    cards: sections.completed.map(WorkCardPresentation.init(job:))
                ),
            ],
            unboundAttention: sections.unboundAttention.map(WorkAttentionBadge.init(summary:)),
            unsupportedCount: sections.unsupportedJobs.count
                + sections.unsupportedAttention.count
                + sections.unsupportedSubjects.count
        )
    }

    /// Human label + tone for a Job status. Unknown future statuses render with
    /// a title-cased fallback and a neutral tone rather than being hidden.
    static func statusStyle(for status: String) -> (label: String, tone: WorkStatusTone) {
        switch status {
        case "queued": return ("Queued", .neutral)
        case "claimed": return ("Starting", .running)
        case "running": return ("Running", .running)
        case "waiting_attention": return ("Needs attention", .attention)
        case "cancel_requested": return ("Cancelling", .neutral)
        case "succeeded": return ("Done", .success)
        case "failed": return ("Failed", .failure)
        case "cancelled": return ("Cancelled", .cancelled)
        case "interrupted": return ("Interrupted", .failure)
        default: return (titleCased(status), .neutral)
        }
    }

    static func attentionLabel(for kind: String) -> String {
        switch kind {
        case "approval": return "Approval"
        case "clarify": return "Question"
        case "sudo": return "Admin access"
        case "secret": return "Secret"
        default: return titleCased(kind)
        }
    }

    private static func titleCased(_ raw: String) -> String {
        let cleaned = raw.replacingOccurrences(of: "_", with: " ")
        guard !cleaned.isEmpty else { return "Unknown" }
        return cleaned.prefix(1).uppercased() + cleaned.dropFirst()
    }
}
