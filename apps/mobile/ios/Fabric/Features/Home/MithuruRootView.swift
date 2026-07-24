import AVFoundation
import SwiftUI
import UniformTypeIdentifiers

/// Native, voice-first surface backed by the same gateway session and approval
/// protocol as standard Fabric chat. It intentionally does not expose provider,
/// model, token, tool, or terminal controls.
struct MithuruRootView: View {
    @Environment(AppModel.self) private var appModel
    @State private var preferences = MithuruPreferences()
    @State private var loadedScope: String?

    var body: some View {
        Group {
            if !preferences.onboardingCompleted {
                MithuruOnboardingView(preferences: $preferences) {
                    preferences.onboardingCompleted = true
                    preferences.simpleModeEnabled = true
                    save()
                }
            } else if preferences.simpleModeEnabled {
                MithuruConversationView(preferences: $preferences) {
                    preferences.simpleModeEnabled = false
                    save()
                }
            } else {
                VStack(spacing: 0) {
                    HStack {
                        Spacer()
                        Button {
                            preferences.simpleModeEnabled = true
                            save()
                        } label: {
                            Label(copy(.openMithuru), systemImage: "person.wave.2")
                                .font(.headline)
                                .frame(minHeight: FabricTheme.minTarget)
                        }
                        .buttonStyle(.borderedProminent)
                        .padding(.horizontal)
                        .padding(.top, 8)
                    }
                    ConversationHomeView()
                }
            }
        }
        .dynamicTypeSize(preferences.textScale.dynamicTypeSize...)
        .task(id: appModel.activeGatewayId) {
            guard loadedScope != appModel.activeGatewayId else { return }
            loadedScope = appModel.activeGatewayId
            preferences = MithuruPreferencesStore.load(gatewayID: appModel.activeGatewayId)
        }
    }

    private func copy(_ key: MithuruCopyKey) -> String {
        MithuruCopy.text(key, locale: preferences.locale)
    }

    private func save() {
        MithuruPreferencesStore.save(preferences, gatewayID: appModel.activeGatewayId)
    }
}

private struct MithuruOnboardingView: View {
    @Binding var preferences: MithuruPreferences
    let onComplete: () -> Void
    @State private var step = 0

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text(copy(.welcome))
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(FabricTheme.textMuted)
                Text(title)
                    .font(.largeTitle.bold())
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)
                if step == 4 {
                    Text(copy(.familyPrivacy))
                        .font(.body)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if step == 5 {
                    Text(copy(.cloudExplanation))
                        .font(.body)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                VStack(spacing: 14) {
                    ForEach(options, id: \.label) { option in
                        Button(option.label) {
                            apply(option)
                        }
                        .buttonStyle(.bordered)
                        .foregroundStyle(FabricTheme.text)
                        .font(.title3.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
                        .accessibilityIdentifier("mithuru-onboarding-option-\(option.id)")
                    }
                }
                if step > 0 {
                    Button(copy(.back)) {
                        step = step == 4 && preferences.interactionMode == .textOnly ? 2 : step - 1
                    }
                        .font(.headline)
                        .frame(minHeight: FabricTheme.minTarget)
                }
            }
            .frame(maxWidth: 680, alignment: .leading)
            .padding(24)
        }
        .background(FabricTheme.canvas.ignoresSafeArea())
        .accessibilityIdentifier("mithuru-onboarding")
    }

    private var title: String {
        switch step {
        case 0: return copy(.languageQuestion)
        case 1: return copy(.interactionQuestion)
        case 2: return copy(.textSizeQuestion)
        case 3: return copy(.speechRateQuestion)
        case 4: return copy(.familyQuestion)
        default: return copy(.cloudQuestion)
        }
    }

    private struct Option {
        let id: String
        let label: String
        let apply: (inout MithuruPreferences) -> Void
    }

    private var options: [Option] {
        switch step {
        case 0:
            return MithuruLocale.allCases.map { locale in
                Option(id: locale.rawValue, label: locale.displayName) { $0.locale = locale }
            }
        case 1:
            return [
                Option(id: "voice-and-text", label: copy(.voiceAndText)) { $0.interactionMode = .voiceAndText },
                Option(id: "text-only", label: copy(.textOnly)) { $0.interactionMode = .textOnly },
            ]
        case 2:
            return [
                Option(id: "large", label: copy(.large)) { $0.textScale = .large },
                Option(id: "extra-large", label: copy(.extraLarge)) { $0.textScale = .extraLarge },
                Option(id: "maximum", label: copy(.maximum)) { $0.textScale = .maximum },
            ]
        case 3:
            return [
                Option(id: "slow", label: copy(.slow)) { $0.speechRate = 0.7 },
                Option(id: "normal", label: copy(.normal)) { $0.speechRate = 1.0 },
            ]
        case 4:
            return [
                Option(id: "family-yes", label: copy(.yes)) { $0.caregiverConfigured = true },
                Option(id: "family-no", label: copy(.no)) { $0.caregiverConfigured = false },
            ]
        default:
            return [
                Option(id: "cloud-yes", label: copy(.yes)) { $0.cloudSpeechAllowed = true },
                Option(id: "cloud-no", label: copy(.no)) { $0.cloudSpeechAllowed = false },
            ]
        }
    }

    private func apply(_ option: Option) {
        option.apply(&preferences)
        if step == 5 {
            onComplete()
        } else if step == 4, preferences.interactionMode == .textOnly {
            preferences.cloudSpeechAllowed = false
            onComplete()
        } else if step == 2, preferences.interactionMode == .textOnly {
            step = 4
        } else {
            step += 1
        }
    }

    private func copy(_ key: MithuruCopyKey) -> String {
        MithuruCopy.text(key, locale: preferences.locale)
    }
}

private struct MithuruConversationView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.scenePhase) private var scenePhase
    @Binding var preferences: MithuruPreferences
    let onExit: () -> Void

    @State private var model: ChatViewModel?
    @State private var voice = DeviceVoiceController()
    @State private var draft = ""
    @State private var dictationBase = ""
    @State private var showHelp = false
    @State private var showDocumentConsent = false
    @State private var showFileImporter = false
    @State private var attachmentSequence = 0
    @State private var promptAnswer = ""

    var body: some View {
        VStack(spacing: 0) {
            header
            if let model {
                content(model)
            } else {
                ProgressView(copy(.processing))
                    .font(.title3)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(FabricTheme.canvas.ignoresSafeArea())
        .task(id: appModel.connectionGeneration) {
            if model == nil {
                let next = ChatViewModel(
                    api: appModel.api,
                    resumeStoredSessionId: nil,
                    supportsMethod: { appModel.supportsGatewayMethod($0) },
                    durableWorkNegotiation: { appModel.capabilityNegotiation },
                    workGatewayID: { appModel.activeGatewayId },
                    onWorkIdentity: { runtimeSessionID, identity in
                        appModel.publishWorkContext(
                            runtimeSessionID: runtimeSessionID,
                            workIdentity: identity
                        )
                    }
                )
                model = next
                await next.start()
            } else if appModel.phase == .connected {
                await model?.resumeAfterReconnect()
            }
        }
        .onChange(of: voice.transcript) { _, transcript in
            draft = VoiceDraftComposer.merging(baseDraft: dictationBase, transcript: transcript)
        }
        .onChange(of: appModel.phase) { oldPhase, newPhase in
            if oldPhase == .connected, newPhase != .connected {
                model?.connectionDidClose()
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active, voice.isListening { voice.stopDictation() }
        }
        .onDisappear {
            voice.stopDictation()
            voice.stopSpeaking()
            model?.stop()
        }
        .alert(copy(.help), isPresented: $showHelp) {
            Button(copy(.yes), role: .cancel) {}
        } message: {
            Text(copy(.helpBody))
        }
        .alert(copy(.confirmTitle), isPresented: $showDocumentConsent) {
            Button(copy(.chooseDocument)) { showFileImporter = true }
            Button(copy(.cancel), role: .cancel) {}
        } message: {
            Text(copy(.documentConsent))
        }
        .alert(item: voiceIssueBinding) { issue in
            Alert(
                title: Text(issue.title),
                message: Text(issue.message),
                dismissButton: .default(Text(copy(.yes))) { voice.clearIssue() }
            )
        }
        .fileImporter(
            isPresented: $showFileImporter,
            allowedContentTypes: [.image, .pdf, .plainText],
            allowsMultipleSelection: false,
            onCompletion: importDocument
        )
        .accessibilityIdentifier("mithuru-home")
    }

    private var header: some View {
        HStack(spacing: 10) {
            Text(copy(.brand))
                .font(.title.bold())
            Spacer()
            Menu {
                ForEach(MithuruLocale.allCases) { locale in
                    Button(locale.displayName) {
                        preferences.locale = locale
                        persistPreferences()
                    }
                }
            } label: {
                Label(preferences.locale.displayName, systemImage: "globe")
                    .frame(minHeight: FabricTheme.minTarget)
            }
            Button { showHelp = true } label: {
                Image(systemName: "questionmark.circle")
                    .frame(width: FabricTheme.minTarget, height: FabricTheme.minTarget)
            }
            .accessibilityLabel(copy(.help))
            Button(copy(.standardMode), action: onExit)
                .font(.headline)
                .frame(minHeight: FabricTheme.minTarget)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(FabricTheme.surfaceRaised)
        .overlay(alignment: .bottom) { Divider() }
    }

    @ViewBuilder
    private func content(_ model: ChatViewModel) -> some View {
        VStack(spacing: 0) {
            status(model)
            transcript(model)
            if let approval = model.pendingApproval {
                confirmation(approval, model: model)
            } else if let prompt = model.pendingPrompt {
                promptCard(prompt, model: model)
            }
            composer(model)
        }
    }

    private func status(_ model: ChatViewModel) -> some View {
        let status: (String, String) = {
            if model.pendingApproval != nil { return (copy(.needsConfirmation), "exclamationmark.shield") }
            if voice.isListening { return (copy(.listening), "waveform") }
            if voice.isSpeaking { return (copy(.speaking), "speaker.wave.2") }
            if model.busy { return (copy(.processing), "ellipsis") }
            if appModel.phase != .connected { return (copy(.offline), "wifi.slash") }
            return (copy(.ready), "checkmark.circle")
        }()
        return Label(status.0, systemImage: status.1)
            .font(.headline)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal)
            .padding(.vertical, 10)
            .background(FabricTheme.surfaceInset)
            .accessibilityLabel("Mithuru status")
            .accessibilityValue(status.0)
    }

    private func transcript(_ model: ChatViewModel) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    if model.messages.isEmpty {
                        Text(copy(.greeting))
                            .font(.title2.weight(.semibold))
                            .foregroundStyle(FabricTheme.textMuted)
                            .frame(maxWidth: .infinity, minHeight: 140)
                    }
                    ForEach(model.messages) { message in
                        if !message.text.isEmpty {
                            MithuruTranscriptRow(message: message, fallbackError: copy(.connectionError))
                                .id(message.id)
                        }
                    }
                }
                .padding()
            }
            .onChange(of: model.messages.count) { _, _ in
                if let id = model.messages.last?.id {
                    withAnimation { proxy.scrollTo(id, anchor: .bottom) }
                }
            }
        }
        .frame(maxHeight: .infinity)
        .accessibilityLabel("Mithuru conversation")
    }

    private func confirmation(_ approval: PendingApproval, model: ChatViewModel) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(copy(.confirmTitle), systemImage: "exclamationmark.shield.fill")
                .font(.title2.bold())
            if let summary = approval.summary {
                Text(summary)
                    .font(.body)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let command = approval.command {
                Text(command)
                    .font(.body.monospaced())
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let cwd = approval.cwd {
                Label(cwd, systemImage: "folder")
                    .font(.footnote)
                    .textSelection(.enabled)
            }
            if approval.summary == nil, approval.command == nil {
                Text(copy(.needsConfirmation))
            }
            HStack {
                Button(copy(.allowOnce)) {
                    Task { await model.respondToApproval(choice: .once) }
                }
                .buttonStyle(.borderedProminent)
                .frame(maxWidth: .infinity, minHeight: 52)
                Button(copy(.deny), role: .destructive) {
                    Task { await model.respondToApproval(choice: .deny) }
                }
                .buttonStyle(.bordered)
                .frame(maxWidth: .infinity, minHeight: 52)
            }
        }
        .padding()
        .background(FabricTheme.warning.fabricTint())
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("mithuru-confirmation")
    }

    private func promptCard(_ prompt: PendingPrompt, model: ChatViewModel) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(prompt.presentationQuestion)
                .font(.headline)
            if prompt.isSecureEntry {
                SecureField(copy(.typeRequest), text: $promptAnswer)
                    .textFieldStyle(.roundedBorder)
                    .textContentType(.password)
                    .privacySensitive()
            } else {
                TextField(copy(.typeRequest), text: $promptAnswer, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...4)
                ForEach(prompt.presentationChoices) { choice in
                    Button(choice.label) {
                        promptAnswer = ""
                        Task { await model.respondToPrompt(choice.response) }
                    }
                    .buttonStyle(.bordered)
                    .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                }
            }
            HStack {
                Button(copy(.send)) {
                    let answer = promptAnswer
                    promptAnswer = ""
                    Task { await model.respondToPrompt(answer) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(promptAnswer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button(copy(.cancel), role: .cancel) {
                    Task { await model.respondToPrompt("") }
                }
                .buttonStyle(.bordered)
            }
        }
        .padding()
        .background(FabricTheme.surfaceRaised)
    }

    private func composer(_ model: ChatViewModel) -> some View {
        VStack(spacing: 12) {
            TextField(copy(.typeRequest), text: $draft, axis: .vertical)
                .lineLimit(2...5)
                .textFieldStyle(.roundedBorder)
                .font(.title3)
                .frame(minHeight: 54)
                .accessibilityLabel(copy(.editTranscript))
            if !model.pendingAttachments.isEmpty {
                Text("\(model.pendingAttachments.count) \(copy(.chooseDocument))")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
            }
            HStack(spacing: 12) {
                if preferences.interactionMode == .voiceAndText {
                    Button {
                        if voice.dictationState == .idle { dictationBase = draft }
                        Task {
                            await voice.toggleDictation(
                                locale: preferences.locale.locale,
                                allowCloudFallback: preferences.cloudSpeechAllowed
                            )
                        }
                    } label: {
                        Label(
                            voice.isListening ? copy(.stopListening) : copy(.talk),
                            systemImage: voice.isListening ? "stop.fill" : "mic.fill"
                        )
                        .font(.title3.bold())
                        .frame(maxWidth: .infinity, minHeight: 56)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.busy)
                }
                Button {
                    send(model)
                } label: {
                    Label(copy(.send), systemImage: "arrow.up.circle.fill")
                        .font(.title3.bold())
                        .frame(maxWidth: .infinity, minHeight: 56)
                }
                .buttonStyle(.bordered)
                .disabled(
                    (draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        && model.pendingAttachments.isEmpty)
                        || model.busy
                        || appModel.phase != .connected
                )
            }
            HStack(spacing: 12) {
                if preferences.interactionMode == .voiceAndText {
                    Button {
                        if let message = model.messages.last(where: { $0.role == .assistant && !$0.text.isEmpty }) {
                            voice.toggleReadAloud(
                                messageID: message.id,
                                text: message.text,
                                locale: preferences.locale.locale,
                                rate: Float(preferences.speechRate) * AVSpeechUtteranceDefaultSpeechRate
                            )
                        }
                    } label: {
                        Label(copy(.repeatAnswer), systemImage: "speaker.wave.2")
                            .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                    }
                    .buttonStyle(.bordered)
                }
                Button {
                    showDocumentConsent = true
                } label: {
                    Label(copy(.explainLetter), systemImage: "doc.text.viewfinder")
                        .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                }
                .buttonStyle(.bordered)
            }
            suggestedActions
            if preferences.interactionMode == .voiceAndText {
                Text(preferences.cloudSpeechAllowed ? copy(.privacyCloud) : copy(.privacyLocal))
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
            }
        }
        .padding()
        .background(FabricTheme.surfaceRaised)
        .overlay(alignment: .top) { Divider() }
        .disabled(model.pendingApproval != nil || model.pendingPrompt != nil)
    }

    private var suggestedActions: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                suggestion(copy(.readMessages), prompt: copy(.readMessages))
                suggestion(copy(.messageFamily), prompt: copy(.messageFamily))
                suggestion(copy(.setReminder), prompt: copy(.setReminder))
                suggestion(copy(.appointments), prompt: copy(.appointments))
            }
        }
        .accessibilityLabel("Suggested actions")
    }

    private func suggestion(_ label: String, prompt: String) -> some View {
        Button(label) { draft = prompt }
            .buttonStyle(.bordered)
            .frame(minHeight: FabricTheme.minTarget)
    }

    private func send(_ model: ChatViewModel) {
        let text = draft
        draft = ""
        dictationBase = ""
        voice.stopDictation()
        Task { await model.send(text) }
    }

    private func importDocument(_ result: Result<[URL], Error>) {
        guard case .success(let urls) = result, let url = urls.first else { return }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        guard let reportedSize = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize,
              reportedSize <= ChatAttachmentPolicy.maximumAttachmentBytes,
              let data = try? Data(contentsOf: url, options: .mappedIfSafe),
              !data.isEmpty else { return }
        attachmentSequence += 1
        model?.stageAttachment(ChatAttachmentPolicy.attachment(
            data: data,
            suggestedName: url.lastPathComponent,
            sequence: attachmentSequence
        ))
        if draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            draft = copy(.explainLetter)
        }
    }

    private func copy(_ key: MithuruCopyKey) -> String {
        MithuruCopy.text(key, locale: preferences.locale)
    }

    private func persistPreferences() {
        MithuruPreferencesStore.save(preferences, gatewayID: appModel.activeGatewayId)
    }

    private var voiceIssueBinding: Binding<DeviceVoiceIssue?> {
        Binding(
            get: { voice.issue },
            set: { issue in
                if issue == nil { voice.clearIssue() }
            }
        )
    }
}

private struct MithuruTranscriptRow: View {
    let message: TranscriptMessage
    let fallbackError: String

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 34) }
            Text(message.role == .system ? fallbackError : message.text)
                .font(.body)
                .textSelection(.enabled)
                .padding(14)
                .background(background)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            if message.role != .user { Spacer(minLength: 34) }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(message.role == .user ? "You" : "Mithuru")
    }

    private var background: Color {
        switch message.role {
        case .user: return FabricTheme.surfaceBrand
        case .system: return FabricTheme.danger.fabricTint()
        case .assistant, .info: return FabricTheme.surfaceRaised
        }
    }
}

#if DEBUG
struct MithuruOnboardingDebugFixtureView: View {
    @State private var preferences = MithuruPreferences()
    @State private var completed = false

    var body: some View {
        if completed {
            Text("Mithuru setup complete")
                .accessibilityIdentifier("mithuru-onboarding-complete")
        } else {
            MithuruOnboardingView(preferences: $preferences) {
                completed = true
            }
        }
    }
}
#endif
