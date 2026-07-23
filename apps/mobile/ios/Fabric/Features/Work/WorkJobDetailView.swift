import SwiftUI

// Detail sheet for one Job. Works entirely off the bounded inbox summary —
// result and error bodies stay behind `job.get` and are intentionally not
// fetched here (a deliberate follow-up). The board offers the two safe,
// value-free mutations: cancel the Job, and answer a simple approval-style
// Attention. Requests that need typed input (clarify answers, secrets) are
// answered from the conversation, not the board.
struct WorkJobDetailView: View {
    let job: FabricWorkInboxJobSummary
    let onCancel: (String) async -> FabricWorkInboxCancellationResult
    let onRespond: (String, String) async -> FabricWorkInboxAttentionResult

    @Environment(\.dismiss) private var dismiss
    @State private var statusMessage: String?
    @State private var working = false

    private var statusStyle: (label: String, tone: WorkStatusTone) {
        WorkBoardPresentation.statusStyle(for: job.status)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header
                if let summary = job.summary, !summary.isEmpty {
                    Text(summary)
                        .font(.body)
                        .foregroundStyle(FabricTheme.text)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                metadata
                if !job.attention.isEmpty {
                    attentionSection
                }
                if job.hasResultPreview || job.hasErrorPreview {
                    outcomeNote
                }
                if let statusMessage {
                    Text(statusMessage)
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if job.canCancel {
                    cancelButton
                }
            }
            .padding(20)
        }
        .background(FabricTheme.canvas.ignoresSafeArea())
        .navigationTitle("Work item")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Done") { dismiss() }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(job.title)
                .font(.title3.weight(.semibold))
                .foregroundStyle(FabricTheme.text)
            WorkStatusChip(label: statusStyle.label, tone: statusStyle.tone)
        }
    }

    private var metadata: some View {
        VStack(alignment: .leading, spacing: 6) {
            metadataRow("Attempts", value: "\(job.attemptCount)")
            metadataRow("Updated", value: WorkTimeFormat.relative(millis: job.updatedAt))
            if let finishedAt = job.finishedAt {
                metadataRow("Finished", value: WorkTimeFormat.relative(millis: finishedAt))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
    }

    private func metadataRow(_ label: String, value: String) -> some View {
        HStack {
            Text(label)
                .font(.footnote)
                .foregroundStyle(FabricTheme.textMuted)
            Spacer()
            Text(value)
                .font(.footnote.weight(.medium))
                .foregroundStyle(FabricTheme.text)
        }
    }

    private var attentionSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Requests")
                .font(.headline)
                .foregroundStyle(FabricTheme.text)
            ForEach(job.attention) { attention in
                attentionRow(attention)
            }
        }
    }

    private func attentionRow(_ attention: FabricWorkInboxAttentionSummary) -> some View {
        let label = WorkBoardPresentation.attentionLabel(for: attention.kind)
        let simpleActions = attention.allowedActions.filter { $0 != "submit" }
        let needsTypedAnswer = attention.allowedActions.contains("submit")
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(attention.sensitive ? "\(label) (sensitive)" : label)
                    .font(.body.weight(.medium))
                    .foregroundStyle(FabricTheme.text)
                Spacer()
                Text(attention.state.capitalized)
                    .font(.caption)
                    .foregroundStyle(FabricTheme.textMuted)
            }
            if attention.canRespond, !simpleActions.isEmpty {
                FlowingActionButtons(
                    actions: simpleActions,
                    disabled: working
                ) { action in
                    Task { await respond(attention.id, action: action) }
                }
            }
            if needsTypedAnswer {
                Text("Answer this from the conversation.")
                    .font(.caption)
                    .foregroundStyle(FabricTheme.textMuted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(FabricTheme.surface, in: RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
    }

    private var outcomeNote: some View {
        Text(job.hasErrorPreview
             ? "This work reported an error. Open the conversation to read it."
             : "This work produced a result. Open the conversation to read it.")
            .font(.footnote)
            .foregroundStyle(FabricTheme.textMuted)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var cancelButton: some View {
        Button(role: .destructive) {
            Task { await cancel() }
        } label: {
            Text("Cancel this work")
                .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
        }
        .buttonStyle(.borderedProminent)
        .tint(FabricTheme.danger)
        .disabled(working)
        .accessibilityIdentifier("work-cancel-job")
    }

    private func cancel() async {
        working = true
        defer { working = false }
        let result = await onCancel(job.id)
        statusMessage = Self.message(for: result)
    }

    private func respond(_ attentionID: String, action: String) async {
        working = true
        defer { working = false }
        let result = await onRespond(attentionID, action)
        statusMessage = Self.message(for: result)
    }

    static func message(for result: FabricWorkInboxCancellationResult) -> String {
        switch result {
        case .requestAccepted: return "Cancellation requested."
        case .alreadyTerminal: return "This work already finished."
        case .unavailable: return "Work actions aren't available on this server."
        case .invalidState: return "This work can't be cancelled."
        case .reconciliationRequired: return "A previous action is still resolving."
        case .outcomeUnknown: return "Couldn't confirm the cancellation. Pull to refresh."
        case .stale: return "This view is out of date. Pull to refresh."
        }
    }

    static func message(for result: FabricWorkInboxAttentionResult) -> String {
        switch result {
        case .delivered: return "Response sent."
        case .unavailable: return "Work actions aren't available on this server."
        case .invalidState: return "This request can no longer be answered."
        case .reconciliationRequired: return "A previous response is still resolving."
        case .outcomeUnknown: return "Couldn't confirm the response. Pull to refresh."
        case .stale: return "This view is out of date. Pull to refresh."
        }
    }
}

/// Small wrapping row of action buttons for an Attention's allowed actions.
private struct FlowingActionButtons: View {
    let actions: [String]
    let disabled: Bool
    let onTap: (String) -> Void

    var body: some View {
        HStack(spacing: 8) {
            ForEach(actions, id: \.self) { action in
                Button(WorkAttentionAction.label(for: action)) {
                    onTap(action)
                }
                .buttonStyle(.bordered)
                .tint(action == "deny" ? FabricTheme.danger : FabricTheme.action)
                .disabled(disabled)
                .accessibilityIdentifier("work-attention-action-\(action)")
            }
        }
    }
}

enum WorkAttentionAction {
    static func label(for action: String) -> String {
        switch action {
        case "once": return "Allow once"
        case "session": return "Allow for session"
        case "always": return "Always allow"
        case "deny": return "Deny"
        case "cancel": return "Cancel request"
        default: return action.capitalized
        }
    }
}
