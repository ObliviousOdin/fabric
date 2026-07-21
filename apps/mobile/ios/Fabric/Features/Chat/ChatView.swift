import SwiftUI
import UIKit

/// Chat transcript + composer for one Fabric session, with the same
/// dispatch/remote-control surface the TUI composer exposes: slash
/// commands, steering, background tasks, and process control.
struct ChatView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    let resumeStoredSessionId: String?
    let title: String
    let onInitialPromptAttempted: () -> Void

    @State private var model: ChatViewModel?
    @State private var draft = ""
    @State private var initialPromptDispatch: InitialPromptDispatch

    init(
        resumeStoredSessionId: String?,
        title: String,
        initialPrompt: String? = nil,
        onInitialPromptAttempted: @escaping () -> Void = {}
    ) {
        self.resumeStoredSessionId = resumeStoredSessionId
        self.title = title
        self.onInitialPromptAttempted = onInitialPromptAttempted
        _initialPromptDispatch = State(
            initialValue: InitialPromptDispatch(prompt: initialPrompt)
        )
    }

    var body: some View {
        Group {
            if let model {
                ChatContentView(
                    model: model,
                    draft: $draft,
                    recoveryAction: SessionRecoveryAction(
                        storedSessionId: model.storedSessionId
                    ),
                    onRetrySession: {
                        Task { await retrySession(using: model) }
                    },
                    onReturnToConversations: { dismiss() }
                )
            } else {
                ProgressView()
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .task(id: appModel.connectionGeneration) {
            if model == nil {
                let vm = ChatViewModel(
                    api: appModel.api,
                    resumeStoredSessionId: resumeStoredSessionId,
                    supportsMethod: { method in
                        appModel.supportsGatewayMethod(method)
                    },
                    durableWorkNegotiation: {
                        appModel.capabilityNegotiation
                    },
                    workGatewayID: {
                        appModel.activeGatewayId
                    }
                )
                model = vm
                await vm.start()
                await dispatchInitialPromptIfReady(using: vm)
            } else if appModel.phase == .connected {
                if let model {
                    await model.resumeAfterReconnect()
                    await dispatchInitialPromptIfReady(using: model)
                }
            }
        }
        .onChange(of: appModel.phase) { oldPhase, newPhase in
            if oldPhase == .connected, newPhase != .connected {
                model?.connectionDidClose()
            }
        }
        .onDisappear {
            model?.stop()
        }
        .toolbar(.visible, for: .navigationBar)
    }

    private func dispatchInitialPromptIfReady(using model: ChatViewModel) async {
        guard let prompt = initialPromptDispatch.beginIfReady(
            model.canSubmitInitialPrompt,
            onAttempt: onInitialPromptAttempted
        ) else { return }
        // `prompt.submit` is not idempotent. Consume this launch intent before
        // awaiting the network so reconnect/task re-entry cannot submit the
        // same user goal twice. If session bootstrap was interrupted after its
        // durable key was issued, the first successful resume still gets the
        // launch prompt.
        await model.sendInitialPrompt(prompt)
    }

    private func retrySession(using model: ChatViewModel) async {
        // Creating a session is not idempotent. A failed create response can
        // mean the gateway created the session but the client missed the
        // receipt, so only a known durable key is safe to retry.
        guard model.storedSessionId != nil else { return }
        await model.resumeAfterReconnect()
        await dispatchInitialPromptIfReady(using: model)
    }
}

enum SessionRecoveryAction: Equatable {
    case retryResume
    case returnToConversations

    init(storedSessionId: String?) {
        self = storedSessionId?.isEmpty == false
            ? .retryResume
            : .returnToConversations
    }
}

/// One-shot launch intent for the conversation-first home. Keeping this as a
/// tiny value type makes the no-double-submit invariant unit-testable without
/// constructing a live WebSocket client.
struct InitialPromptDispatch: Equatable {
    private let prompt: String?
    private(set) var attempted = false

    init(prompt: String?) {
        let trimmed = prompt?.trimmingCharacters(in: .whitespacesAndNewlines)
        self.prompt = (trimmed?.isEmpty == false) ? trimmed : nil
    }

    mutating func beginIfReady(
        _ ready: Bool,
        onAttempt: () -> Void = {}
    ) -> String? {
        guard ready, !attempted, let prompt else { return nil }
        attempted = true
        // Synchronous by contract: Home clears only the matching launch draft
        // before the non-cancellable JSON-RPC await can yield or complete late.
        onAttempt()
        return prompt
    }
}

private struct ChatContentView: View {
    @Bindable var model: ChatViewModel
    @Binding var draft: String
    let recoveryAction: SessionRecoveryAction
    let onRetrySession: () -> Void
    let onReturnToConversations: () -> Void

    @State private var showCommandCatalog = false
    @State private var showProcesses = false
    @State private var showLiveView = false
    @State private var promptAnswer = ""

    var body: some View {
        VStack(spacing: 0) {
            if let warning = model.persistenceWarning {
                Label(warning, systemImage: "externaldrive.badge.exclamationmark")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.warning)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)
                    .padding(.vertical, 8)
                    .background(FabricTheme.warning.fabricTint())
            }
            if let sessionError = model.sessionError {
                VStack(spacing: 12) {
                    ContentUnavailableView(
                        "Session unavailable",
                        systemImage: "exclamationmark.triangle",
                        description: Text(sessionError)
                    )
                    switch recoveryAction {
                    case .retryResume:
                        Button("Retry session", action: onRetrySession)
                            .buttonStyle(.borderedProminent)
                            .frame(minHeight: FabricTheme.minTarget)
                    case .returnToConversations:
                        Button("Back to conversations", action: onReturnToConversations)
                            .buttonStyle(.borderedProminent)
                            .frame(minHeight: FabricTheme.minTarget)
                            .accessibilityHint("Your goal remains preserved on Home")
                    }
                }
            } else {
                transcript
            }

            if let approval = model.pendingApproval {
                approvalBanner(approval)
                    .disabled(
                        !model.sessionReady
                            || !model.supportsGatewayMethod("approval.respond")
                    )
            }

            if let prompt = model.pendingPrompt {
                promptBanner(prompt)
                    .disabled(
                        !model.sessionReady
                            || !model.supportsGatewayMethod(prompt.responseMethod)
                    )
            }

            if let status = model.statusLine {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.mini)
                    Text(status)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Spacer()
                }
                .padding(.horizontal)
                .padding(.vertical, 4)
            }

            composer
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button {
                        showCommandCatalog = true
                    } label: {
                        Label("Commands…", systemImage: "slash.circle")
                    }
                    .disabled(
                        !model.supportsGatewayMethod("commands.catalog")
                            || !model.supportsGatewayMethod("slash.exec")
                    )
                    Button {
                        let text = draft
                        draft = ""
                        Task { await model.sendInBackground(text) }
                    } label: {
                        Label("Run draft in background", systemImage: "moon.zzz")
                    }
                    .disabled(
                        draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || !model.canSendInBackground
                    )
                    Button {
                        showProcesses = true
                    } label: {
                        Label("Background processes…", systemImage: "terminal")
                    }
                    .disabled(!model.supportsGatewayMethod("process.list"))
                    Button {
                        showLiveView = true
                    } label: {
                        Label("Live screen view…", systemImage: "display")
                    }
                    .disabled(!model.supportsGatewayMethod("computer.screenshot"))
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
                .accessibilityLabel("Chat actions")
                .disabled(!model.sessionReady)
            }
        }
        .sheet(isPresented: $showCommandCatalog) {
            CommandCatalogSheet(
                api: model.api,
                supportsMethod: model.supportsGatewayMethod
            ) { command in
                draft = command + " "
                showCommandCatalog = false
            }
        }
        .sheet(isPresented: $showProcesses) {
            ProcessListSheet(
                api: model.api,
                sessionId: model.sessionId,
                supportsMethod: model.supportsGatewayMethod
            )
        }
        .sheet(isPresented: $showLiveView) {
            LiveViewSheet(api: model.api, supportsMethod: model.supportsGatewayMethod)
        }
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(model.messages) { message in
                        MessageBubble(message: message)
                            .id(message.id)
                    }
                }
                .padding()
            }
            .onChange(of: model.messages) {
                if let lastId = model.messages.last?.id {
                    proxy.scrollTo(lastId, anchor: .bottom)
                }
            }
        }
    }

    /// Waiting-for-approval banner. Status language per the design contract:
    /// an amber marker + explicit label, with the status color held to a
    /// tint and an edge marker — never a fully saturated panel.
    private func approvalBanner(_ approval: PendingApproval) -> some View {
        HStack(spacing: 0) {
            Rectangle()
                .fill(FabricTheme.warning)
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Circle()
                        .fill(FabricTheme.warning)
                        .frame(width: 8, height: 8)
                    Text("Waiting for approval")
                        .font(.subheadline.weight(.semibold))
                }
                if let command = approval.command, !command.isEmpty {
                    Text(command)
                        .font(.caption.monospaced())
                        .lineLimit(4)
                }
                HStack {
                    Button("Allow") {
                        Task { await model.respondToApproval(allow: true) }
                    }
                    .buttonStyle(.borderedProminent)
                    Button("Deny", role: .destructive) {
                        Task { await model.respondToApproval(allow: false) }
                    }
                    .buttonStyle(.bordered)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
        .background(FabricTheme.warning.fabricTint())
        .fixedSize(horizontal: false, vertical: true)
    }

    /// Blocking agent prompt: clarify choices as buttons, plus a free-text
    /// (or secure, for sudo/secret) answer field.
    private func promptBanner(_ prompt: PendingPrompt) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(
                prompt.kind == .clarify ? "The agent has a question" : "Credential requested",
                systemImage: prompt.kind == .clarify ? "questionmark.bubble" : "key"
            )
            .font(.subheadline.weight(.semibold))

            Text(prompt.question)
                .font(.callout)

            if !prompt.choices.isEmpty {
                ForEach(prompt.choices, id: \.self) { choice in
                    Button(choice) {
                        promptAnswer = ""
                        Task { await model.respondToPrompt(choice) }
                    }
                    .buttonStyle(.bordered)
                }
            }

            HStack {
                Group {
                    if prompt.isSecureEntry {
                        SecureField("Answer", text: $promptAnswer)
                    } else {
                        TextField("Answer", text: $promptAnswer)
                    }
                }
                .textFieldStyle(.roundedBorder)

                Button("Send") {
                    let answer = promptAnswer
                    promptAnswer = ""
                    Task { await model.respondToPrompt(answer) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(promptAnswer.isEmpty)

                Button("Dismiss", role: .cancel) {
                    promptAnswer = ""
                    Task { await model.respondToPrompt("") }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(FabricTheme.info.fabricTint())
    }

    private var composer: some View {
        HStack(spacing: 8) {
            TextField(
                model.busy ? "Steer the running turn…" : "Message Fabric… (/ for commands)",
                text: $draft,
                axis: .vertical
            )
            .textFieldStyle(.roundedBorder)
            .lineLimit(1...5)
            .disabled(
                !model.sessionReady
                    || !model.supportsGatewayMethod(draftDispatchMethod)
            )

            if model.busy {
                // Steering send: injects the note without interrupting. The
                // active-thread color marks it as touching the live turn.
                Button {
                    let text = draft
                    draft = ""
                    Task { await model.send(text) }
                } label: {
                    Image(systemName: "arrow.uturn.right.circle.fill")
                        .font(.title2)
                        .foregroundStyle(FabricTheme.threadActive)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .accessibilityLabel("Steer running turn")
                .disabled(
                    draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || !model.supportsGatewayMethod("session.steer")
                )

                Button {
                    Task { await model.interrupt() }
                } label: {
                    Image(systemName: "stop.circle.fill")
                        .font(.title2)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .accessibilityLabel("Interrupt running turn")
                .disabled(!model.supportsGatewayMethod("session.interrupt"))
            } else {
                Button {
                    let text = draft
                    draft = ""
                    Task { await model.send(text) }
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title2)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .accessibilityLabel("Send message")
                .disabled(
                    !model.sessionReady
                        || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || !model.supportsGatewayMethod(draftDispatchMethod)
                )
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .disabled(!model.sessionReady)
    }

    private var draftDispatchMethod: String {
        if model.busy { return "session.steer" }
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.hasPrefix("/") ? "slash.exec" : "prompt.submit"
    }
}

private struct MessageBubble: View {
    let message: TranscriptMessage

    var body: some View {
        switch message.role {
        // Purple marks user-controlled elements (contract): the user's own
        // words are the one solid-accent surface in the transcript.
        case .user:
            HStack {
                Spacer(minLength: 40)
                Text(message.text)
                    .font(.subheadline)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(FabricTheme.action)
                    .foregroundStyle(FabricTheme.textOnBrand)
                    .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
                    .accessibilityLabel("You")
                    .accessibilityValue(message.text)
            }
        case .assistant:
            HStack(alignment: .top) {
                AssistantMessageBody(message: message)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(FabricTheme.surfaceRaised)
                    .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
                Spacer(minLength: 40)
            }
        // Technical output (slash results, task notices): mono on an inset
        // surface, full width — a ledger row, not a speech bubble.
        case .info:
            Text(message.text)
                .font(.caption.monospaced())
                .foregroundStyle(FabricTheme.textMuted)
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(FabricTheme.surfaceInset)
                .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radius))
                .accessibilityLabel("Information")
                .accessibilityValue(message.text)
        // Failures read as status, not as chat: danger dot + left-aligned copy.
        case .system:
            HStack(spacing: 8) {
                Circle()
                    .fill(FabricTheme.danger)
                    .frame(width: 8, height: 8)
                Text(message.text)
                    .font(.caption)
                    .foregroundStyle(FabricTheme.danger)
                Spacer(minLength: 0)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Error")
            .accessibilityValue(message.text)
        }
    }
}

/// Rendering policy for assistant rows. A live row deliberately stays on the
/// cheap verbatim `Text` path for its entire stream. Only that row transitions
/// to rich presentation when `message.complete` flips `streaming` to false;
/// completed rows retain their cached document when later deltas arrive.
enum AssistantTranscriptPresentationMode: Equatable {
    case streamingPlain
    case rich

    static func mode(for message: TranscriptMessage) -> Self {
        message.streaming ? .streamingPlain : .rich
    }
}

struct AssistantTranscriptRenderInput: Equatable {
    let text: String
    let streaming: Bool
}

/// A small, deterministic Markdown block model. Foundation's native inline
/// Markdown parser handles emphasis and links; this layer owns only the block
/// structure SwiftUI `Text` does not present on its own (headings, lists,
/// fenced code, and unified diffs).
struct AssistantTranscriptDocument: Equatable {
    enum ListMarker: Equatable {
        case unordered
        case ordered(String)

        var displayText: String {
            switch self {
            case .unordered: return "•"
            case .ordered(let marker): return marker
            }
        }
    }

    enum Block: Equatable {
        case paragraph(String)
        case heading(level: Int, text: String)
        case listItem(marker: ListMarker, depth: Int, text: String)
        case code(language: String?, text: String)
        case diff(String)
    }

    let source: String
    let blocks: [Block]

    var containsTechnicalBlock: Bool {
        blocks.contains { block in
            switch block {
            case .code, .diff: return true
            default: return false
            }
        }
    }

    init(_ source: String) {
        self.source = source
        blocks = Self.parse(source)
    }

    private struct Fence {
        let marker: Character
        let count: Int
        let language: String?
    }

    private struct ParsedListItem {
        let marker: ListMarker
        let depth: Int
        let text: String
    }

    private static func parse(_ source: String) -> [Block] {
        guard !source.isEmpty else { return [.paragraph("")] }
        if looksLikeUnifiedDiff(source) { return [.diff(source)] }

        let lines = source.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        var result: [Block] = []
        var paragraph: [String] = []
        var index = 0

        func flushParagraph() {
            guard !paragraph.isEmpty else { return }
            result.append(.paragraph(paragraph.joined(separator: "\n")))
            paragraph.removeAll(keepingCapacity: true)
        }

        while index < lines.count {
            let line = lines[index]

            if let fence = openingFence(in: line) {
                var closingIndex: Int?
                var candidate = index + 1
                while candidate < lines.count {
                    if closesFence(lines[candidate], fence: fence) {
                        closingIndex = candidate
                        break
                    }
                    candidate += 1
                }

                guard let closingIndex else {
                    // An unfinished fence is prose, not a half-rendered code
                    // panel. Preserve every byte so malformed model output is
                    // still readable and copyable.
                    paragraph.append(contentsOf: lines[index...])
                    index = lines.count
                    break
                }

                flushParagraph()
                let code = lines[(index + 1)..<closingIndex].joined(separator: "\n")
                if isDiffLanguage(fence.language) || looksLikeUnifiedDiff(code) {
                    result.append(.diff(code))
                } else {
                    result.append(.code(language: fence.language, text: code))
                }
                index = closingIndex + 1
                continue
            }

            if line.trimmingCharacters(in: .whitespaces).isEmpty {
                flushParagraph()
                index += 1
                continue
            }

            if let heading = heading(in: line) {
                flushParagraph()
                result.append(.heading(level: heading.level, text: heading.text))
                index += 1
                continue
            }

            if let item = listItem(in: line) {
                flushParagraph()
                result.append(.listItem(marker: item.marker, depth: item.depth, text: item.text))
                index += 1
                continue
            }

            paragraph.append(line)
            index += 1
        }

        flushParagraph()
        return result.isEmpty ? [.paragraph(source)] : result
    }

    private static func openingFence(in line: String) -> Fence? {
        let characters = Array(line)
        var offset = 0
        while offset < characters.count, characters[offset] == " ", offset < 4 {
            offset += 1
        }
        guard offset <= 3, offset < characters.count else { return nil }
        let marker = characters[offset]
        guard marker == "`" || marker == "~" else { return nil }

        var end = offset
        while end < characters.count, characters[end] == marker { end += 1 }
        let count = end - offset
        guard count >= 3 else { return nil }

        let info = String(characters[end...]).trimmingCharacters(in: .whitespaces)
        if marker == "`", info.contains("`") { return nil }
        return Fence(marker: marker, count: count, language: normalizedLanguage(info))
    }

    private static func closesFence(_ line: String, fence: Fence) -> Bool {
        let characters = Array(line)
        var offset = 0
        while offset < characters.count, characters[offset] == " ", offset < 4 {
            offset += 1
        }
        guard offset <= 3, offset < characters.count, characters[offset] == fence.marker else {
            return false
        }

        var end = offset
        while end < characters.count, characters[end] == fence.marker { end += 1 }
        guard end - offset >= fence.count else { return false }
        return characters[end...].allSatisfy { $0.isWhitespace }
    }

    private static func normalizedLanguage(_ info: String) -> String? {
        guard var token = info.split(whereSeparator: { $0.isWhitespace }).first.map(String.init) else {
            return nil
        }
        if token.hasPrefix(".") { token.removeFirst() }
        let allowed = token.prefix(32).filter { character in
            character.isLetter || character.isNumber || "+#._-".contains(character)
        }
        return allowed.isEmpty ? nil : String(allowed).lowercased()
    }

    private static func heading(in line: String) -> (level: Int, text: String)? {
        let characters = Array(line)
        var offset = 0
        while offset < characters.count, characters[offset] == " ", offset < 4 {
            offset += 1
        }
        guard offset <= 3, offset < characters.count, characters[offset] == "#" else { return nil }

        var end = offset
        while end < characters.count, characters[end] == "#", end - offset < 7 { end += 1 }
        let level = end - offset
        guard (1...6).contains(level) else { return nil }
        guard end == characters.count || characters[end].isWhitespace else { return nil }
        return (level, String(characters[end...]).trimmingCharacters(in: .whitespaces))
    }

    private static func listItem(in line: String) -> ParsedListItem? {
        let characters = Array(line)
        var offset = 0
        while offset < characters.count, characters[offset] == " " { offset += 1 }
        guard offset < characters.count else { return nil }
        let depth = min(offset / 2, 4)

        if "-*+".contains(characters[offset]) {
            let contentStart = offset + 1
            guard contentStart < characters.count, characters[contentStart].isWhitespace else { return nil }
            let text = String(characters[(contentStart + 1)...])
            return ParsedListItem(marker: .unordered, depth: depth, text: text)
        }

        var digitEnd = offset
        while digitEnd < characters.count,
              characters[digitEnd].isNumber,
              digitEnd - offset < 9 {
            digitEnd += 1
        }
        guard digitEnd > offset, digitEnd < characters.count else { return nil }
        let terminator = characters[digitEnd]
        guard terminator == "." || terminator == ")" else { return nil }
        let contentStart = digitEnd + 1
        guard contentStart < characters.count, characters[contentStart].isWhitespace else { return nil }
        let marker = String(characters[offset...digitEnd])
        return ParsedListItem(
            marker: .ordered(marker),
            depth: depth,
            text: String(characters[(contentStart + 1)...])
        )
    }

    private static func isDiffLanguage(_ language: String?) -> Bool {
        guard let language else { return false }
        return ["diff", "patch", "udiff"].contains(language)
    }

    private static func looksLikeUnifiedDiff(_ source: String) -> Bool {
        let lines = source.split(separator: "\n", omittingEmptySubsequences: false)
        guard let firstContent = lines.first(where: {
            !$0.trimmingCharacters(in: .whitespaces).isEmpty
        }), firstContent.hasPrefix("diff --git ") || firstContent.hasPrefix("--- ") else {
            return false
        }
        var hasGitHeader = false
        var hasOldHeader = false
        var hasHeaderPair = false
        var hasHunk = false

        for line in lines {
            if line.hasPrefix("diff --git ") { hasGitHeader = true }
            if line.hasPrefix("--- ") { hasOldHeader = true }
            if hasOldHeader, line.hasPrefix("+++ ") { hasHeaderPair = true }
            if line.hasPrefix("@@ ") || line.hasPrefix("@@-") || line.hasPrefix("@@") {
                hasHunk = true
            }
        }
        return hasHunk && (hasGitHeader || hasHeaderPair)
    }
}

/// Neutralize raw HTML images without rewriting escaped or code-span examples.
/// Foundation then identifies active Markdown image runs structurally; those
/// URL attributes are removed before the value reaches SwiftUI.
enum AssistantMarkdownSafety {
    static func sanitizedInline(_ source: String) -> String {
        guard let rawImagePattern else { return source }
        let fullRange = NSRange(source.startIndex..<source.endIndex, in: source)
        let codeRanges = inlineCodeRanges(in: source)
        var output = ""
        var cursor = source.startIndex

        for match in rawImagePattern.matches(in: source, options: [], range: fullRange) {
            guard let range = Range(match.range, in: source),
                  !isEscaped(range.lowerBound, in: source),
                  !codeRanges.contains(where: { $0.contains(range.lowerBound) }) else {
                continue
            }
            output += source[cursor..<range.lowerBound]
            output += inertImageLabel(htmlAltText(in: source, range: range))
            cursor = range.upperBound
        }
        output += source[cursor...]
        return output
    }

    static func attributedString(from source: String) -> AttributedString {
        let safe = sanitizedInline(source)
        let options = AttributedString.MarkdownParsingOptions(
            interpretedSyntax: .inlineOnlyPreservingWhitespace,
            failurePolicy: .returnPartiallyParsedIfPossible
        )
        var attributed = (try? AttributedString(markdown: safe, options: options))
            ?? AttributedString(safe)
        // Parsing is local and does not fetch an image. Foundation marks only
        // active Markdown image nodes with `imageURL`; escaped syntax, code
        // spans, reference examples, and malformed nodes remain ordinary text.
        // Replace those marked runs before the value reaches SwiftUI so no
        // remote destination survives into presentation.
        let imageRanges = attributed.runs.compactMap { run in
            run.imageURL == nil ? nil : run.range
        }
        for range in imageRanges.reversed() {
            let rawAlt = String(attributed[range].characters)
                .replacingOccurrences(of: "\u{FFFC}", with: "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let label = rawAlt.isEmpty ? "Image" : "Image: \(rawAlt)"
            attributed.replaceSubrange(range, with: AttributedString(label))
        }
        // Assistant output is untrusted. In particular, Fabric pairing uses
        // an app URL scheme, so a model-authored link must never be able to
        // enter the app's deep-link router behind an innocuous label. Web
        // links stay explicit and user-initiated; every other scheme (and
        // every relative URL) is readable text without a link action.
        let inertLinkRanges = attributed.runs.compactMap { run -> Range<AttributedString.Index>? in
            guard let link = run.link else { return nil }
            let scheme = link.scheme?.lowercased()
            return scheme == "http" || scheme == "https" ? nil : run.range
        }
        for range in inertLinkRanges {
            attributed[range].link = nil
        }
        return attributed
    }

    private static let rawImagePattern = try? NSRegularExpression(
        pattern: #"<img(?=[\s/>])(?:[^>"']|"[^"]*"|'[^']*')*>"#,
        options: .caseInsensitive
    )

    private static let htmlAltPattern = try? NSRegularExpression(
        pattern: #"(?:^|[\s/])alt\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))"#,
        options: .caseInsensitive
    )

    private static func htmlAltText(
        in source: String,
        range: Range<String.Index>
    ) -> String? {
        guard let htmlAltPattern else { return nil }
        let attributes = String(source[range])
        let fullRange = NSRange(attributes.startIndex..<attributes.endIndex, in: attributes)
        guard let match = htmlAltPattern.firstMatch(
            in: attributes,
            options: [],
            range: fullRange
        ) else {
            return nil
        }
        for capture in 1..<match.numberOfRanges {
            let captureRange = match.range(at: capture)
            if captureRange.location != NSNotFound,
               let swiftRange = Range(captureRange, in: attributes) {
                return String(attributes[swiftRange])
            }
        }
        return ""
    }

    private static func codeSpan(
        startingAt start: String.Index,
        in source: String
    ) -> Range<String.Index>? {
        guard source[start] == "`", !isEscaped(start, in: source) else { return nil }
        let openingRun = backtickRun(startingAt: start, in: source)
        let openingCount = source.distance(from: openingRun.lowerBound, to: openingRun.upperBound)
        var cursor = openingRun.upperBound

        while cursor < source.endIndex {
            guard source[cursor] == "`" else {
                cursor = source.index(after: cursor)
                continue
            }
            let candidate = backtickRun(startingAt: cursor, in: source)
            let candidateCount = source.distance(from: candidate.lowerBound, to: candidate.upperBound)
            if candidateCount == openingCount {
                return start..<candidate.upperBound
            }
            cursor = candidate.upperBound
        }

        return nil
    }

    private static func inlineCodeRanges(in source: String) -> [Range<String.Index>] {
        var ranges: [Range<String.Index>] = []
        var cursor = source.startIndex
        while cursor < source.endIndex {
            if source[cursor] == "`",
               !isEscaped(cursor, in: source),
               let range = codeSpan(startingAt: cursor, in: source) {
                ranges.append(range)
                cursor = range.upperBound
            } else {
                cursor = source.index(after: cursor)
            }
        }
        return ranges
    }

    private static func backtickRun(
        startingAt start: String.Index,
        in source: String
    ) -> Range<String.Index> {
        var end = start
        while end < source.endIndex, source[end] == "`" {
            end = source.index(after: end)
        }
        return start..<end
    }

    private static func isEscaped(_ index: String.Index, in source: String) -> Bool {
        var slashCount = 0
        var cursor = index
        while cursor > source.startIndex {
            let previous = source.index(before: cursor)
            guard source[previous] == "\\" else { break }
            slashCount += 1
            cursor = previous
        }
        return slashCount.isMultiple(of: 2) == false
    }

    private static func inertImageLabel(_ altText: String?) -> String {
        guard let altText else { return "Image" }
        let trimmed = altText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "Image" }
        return "Image: \(markdownLiteral(trimmed))"
    }

    private static func markdownLiteral(_ source: String) -> String {
        var output = ""
        for character in source {
            if isASCIIPunctuation(character) { output.append("\\") }
            output.append(character)
        }
        return output
    }

    private static func isASCIIPunctuation(_ character: Character) -> Bool {
        guard let value = character.asciiValue else { return false }
        return (33...47).contains(value)
            || (58...64).contains(value)
            || (91...96).contains(value)
            || (123...126).contains(value)
    }
}

private struct AssistantMessageBody: View {
    let message: TranscriptMessage

    @State private var document: AssistantTranscriptDocument?

    private var renderInput: AssistantTranscriptRenderInput {
        AssistantTranscriptRenderInput(text: message.text, streaming: message.streaming)
    }

    var body: some View {
        Group {
            switch AssistantTranscriptPresentationMode.mode(for: message) {
            case .streamingPlain:
                Text(verbatim: message.text.isEmpty ? "…" : message.text)
                    .font(.subheadline)
                    .foregroundStyle(FabricTheme.text)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                    .accessibilityLabel("Fabric")
                    .accessibilityValue(message.text.isEmpty ? "Streaming response" : message.text)
            case .rich:
                if let document {
                    AssistantTranscriptView(document: document)
                        .frame(
                            maxWidth: document.containsTechnicalBlock ? .infinity : nil,
                            alignment: .leading
                        )
                        .accessibilityElement(children: .contain)
                        .accessibilityLabel("Fabric response")
                } else {
                    // A completed row is parsed once on appearance. This
                    // verbatim fallback prevents a blank flash and preserves
                    // malformed text while the state cache is populated.
                    Text(verbatim: message.text)
                        .font(.subheadline)
                        .foregroundStyle(FabricTheme.text)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                        .accessibilityLabel("Fabric")
                        .accessibilityValue(message.text)
                }
            }
        }
        .onAppear { cacheDocument(for: renderInput) }
        .onChange(of: renderInput) { _, newValue in
            cacheDocument(for: newValue)
        }
    }

    private func cacheDocument(for input: AssistantTranscriptRenderInput) {
        guard !input.streaming else {
            document = nil
            return
        }
        guard document?.source != input.text else { return }
        document = AssistantTranscriptDocument(input.text)
    }
}

private struct AssistantTranscriptView: View {
    let document: AssistantTranscriptDocument

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(document.blocks.indices, id: \.self) { index in
                blockView(document.blocks[index])
            }
        }
    }

    @ViewBuilder
    private func blockView(_ block: AssistantTranscriptDocument.Block) -> some View {
        switch block {
        case .paragraph(let markdown):
            SafeInlineMarkdownText(markdown: markdown, font: .subheadline)
        case .heading(let level, let markdown):
            SafeInlineMarkdownText(markdown: markdown, font: headingFont(level))
                .accessibilityAddTraits(.isHeader)
        case .listItem(let marker, let depth, let markdown):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(marker.displayText)
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(FabricTheme.textMuted)
                SafeInlineMarkdownText(markdown: markdown, font: .subheadline)
                    .layoutPriority(1)
            }
            .padding(.leading, CGFloat(depth) * 12)
        case .code(let language, let text):
            TechnicalTranscriptBlock(kind: .code(language: language), text: text)
        case .diff(let text):
            TechnicalTranscriptBlock(kind: .diff, text: text)
        }
    }

    private func headingFont(_ level: Int) -> Font {
        switch level {
        case 1: return .title3.weight(.semibold)
        case 2: return .headline.weight(.semibold)
        default: return .subheadline.weight(.semibold)
        }
    }
}

private struct SafeInlineMarkdownText: View {
    let markdown: String
    let font: Font

    var body: some View {
        Text(AssistantMarkdownSafety.attributedString(from: markdown))
            .font(font)
            .foregroundStyle(FabricTheme.text)
            .tint(FabricTheme.action)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)
    }
}

private struct TechnicalTranscriptBlock: View {
    enum Kind {
        case code(language: String?)
        case diff
    }

    let kind: Kind
    let text: String

    private var title: String {
        switch kind {
        case .code(let language):
            return language.map { "Code · \($0)" } ?? "Code"
        case .diff:
            return "Unified diff"
        }
    }

    private var isDiff: Bool {
        if case .diff = kind { return true }
        return false
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(FabricTheme.textMuted)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Button {
                    UIPasteboard.general.string = text
                } label: {
                    Image(systemName: "doc.on.doc")
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .buttonStyle(.plain)
                .foregroundStyle(FabricTheme.action)
                .accessibilityLabel("Copy \(title.lowercased())")
            }
            .padding(.leading, 12)
            .padding(.trailing, 2)

            Divider()

            ScrollView(.horizontal) {
                Text(verbatim: text.isEmpty ? " " : text)
                    .font(.caption.monospaced())
                    .foregroundStyle(FabricTheme.text)
                    .fixedSize(horizontal: true, vertical: true)
                    .padding(12)
                    .textSelection(.enabled)
            }
            .scrollIndicators(.visible)
            .accessibilityLabel(title)
            .accessibilityValue(text)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FabricTheme.surfaceInset)
        .overlay {
            RoundedRectangle(cornerRadius: FabricTheme.radius)
                .stroke(FabricTheme.border, lineWidth: 1)
        }
        .overlay(alignment: .leading) {
            if isDiff {
                Rectangle()
                    .fill(FabricTheme.thread)
                    .frame(width: 3)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radius))
        .accessibilityElement(children: .contain)
    }
}
