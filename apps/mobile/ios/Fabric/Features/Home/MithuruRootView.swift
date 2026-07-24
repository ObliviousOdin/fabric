import AVFoundation
import SwiftUI
import UniformTypeIdentifiers
import UIKit

/// Native, voice-first surface backed by the same gateway transport and approval
/// protocol as standard Fabric chat. It intentionally does not expose provider,
/// model, token, tool, or terminal controls.
struct MithuruRootView: View {
    @Environment(AppModel.self) private var appModel
    @State private var preferences = MithuruPreferences()
    @State private var mithuruStoredSessionId: String?

    var body: some View {
        Group {
            if !preferences.onboardingCompleted, preferences.simpleModeEnabled {
                MithuruOnboardingView(preferences: $preferences) {
                    preferences.onboardingCompleted = true
                    preferences.simpleModeEnabled = true
                    save()
                } onExit: {
                    preferences.simpleModeEnabled = false
                    save()
                }
            } else if preferences.simpleModeEnabled {
                let gatewayID = appModel.activeGatewayId
                MithuruConversationView(
                    preferences: $preferences,
                    resumeStoredSessionId: mithuruStoredSessionId,
                    onStoredSessionID: { sessionID in
                        MithuruPreferencesStore.saveStoredSessionID(
                            sessionID,
                            gatewayID: gatewayID
                        )
                        guard appModel.activeGatewayId == gatewayID else { return }
                        mithuruStoredSessionId = sessionID
                    }
                ) {
                    preferences.simpleModeEnabled = false
                    save()
                }
                .id(gatewayID ?? "default")
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
            mithuruStoredSessionId = MithuruPreferencesStore.loadStoredSessionID(
                gatewayID: appModel.activeGatewayId
            )
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
    let onExit: () -> Void
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
                Button(copy(.standardMode), action: onExit)
                    .font(.headline)
                    .frame(minHeight: FabricTheme.minTarget)
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
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Binding var preferences: MithuruPreferences
    let resumeStoredSessionId: String?
    let onStoredSessionID: (String?) -> Void
    let onExit: () -> Void

    @State private var model: ChatViewModel?
    @State private var voice = DeviceVoiceController()
    @State private var draft = ""
    @State private var dictationBase = ""
    @State private var showHelp = false
    @State private var showDocumentConsent = false
    @State private var showFileImporter = false
    @State private var showCloudSpeechConsent = false
    @State private var attachmentError: String?
    @State private var attachmentSequence = 0
    @AccessibilityFocusState private var focusedInteractionIdentity: String?

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
                    resumeStoredSessionId: resumeStoredSessionId,
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
                onStoredSessionID(next.storedSessionId)
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
        .onChange(of: model?.interactionAccessibilityCue, initial: true) { _, cue in
            guard let cue else {
                focusedInteractionIdentity = nil
                return
            }
            voice.stopAll()
            guard UIAccessibility.isVoiceOverRunning else { return }
            focusedInteractionIdentity = cue.identity
            UIAccessibility.post(notification: .announcement, argument: cue.announcement)
        }
        .onChange(of: preferences.cloudSpeechAllowed) { _, _ in
            voice.stopAll()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { voice.stopAll() }
        }
        .onDisappear {
            voice.stopAll()
            onStoredSessionID(model?.storedSessionId)
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
        .alert(copy(.cloudQuestion), isPresented: $showCloudSpeechConsent) {
            Button(copy(.allowOnlineSpeech)) {
                preferences.cloudSpeechAllowed = true
                persistPreferences()
            }
            Button(copy(.cancel), role: .cancel) {}
        } message: {
            Text(copy(.cloudExplanation))
        }
        .alert(item: voiceIssueBinding) { _ in
            Alert(
                title: Text(copy(.voiceIssueTitle)),
                message: Text(copy(.voiceIssueMessage)),
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
            if preferences.interactionMode == .voiceAndText {
                Button {
                    if preferences.cloudSpeechAllowed {
                        preferences.cloudSpeechAllowed = false
                        voice.stopAll()
                        persistPreferences()
                    } else {
                        showCloudSpeechConsent = true
                    }
                } label: {
                    Image(systemName: preferences.cloudSpeechAllowed ? "shield.checkered" : "shield")
                        .frame(width: FabricTheme.minTarget, height: FabricTheme.minTarget)
                }
                .accessibilityLabel(
                    preferences.cloudSpeechAllowed ? copy(.disableOnlineSpeech) : copy(.allowOnlineSpeech)
                )
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
            if dynamicTypeSize.isAccessibilitySize {
                transcript(model)
                    .frame(minHeight: 160, maxHeight: 280)
                ScrollView {
                    VStack(spacing: 0) {
                        blockingInteraction(model)
                        composer(model)
                    }
                }
            } else {
                transcript(model)
                blockingInteraction(model)
                composer(model)
            }
        }
    }

    @ViewBuilder
    private func blockingInteraction(_ model: ChatViewModel) -> some View {
        if let approval = model.pendingApproval {
            confirmation(approval, model: model)
        } else if let prompt = model.pendingPrompt {
            promptCard(prompt, model: model)
        }
    }

    private func status(_ model: ChatViewModel) -> some View {
        let status: (String, String) = {
            if model.pendingApproval != nil { return (copy(.needsConfirmation), "exclamationmark.shield") }
            if model.sessionError != nil || model.unknownSendOutcome != nil {
                return (copy(.connectionError), "exclamationmark.triangle")
            }
            if voice.isListening { return (copy(.listening), "waveform") }
            if voice.isSpeaking { return (copy(.speaking), "speaker.wave.2") }
            if appModel.phase != .connected { return (copy(.offline), "wifi.slash") }
            if model.busy || !model.sessionReady { return (copy(.processing), "ellipsis") }
            return (copy(.ready), "checkmark.circle")
        }()
        return Label(status.0, systemImage: status.1)
            .font(.headline)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal)
            .padding(.vertical, 10)
            .background(FabricTheme.surfaceInset)
            .accessibilityLabel(copy(.statusAccessibility))
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
                            MithuruTranscriptRow(
                                message: message,
                                fallbackError: copy(.connectionError),
                                userLabel: copy(.you),
                                assistantLabel: copy(.brand)
                            )
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
        .accessibilityLabel(copy(.conversationAccessibility))
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
            .disabled(model.approvalResponseState.isSubmitting)
        }
        .padding()
        .background(FabricTheme.warning.fabricTint())
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("mithuru-confirmation")
        .accessibilityFocused(
            $focusedInteractionIdentity,
            equals: PendingInteraction.approval(approval).identity
        )
    }

    private func promptCard(_ prompt: PendingPrompt, model: ChatViewModel) -> some View {
        MithuruPromptCard(
            prompt: prompt,
            fieldLabel: copy(.typeRequest),
            sendLabel: copy(.send),
            cancelLabel: copy(.cancel),
            submitting: model.promptResponseSubmitting
        ) { response in
            Task { await model.respondToPrompt(response) }
        }
        .id(PendingInteraction.prompt(prompt).identity)
        .accessibilityFocused(
            $focusedInteractionIdentity,
            equals: PendingInteraction.prompt(prompt).identity
        )
    }

    private func composer(_ model: ChatViewModel) -> some View {
        VStack(spacing: 12) {
            TextField(copy(.typeRequest), text: $draft, axis: .vertical)
                .lineLimit(2...5)
                .textFieldStyle(.roundedBorder)
                .font(.title3)
                .frame(minHeight: 54)
                .accessibilityLabel(copy(.editTranscript))
                .disabled(
                    !model.sessionReady
                        || model.unknownSendOutcome != nil
                        || voice.dictationState.locksDraft
                        || !appModel.supportsGatewayMethod("prompt.submit")
                )
            if !model.pendingAttachments.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text(copy(.documentsToSend))
                        .font(.headline)
                    ForEach(model.pendingAttachments) { attachment in
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Image(systemName: attachment.kind == .image ? "photo" : "doc")
                            Text(attachment.filename)
                                .lineLimit(2)
                                .truncationMode(.middle)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Button(role: .destructive) {
                                model.removeAttachment(id: attachment.id)
                            } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .frame(width: FabricTheme.minTarget, height: FabricTheme.minTarget)
                            }
                            .accessibilityLabel("\(copy(.removeDocument)): \(attachment.filename)")
                            .disabled(model.isUploadingAttachments)
                        }
                    }
                }
                .padding(10)
                .background(FabricTheme.surfaceInset)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            if let attachmentError {
                Text(attachmentError)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.danger)
                    .accessibilityIdentifier("mithuru-attachment-error")
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
                    .disabled(
                        model.busy
                            || !model.sessionReady
                            || model.unknownSendOutcome != nil
                            || !appModel.supportsGatewayMethod("prompt.submit")
                    )
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
                        || !model.sessionReady
                        || appModel.phase != .connected
                        || model.unknownSendOutcome != nil
                        || model.isUploadingAttachments
                        || voice.dictationState.locksDraft
                        || !appModel.supportsGatewayMethod("prompt.submit")
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
                    attachmentError = nil
                    showDocumentConsent = true
                } label: {
                    Label(copy(.explainLetter), systemImage: "doc.text.viewfinder")
                        .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                }
                .buttonStyle(.bordered)
                .disabled(
                    !model.sessionReady
                        || model.unknownSendOutcome != nil
                        || model.isUploadingAttachments
                        || !model.supportsAttachments
                )
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
        .accessibilityLabel(copy(.suggestionsAccessibility))
    }

    private func suggestion(_ label: String, prompt: String) -> some View {
        Button(label) { draft = prompt }
            .buttonStyle(.bordered)
            .frame(minHeight: FabricTheme.minTarget)
    }

    private func send(_ model: ChatViewModel) {
        guard !voice.dictationState.locksDraft else { return }
        let text = draft
        voice.stopDictation()
        Task {
            guard await model.sendPlainPrompt(text) else { return }
            draft = ""
            dictationBase = ""
            attachmentError = nil
        }
    }

    private func importDocument(_ result: Result<[URL], Error>) {
        guard model?.supportsAttachments == true else {
            attachmentError = copy(.connectionError)
            return
        }
        guard case .success(let urls) = result, let url = urls.first else {
            if case .failure = result { attachmentError = copy(.connectionError) }
            return
        }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        guard let reportedSize = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize,
              reportedSize <= ChatAttachmentPolicy.maximumAttachmentBytes,
              let data = try? Data(contentsOf: url, options: .mappedIfSafe),
              !data.isEmpty else {
            attachmentError = copy(.connectionError)
            return
        }
        attachmentError = nil
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

struct MithuruPromptAnswerState: Equatable {
    private(set) var identity: String?
    var answer = ""

    mutating func reset(for nextIdentity: String) {
        guard identity != nextIdentity else { return }
        identity = nextIdentity
        answer = ""
    }

    mutating func consume(_ response: String) -> String {
        answer = ""
        return response
    }
}

private struct MithuruPromptCard: View {
    let prompt: PendingPrompt
    let fieldLabel: String
    let sendLabel: String
    let cancelLabel: String
    let submitting: Bool
    let onRespond: (String) -> Void

    @State private var draft = MithuruPromptAnswerState()

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(prompt.presentationQuestion)
                .font(.headline)
            if prompt.isSecureEntry {
                SecureField(fieldLabel, text: $draft.answer)
                    .textFieldStyle(.roundedBorder)
                    .textContentType(.password)
                    .privacySensitive()
            } else {
                TextField(fieldLabel, text: $draft.answer, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...4)
                ForEach(prompt.presentationChoices) { choice in
                    Button(choice.label) { submit(choice.response) }
                        .buttonStyle(.bordered)
                        .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                }
            }
            HStack {
                Button(sendLabel) { submit(draft.answer) }
                    .buttonStyle(.borderedProminent)
                    .disabled(draft.answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button(cancelLabel, role: .cancel) { submit("") }
                    .buttonStyle(.bordered)
            }
        }
        .disabled(submitting)
        .padding()
        .background(FabricTheme.surfaceRaised)
        .onChange(of: PendingInteraction.prompt(prompt).identity, initial: true) { _, identity in
            draft.reset(for: identity)
        }
    }

    private func submit(_ response: String) {
        onRespond(draft.consume(response))
    }
}

private struct MithuruTranscriptRow: View {
    let message: TranscriptMessage
    let fallbackError: String
    let userLabel: String
    let assistantLabel: String

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 34) }
            Text(presentedText)
                .font(.body)
                .textSelection(.enabled)
                .padding(14)
                .background(background)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            if message.role != .user { Spacer(minLength: 34) }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(message.role == .user ? userLabel : assistantLabel)
        .accessibilityValue(presentedText)
    }

    private var presentedText: String {
        message.role == .system ? fallbackError : message.text
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
            } onExit: {
                completed = true
            }
        }
    }
}
#endif
