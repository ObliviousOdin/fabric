import ImageIO
import PhotosUI
import QuickLook
import SwiftUI
import UIKit
import UniformTypeIdentifiers

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
    @State private var showRenamePrompt = false
    @State private var renameDraft = ""

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
                    liveViewCaptureCapability: LiveViewCaptureCapability(
                        negotiation: appModel.capabilityNegotiation
                    ),
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
        .navigationTitle(model?.sessionTitle ?? title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let model, model.canRenameSession {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        renameDraft = model.sessionTitle
                            ?? (title == "New chat" ? "" : title)
                        showRenamePrompt = true
                    } label: {
                        Image(systemName: "pencil")
                            .frame(
                                minWidth: FabricTheme.minTarget,
                                minHeight: FabricTheme.minTarget
                            )
                    }
                    .accessibilityLabel("Rename conversation")
                    .accessibilityHint("Sets the name shown for this conversation on every device")
                }
            }
        }
        .alert("Rename conversation", isPresented: $showRenamePrompt) {
            TextField("Conversation name", text: $renameDraft)
            Button("Save") {
                let model = model
                let newTitle = renameDraft
                Task { await model?.renameSession(to: newTitle) }
            }
            .disabled(renameDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The name is saved on the Fabric gateway, so it appears in every session list.")
        }
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
        .toolbar(.hidden, for: .tabBar)
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
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(AppModel.self) private var appModel

    @Bindable var model: ChatViewModel
    @Binding var draft: String
    let liveViewCaptureCapability: LiveViewCaptureCapability
    let recoveryAction: SessionRecoveryAction
    let onRetrySession: () -> Void
    let onReturnToConversations: () -> Void

    @State private var showCommandCatalog = false
    @State private var showProcesses = false
    @State private var showLiveView = false
    @State private var showUsageDetail = false
    @State private var promptAnswer = ""
    @State private var liveViewModel: LiveViewModel
    @State private var showPhotoPicker = false
    @State private var showFileImporter = false
    @State private var photoSelection: [PhotosPickerItem] = []
    @State private var attachmentSequence = 0
    @AccessibilityFocusState private var focusedInteractionIdentity: String?

    init(
        model: ChatViewModel,
        draft: Binding<String>,
        liveViewCaptureCapability: LiveViewCaptureCapability,
        recoveryAction: SessionRecoveryAction,
        onRetrySession: @escaping () -> Void,
        onReturnToConversations: @escaping () -> Void
    ) {
        _model = Bindable(wrappedValue: model)
        _draft = draft
        self.liveViewCaptureCapability = liveViewCaptureCapability
        self.recoveryAction = recoveryAction
        self.onRetrySession = onRetrySession
        self.onReturnToConversations = onReturnToConversations
        _liveViewModel = State(initialValue: LiveViewModel(
            captureCapability: liveViewCaptureCapability,
            connectionReady: model.sessionReady,
            capture: { try await model.api.captureScreen() }
        ))
    }

    var body: some View {
        VStack(spacing: 0) {
            if model.showingCachedTranscript {
                Label(
                    model.sessionError == nil
                        ? "Saved preview — checking the gateway for current history"
                        : "Saved preview — gateway unavailable",
                    systemImage: model.sessionError == nil
                        ? "clock.arrow.circlepath"
                        : "wifi.exclamationmark"
                )
                .font(.footnote)
                .foregroundStyle(FabricTheme.textMuted)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal)
                .padding(.vertical, 8)
                .background(FabricTheme.surfaceInset)
                .accessibilityLabel("Saved conversation preview")
                .accessibilityValue(
                    model.sessionError == nil
                        ? "Checking the gateway for current history"
                        : "Read only until the conversation reconnects"
                )
            }
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
                if model.hasReadOnlyCachedTranscriptAfterResumeFailure {
                    transcript
                    CachedTranscriptRecoveryBanner(
                        message: sessionError,
                        onRetry: onRetrySession
                    )
                } else {
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
                }
            } else if !model.sessionReady && model.messages.isEmpty {
                // Opening an old conversation previously showed an empty
                // transcript with a disabled composer and no explanation
                // while `session.resume` was in flight.
                VStack(spacing: 10) {
                    Spacer()
                    ProgressView()
                    Text("Opening conversation…")
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.textMuted)
                    Spacer()
                }
                .frame(maxWidth: .infinity)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Opening conversation")
            } else {
                transcript
            }

            controlDock
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
            LiveViewSheet(model: liveViewModel)
        }
        .sheet(isPresented: $showUsageDetail) {
            if let usage = model.usage {
                SessionUsageDetailSheet(usage: usage)
            }
        }
        .toolbar {
            if let usage = model.usage {
                ToolbarItem(placement: .topBarTrailing) {
                    SessionUsageChip(usage: usage) {
                        showUsageDetail = true
                    }
                }
            }
        }
        .onChange(of: liveViewCaptureCapability, initial: true) { _, capability in
            liveViewModel.setCaptureCapability(capability)
        }
        .onChange(of: model.sessionReady, initial: true) { _, ready in
            liveViewModel.setConnectionReady(ready)
        }
        .onChange(of: model.interactionAccessibilityCue, initial: true) { _, cue in
            guard let cue else {
                focusedInteractionIdentity = nil
                return
            }
            guard UIAccessibility.isVoiceOverRunning else { return }
            focusedInteractionIdentity = cue.identity
            UIAccessibility.post(notification: .announcement, argument: cue.announcement)
        }
        .photosPicker(
            isPresented: $showPhotoPicker,
            selection: $photoSelection,
            maxSelectionCount: ChatAttachmentPolicy.maximumStagedAttachments,
            matching: .images
        )
        .onChange(of: photoSelection) { _, items in
            guard !items.isEmpty else { return }
            photoSelection = []
            Task { await ingestPhotoPickerItems(items) }
        }
        .fileImporter(
            isPresented: $showFileImporter,
            allowedContentTypes: [.item],
            allowsMultipleSelection: true
        ) { result in
            ingestFileImporterResult(result)
        }
        .onDisappear {
            liveViewModel.disappear()
            // Reap Quick Look temp files, including any orphaned by an app
            // kill mid-preview in an earlier session of this surface.
            AttachmentPreviewStore.removeAllTemporaryFiles()
        }
    }

    // MARK: - Attachment ingest

    private func nextAttachmentSequence() -> Int {
        attachmentSequence += 1
        return attachmentSequence
    }

    private func ingestPhotoPickerItems(_ items: [PhotosPickerItem]) async {
        for item in items {
            guard let data = try? await item.loadTransferable(type: Data.self),
                  !data.isEmpty else {
                model.reportAttachmentProblem(
                    "A selected photo couldn't be loaded. Try picking it again."
                )
                continue
            }
            stagePickedData(data, suggestedName: nil)
        }
    }

    private func ingestFileImporterResult(_ result: Result<[URL], Error>) {
        guard case .success(let urls) = result else { return }
        for url in urls {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            // Reject oversized picks from metadata before reading a byte, so
            // a multi-gigabyte selection cannot balloon memory just to earn
            // the friendly size-limit copy.
            let reportedSize = (try? url.resourceValues(forKeys: [.fileSizeKey]))?.fileSize
            if let reportedSize, reportedSize > ChatAttachmentPolicy.maximumAttachmentBytes {
                let megabytes = ChatAttachmentPolicy.maximumAttachmentBytes / (1_024 * 1_024)
                model.reportAttachmentProblem(
                    "\"\(url.lastPathComponent)\" is larger than the \(megabytes) MB attachment limit."
                )
                continue
            }
            guard let data = try? Data(contentsOf: url, options: .mappedIfSafe), !data.isEmpty else {
                model.reportAttachmentProblem(
                    "\"\(url.lastPathComponent)\" couldn't be read. Try picking it again."
                )
                continue
            }
            stagePickedData(data, suggestedName: url.lastPathComponent)
        }
    }

    /// Stage picked bytes, converting image formats the gateway's vision
    /// path cannot ingest (HEIC photo-library images, TIFF) to JPEG first.
    /// Every server-supported format stays byte-identical — animated GIFs in
    /// particular.
    private func stagePickedData(_ data: Data, suggestedName: String?) {
        var payload = data
        var name = suggestedName
        if ChatAttachmentPolicy.sniffedImageMIME(data) == nil,
           !ChatAttachmentPolicy.isPDF(data),
           data.count <= ChatAttachmentPolicy.maximumAttachmentBytes,
           let jpeg = Self.transcodedJPEG(from: data) {
            payload = jpeg
            name = suggestedName.map { ($0 as NSString).deletingPathExtension + ".jpg" }
        }
        model.stageAttachment(ChatAttachmentPolicy.attachment(
            data: payload,
            suggestedName: name,
            sequence: nextAttachmentSequence()
        ))
    }

    /// Convert through ImageIO's bounded thumbnail decoder — never a
    /// full-resolution raster pass — so a crafted dimension bomb cannot
    /// exhaust memory the way `UIImage(data:)` would (the ScreenCapture
    /// validation precedent). 4096 px preserves more detail than the vision
    /// pipeline consumes. Non-image bytes cheaply return nil and stage as a
    /// plain file instead.
    private static func transcodedJPEG(from data: Data) -> Data? {
        guard let source = CGImageSourceCreateWithData(
            data as CFData,
            [kCGImageSourceShouldCache: false] as CFDictionary
        ), CGImageSourceGetCount(source) >= 1,
           let frame = CGImageSourceCreateThumbnailAtIndex(
               source,
               0,
               [
                   kCGImageSourceCreateThumbnailFromImageAlways: true,
                   kCGImageSourceCreateThumbnailWithTransform: true,
                   kCGImageSourceThumbnailMaxPixelSize: 4_096,
                   kCGImageSourceShouldCache: false,
               ] as CFDictionary
           )
        else { return nil }
        return UIImage(cgImage: frame).jpegData(compressionQuality: 0.85)
    }

    private var transcript: some View {
        TranscriptView(messages: model.messages)
            // Decorative companion docked below the transcript's safe area so it
            // never covers the newest message (follow mode anchors content to the
            // bottom), the composer, or a blocking approval/prompt.
            .safeAreaInset(edge: .bottom, alignment: .trailing, spacing: 0) {
                if case .active(let pet) = appModel.petState {
                    PetSpriteView(sheet: pet.sheet, state: model.petState, height: 64)
                        .padding(.trailing, 12)
                        .padding(.bottom, 6)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                        .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            }
            .animation(.easeOut(duration: 0.3), value: petIsActive)
    }

    private var petIsActive: Bool {
        if case .active = appModel.petState { return true }
        return false
    }

    /// At accessibility sizes the approval/question, remote actions, and
    /// composer share one scrollable dock. They cannot all fit below a useful
    /// transcript at AX XXXL, and independent fixed children otherwise squeeze
    /// and overlap one another. Regular sizes retain the compact pinned dock.
    @ViewBuilder
    private var controlDock: some View {
        if dynamicTypeSize.isAccessibilitySize {
            ScrollView {
                VStack(spacing: 0) {
                    controlStack(usesIndependentBlockingScroll: false)
                }
            }
            .scrollBounceBehavior(.basedOnSize)
            .frame(
                minHeight: hasBlockingInteraction ? 360 : 260,
                maxHeight: hasBlockingInteraction ? 580 : 460
            )
            .layoutPriority(3)
            .background(FabricTheme.surfaceRaised)
            .overlay(alignment: .top) { Divider() }
            .accessibilityLabel("Conversation controls")
            .accessibilityIdentifier("chat-interaction-dock-scroll")
        } else {
            controlStack(usesIndependentBlockingScroll: true)
        }
    }

    private var hasBlockingInteraction: Bool {
        model.pendingApproval != nil || model.pendingPrompt != nil
    }

    @ViewBuilder
    private func controlStack(usesIndependentBlockingScroll: Bool) -> some View {
        if usesIndependentBlockingScroll {
            blockingInteractionRegion
        } else {
            blockingInteractionContent
        }

        if let status = model.statusLine {
            HStack(alignment: .top, spacing: 6) {
                ProgressView().controlSize(.mini)
                Text(status)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
            }
            .padding(.horizontal)
            .padding(.vertical, 4)
        }

        if let outcome = model.unknownSendOutcome {
            UnknownSendOutcomeBanner(
                outcome: outcome,
                canCheck: model.storedSessionId?.isEmpty == false
            ) {
                Task { await model.checkConversationAfterUnknownSend() }
            }
        }

        let advertisedActions = ChatAdvertisedActions(
            supportsMethod: model.supportsGatewayMethod,
            supportsDurableWork: model.advertisesDurableWork,
            liveViewSupported: liveViewCaptureCapability.isSupported
        )
        if !advertisedActions.isEmpty {
            ChatActionStrip(
                advertised: advertisedActions,
                commandsEnabled: model.sessionReady,
                backgroundEnabled: model.sessionReady
                    && model.unknownSendOutcome == nil
                    && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    && model.canSendInBackground,
                processesEnabled: model.sessionReady,
                liveViewEnabled: model.sessionReady,
                onCommands: { showCommandCatalog = true },
                onBackground: {
                    let text = draft
                    draft = ""
                    Task { await model.sendInBackground(text) }
                },
                onProcesses: { showProcesses = true },
                onLiveView: { showLiveView = true }
            )
        }

        if !model.pendingAttachments.isEmpty {
            PendingAttachmentStrip(
                attachments: model.pendingAttachments,
                onRemove: { model.removeAttachment(id: $0) }
            )
        }

        ChatComposerBar(
            draft: $draft,
            busy: model.busy,
            sessionReady: model.sessionReady,
            hasUnknownSendOutcome: model.unknownSendOutcome != nil,
            supportsMethod: model.supportsGatewayMethod,
            onSend: { text in Task { await model.send(text) } },
            onInterrupt: { Task { await model.interrupt() } },
            supportsAttachments: model.supportsAttachments,
            hasStagedAttachments: !model.pendingAttachments.isEmpty,
            uploadLocked: model.isUploadingAttachments,
            onAttachPhotos: { showPhotoPicker = true },
            onAttachFiles: { showFileImporter = true }
        )
    }

    @ViewBuilder
    private var blockingInteractionRegion: some View {
        if hasBlockingInteraction {
            ChatBlockingInteractionRegion {
                blockingInteractionContent
            }
        }
    }

    @ViewBuilder
    private var blockingInteractionContent: some View {
        if let approval = model.pendingApproval {
            ApprovalResponseBanner(
                approval: approval,
                responseState: model.approvalResponseState
            ) { choice in
                Task { await model.respondToApproval(choice: choice) }
            }
            .disabled(
                !model.sessionReady
                    || !model.supportsGatewayMethod("approval.respond")
            )
            .accessibilityFocused(
                $focusedInteractionIdentity,
                equals: PendingInteraction.approval(approval).identity
            )
        } else if let prompt = model.pendingPrompt {
            BlockingPromptCard(
                prompt: prompt,
                answer: $promptAnswer,
                onResponse: { answer in
                    Task { await model.respondToPrompt(answer) }
                }
            )
            .disabled(
                !model.sessionReady
                    || !model.supportsGatewayMethod(prompt.responseMethod)
            )
            .accessibilityFocused(
                $focusedInteractionIdentity,
                equals: PendingInteraction.prompt(prompt).identity
            )
        }
    }
}

private struct CachedTranscriptRecoveryBanner: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    let message: String
    let onRetry: () -> Void

    var body: some View {
        Group {
            if dynamicTypeSize >= .xxLarge {
                VStack(alignment: .leading, spacing: 8) {
                    copy
                    retryButton
                }
            } else {
                HStack(alignment: .top, spacing: 10) {
                    copy
                    Spacer(minLength: 0)
                    retryButton
                }
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(FabricTheme.warning.fabricTint())
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Saved conversation is read only")
    }

    private var copy: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("Showing the saved conversation")
                .font(.subheadline.weight(.semibold))
            Text(message)
                .font(.footnote)
                .foregroundStyle(FabricTheme.textMuted)
                .fixedSize(horizontal: false, vertical: true)
            Text("Reconnect before sending or changing anything.")
                .font(.footnote)
                .foregroundStyle(FabricTheme.textMuted)
        }
    }

    private var retryButton: some View {
        Button("Retry", action: onRetry)
            .buttonStyle(.borderedProminent)
            .frame(minHeight: FabricTheme.minTarget)
            .accessibilityLabel("Retry conversation")
    }
}

/// A bounded, independently scrollable blocking region. Long commands,
/// questions, or accessibility-sized controls can scroll without pushing the
/// composer off-screen or making the transcript itself inaccessible.
private struct ChatBlockingInteractionRegion<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        ScrollView {
            content
        }
        .scrollBounceBehavior(.basedOnSize)
        .frame(minHeight: 180, maxHeight: 320)
        .layoutPriority(2)
        .background(FabricTheme.surfaceRaised)
        .overlay(alignment: .top) { Divider() }
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Response required")
        .accessibilityIdentifier("chat-blocking-interaction-scroll")
    }
}

/// Blocking clarify/credential prompt used by both live Chat and deterministic
/// UI fixtures. The field and actions stack before large type can squeeze the
/// primary controls below the 44-point touch contract.
private struct BlockingPromptCard: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    let prompt: PendingPrompt
    @Binding var answer: String
    let onResponse: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(
                prompt.kind == .clarify ? "The agent has a question" : "Credential requested",
                systemImage: prompt.kind == .clarify ? "questionmark.bubble" : "key"
            )
            .font(.subheadline.weight(.semibold))

            Text(prompt.presentationQuestion)
                .font(.callout)
                .fixedSize(horizontal: false, vertical: true)

            if !prompt.presentationChoices.isEmpty {
                VStack(spacing: 8) {
                    ForEach(prompt.presentationChoices) { choice in
                        Button(choice.label) {
                            answer = ""
                            onResponse(choice.response)
                        }
                        .buttonStyle(.bordered)
                        .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                    }
                }
            }

            Group {
                if prompt.isSecureEntry {
                    SecureField("Answer", text: $answer)
                } else {
                    TextField("Answer", text: $answer, axis: .vertical)
                        .lineLimit(1...4)
                }
            }
            .textFieldStyle(.roundedBorder)
            .frame(minHeight: FabricTheme.minTarget)

            if dynamicTypeSize >= .xxLarge {
                VStack(spacing: 8) {
                    sendButton
                    dismissButton
                }
            } else {
                HStack(spacing: 8) {
                    sendButton
                    dismissButton
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(FabricTheme.info.fabricTint())
    }

    private var sendButton: some View {
        Button("Send") {
            let response = answer
            answer = ""
            onResponse(response)
        }
        .buttonStyle(.borderedProminent)
        .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
        .disabled(answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    private var dismissButton: some View {
        Button("Dismiss", role: .cancel) {
            answer = ""
            onResponse("")
        }
        .buttonStyle(.bordered)
        .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
    }
}

/// Capability-truthful chat actions. Only advertised controls are composed;
/// an advertised control may still be temporarily disabled while disconnected
/// or while it awaits the draft/session state it needs.
private struct ChatActionStrip: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    let advertised: ChatAdvertisedActions
    let commandsEnabled: Bool
    let backgroundEnabled: Bool
    let processesEnabled: Bool
    let liveViewEnabled: Bool
    let onCommands: () -> Void
    let onBackground: () -> Void
    let onProcesses: () -> Void
    let onLiveView: () -> Void

    var body: some View {
        Group {
            if dynamicTypeSize >= .xxLarge {
                LazyVGrid(
                    columns: actionColumns,
                    spacing: 8
                ) {
                    actions(fillAvailableWidth: true)
                }
                .padding(.horizontal)
                .padding(.vertical, 4)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        actions(fillAvailableWidth: false)
                    }
                    .padding(.horizontal)
                }
            }
        }
        .frame(minHeight: FabricTheme.minTarget)
        .padding(.top, 4)
        .background(FabricTheme.surfaceRaised)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Conversation actions")
    }

    private var actionColumns: [GridItem] {
        if dynamicTypeSize.isAccessibilitySize {
            return [GridItem(.flexible())]
        }
        return [
            GridItem(.flexible(), spacing: 8),
            GridItem(.flexible(), spacing: 8),
        ]
    }

    @ViewBuilder
    private func actions(fillAvailableWidth: Bool) -> some View {
        if advertised.commands {
            ChatActionButton(
                title: "Commands",
                systemImage: "slash.circle",
                fillAvailableWidth: fillAvailableWidth,
                action: onCommands
            )
            .disabled(!commandsEnabled)
            .accessibilityHint("Browse slash commands and skills")
        }

        if advertised.background {
            ChatActionButton(
                title: "Background",
                systemImage: "moon.zzz",
                fillAvailableWidth: fillAvailableWidth,
                action: onBackground
            )
            .disabled(!backgroundEnabled)
            .accessibilityLabel("Run draft in background")
            .accessibilityHint("Starts the current draft as background work")
        }

        if advertised.processes {
            ChatActionButton(
                title: "Processes",
                systemImage: "terminal",
                fillAvailableWidth: fillAvailableWidth,
                action: onProcesses
            )
            .disabled(!processesEnabled)
            .accessibilityHint("View and control background processes")
        }

        if advertised.liveView {
            ChatActionButton(
                title: "Live View",
                systemImage: "display",
                fillAvailableWidth: fillAvailableWidth,
                action: onLiveView
            )
            .disabled(!liveViewEnabled)
            .accessibilityHint("View the remote screen while Fabric works")
        }
    }
}

/// Production composer shared with the deterministic chat fixture. This keeps
/// fixture interaction, accessibility labels, command dispatch gating, and
/// minimum target sizes aligned with the shipping surface.
private struct ChatComposerBar: View {
    @FocusState private var draftFocused: Bool

    @Binding var draft: String
    let busy: Bool
    let sessionReady: Bool
    let hasUnknownSendOutcome: Bool
    let supportsMethod: (String) -> Bool
    let onSend: (String) -> Void
    let onInterrupt: () -> Void
    var supportsAttachments = false
    var hasStagedAttachments = false
    /// True while a send's attachment uploads are in flight: the send action
    /// locks so a second tap cannot start an overlapping upload batch.
    var uploadLocked = false
    var onAttachPhotos: () -> Void = {}
    var onAttachFiles: () -> Void = {}

    var body: some View {
        HStack(spacing: 8) {
            if supportsAttachments {
                Menu {
                    Button {
                        onAttachPhotos()
                    } label: {
                        Label("Photo Library", systemImage: "photo.on.rectangle")
                    }
                    Button {
                        onAttachFiles()
                    } label: {
                        Label("Choose Files", systemImage: "folder")
                    }
                } label: {
                    Image(systemName: "paperclip")
                        .font(.title3)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .accessibilityLabel("Add attachment")
                .accessibilityHint("Attach photos, GIFs, PDFs, or files to your next message")
                .disabled(!sessionReady || hasUnknownSendOutcome || busy || uploadLocked)
            }

            TextField(
                busy ? "Steer the running turn…" : "Message Fabric… (/ for commands)",
                text: $draft,
                axis: .vertical
            )
            .textFieldStyle(.roundedBorder)
            .focused($draftFocused)
            .lineLimit(1...5)
            .frame(minHeight: FabricTheme.minTarget)
            .accessibilityIdentifier("chat-composer")
            .disabled(
                !sessionReady
                    || hasUnknownSendOutcome
                    || !supportsMethod(draftDispatchMethod)
            )

            if busy {
                Button(action: submitDraft) {
                    Image(systemName: "arrow.uturn.right.circle.fill")
                        .font(.title2)
                        .foregroundStyle(FabricTheme.threadActive)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .accessibilityLabel("Steer running turn")
                .disabled(
                    trimmedDraft.isEmpty
                        || hasUnknownSendOutcome
                        || !supportsMethod("session.steer")
                )

                Button(action: onInterrupt) {
                    Image(systemName: "stop.circle.fill")
                        .font(.title2)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .accessibilityLabel("Interrupt running turn")
                .disabled(!supportsMethod("session.interrupt"))
            } else {
                Button(action: submitDraft) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title2)
                        .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
                }
                .accessibilityLabel("Send message")
                .disabled(
                    !sessionReady
                        || hasUnknownSendOutcome
                        || uploadLocked
                        || (trimmedDraft.isEmpty && !hasStagedAttachments)
                        || !supportsMethod(draftDispatchMethod)
                )
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .disabled(!sessionReady)
        .layoutPriority(3)
    }

    private var trimmedDraft: String {
        draft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var draftDispatchMethod: String {
        if busy { return "session.steer" }
        if trimmedDraft.hasPrefix("/") { return "slash.exec" }
        return "prompt.submit"
    }

    private func submitDraft() {
        let text = draft
        draft = ""
        draftFocused = false
        onSend(text)
    }
}

private struct ChatActionButton: View {
    let title: String
    let systemImage: String
    let fillAvailableWidth: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .font(.caption.weight(.semibold))
                .lineLimit(fillAvailableWidth ? 2 : 1)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 10)
                .frame(
                    maxWidth: fillAvailableWidth ? .infinity : nil,
                    minHeight: FabricTheme.minTarget
                )
        }
        .buttonStyle(.plain)
        .foregroundStyle(FabricTheme.text)
        .contentShape(Rectangle())
    }
}

private struct UnknownSendOutcomeBanner: View {
    let outcome: UnknownSendOutcome
    let canCheck: Bool
    let onCheck: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "arrow.trianglehead.2.clockwise.rotate.90")
                .foregroundStyle(FabricTheme.warning)
                .frame(width: 24, height: 24)
            VStack(alignment: .leading, spacing: 6) {
                Text("Delivery unconfirmed")
                    .font(.subheadline.weight(.semibold))
                Text(outcome.description)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                Button("Check conversation", action: onCheck)
                    .buttonStyle(.borderedProminent)
                    .frame(minHeight: FabricTheme.minTarget)
                    .disabled(!canCheck)
                    .accessibilityHint("Reloads authoritative history without resending your message")
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(FabricTheme.warning.fabricTint())
        .accessibilityElement(children: .contain)
    }
}

/// Waiting-for-approval banner. Four canonical gateway choices stay explicit;
/// a permanent rule remains visible but unavailable when the server forbids it.
private struct ApprovalResponseBanner: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    let approval: PendingApproval
    let responseState: ApprovalResponseState
    let onChoice: (ApprovalChoice) -> Void

    private var columns: [GridItem] {
        let count = dynamicTypeSize >= .xxLarge ? 1 : 2
        return Array(repeating: GridItem(.flexible(), spacing: 8), count: count)
    }

    var body: some View {
        HStack(spacing: 0) {
            Rectangle()
                .fill(FabricTheme.warning)
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 10) {
                Label("Approval needed", systemImage: "exclamationmark.shield")
                    .font(.subheadline.weight(.semibold))

                if let summary = approval.summary, !summary.isEmpty {
                    Text(summary)
                        .font(.callout)
                        .foregroundStyle(FabricTheme.text)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityLabel("Request summary")
                        .accessibilityValue(summary)
                }
                if let command = approval.command, !command.isEmpty {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Command")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(FabricTheme.textMuted)
                        Text(command)
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                if let cwd = approval.cwd, !cwd.isEmpty {
                    Label(cwd, systemImage: "folder")
                        .font(.caption)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityLabel("Working directory")
                        .accessibilityValue(cwd)
                }

                LazyVGrid(columns: columns, spacing: 8) {
                    ForEach(ApprovalChoice.allCases, id: \.rawValue) { choice in
                        approvalButton(choice)
                    }
                }

                if !approval.allowPermanent {
                    Label(
                        "Always is unavailable because this request requires an explicit approval each time.",
                        systemImage: "info.circle"
                    )
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("approval-permanent-unavailable-reason")
                }

                if case .failed(let message) = responseState {
                    Label(message, systemImage: "exclamationmark.circle")
                        .font(.footnote)
                        .foregroundStyle(FabricTheme.danger)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityLabel("Approval response failed")
                        .accessibilityValue(message)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
        .background(FabricTheme.warning.fabricTint())
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private func approvalButton(_ choice: ApprovalChoice) -> some View {
        let isSubmittingChoice: Bool = {
            if case .submitting(let current) = responseState { return current == choice }
            return false
        }()
        Button {
            onChoice(choice)
        } label: {
            HStack(spacing: 6) {
                if isSubmittingChoice {
                    ProgressView().controlSize(.small)
                }
                Text(choice.label)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
        }
        .buttonStyle(.bordered)
        .tint(choice == .deny ? FabricTheme.danger : FabricTheme.action)
        .disabled(
            responseState.isSubmitting
                || (choice == .always && !approval.allowPermanent)
        )
        .accessibilityLabel(choice.accessibilityLabel)
        .accessibilityHint(
            choice == .always && !approval.allowPermanent
                ? "Permanent approval is unavailable for this request"
                : choice.accessibilityHint
        )
    }
}

/// Deterministic no-network surface for simulator capture and UI tests using
/// `-fabric-ui-fixture chat-activity`.
#if DEBUG
struct ChatExperienceDebugFixtureView: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    @State private var approvalState: ApprovalResponseState = .idle
    @State private var draft = "Prepare the verified build notes"
    @State private var fixtureStatus: String?
    @State private var messages: [TranscriptMessage]

    init() {
        _messages = State(initialValue: Self.makeMessages())
    }

    private static func makeMessages() -> [TranscriptMessage] {
        let parts: [AssistantTurnPart] = [
            AssistantTurnPart(
                id: "reasoning:fixture",
                content: .reasoning(.init(
                    text: "I’m checking the release branch, its tests, and the latest build receipt before recommending a ship decision.",
                    wasTruncated: false
                ))
            ),
            AssistantTurnPart(
                id: "tool:tests",
                content: .tool(.init(
                    callID: "fixture-tests",
                    name: "xcodebuild",
                    detail: "iPhone 17 Pro Max · 128 tests passed",
                    state: .complete,
                    durationSeconds: 42.8
                ))
            ),
            AssistantTurnPart(
                id: "tool:upload",
                content: .tool(.init(
                    callID: "fixture-upload",
                    name: "release_check",
                    detail: "Waiting for a signing decision",
                    state: .running,
                    durationSeconds: nil
                ))
            ),
            AssistantTurnPart(
                id: "text:fixture",
                content: .text("The app is healthy. One protected release action needs your approval.")
            ),
        ]
        return [
            TranscriptMessage(role: .user, text: "Verify the iOS release and prepare TestFlight."),
            TranscriptMessage(
                role: .assistant,
                text: "The app is healthy. One protected release action needs your approval.",
                assistantParts: parts
            ),
        ]
    }

    private let approval = PendingApproval(
        command: "gh pr merge 82 --squash",
        requestId: "fixture-approval",
        summary: "Merge the verified iOS experience pull request into main.",
        cwd: "/workspace/fabric",
        allowPermanent: false
    )

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                TranscriptView(messages: messages)
                controlDock
            }
            .background(FabricTheme.surface)
            .navigationTitle("Release readiness")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    @ViewBuilder
    private var controlDock: some View {
        if dynamicTypeSize.isAccessibilitySize {
            ScrollView {
                VStack(spacing: 0) {
                    controls(usesIndependentBlockingScroll: false)
                }
            }
            .scrollBounceBehavior(.basedOnSize)
            .frame(minHeight: 360, maxHeight: 580)
            .layoutPriority(3)
            .background(FabricTheme.surfaceRaised)
            .overlay(alignment: .top) { Divider() }
            .accessibilityLabel("Conversation controls")
            .accessibilityIdentifier("chat-interaction-dock-scroll")
        } else {
            controls(usesIndependentBlockingScroll: true)
        }
    }

    @ViewBuilder
    private func controls(usesIndependentBlockingScroll: Bool) -> some View {
        if usesIndependentBlockingScroll {
            ChatBlockingInteractionRegion {
                approvalBanner
            }
        } else {
            approvalBanner
        }

        if let fixtureStatus {
            Text(fixtureStatus)
                .font(.caption)
                .foregroundStyle(FabricTheme.textMuted)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal)
                .accessibilityIdentifier("chat-fixture-status")
        }

        ChatActionStrip(
            advertised: ChatAdvertisedActions(
                supportsMethod: { _ in true },
                supportsDurableWork: false,
                liveViewSupported: true
            ),
            commandsEnabled: true,
            backgroundEnabled: !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            processesEnabled: true,
            liveViewEnabled: true,
            onCommands: { fixtureStatus = "Command catalog opened" },
            onBackground: {
                fixtureStatus = "Draft sent to background"
                draft = ""
            },
            onProcesses: { fixtureStatus = "Process list opened" },
            onLiveView: { fixtureStatus = "Live View opened" }
        )

        ChatComposerBar(
            draft: $draft,
            busy: false,
            sessionReady: true,
            hasUnknownSendOutcome: false,
            supportsMethod: { _ in true },
            onSend: { text in
                messages.append(TranscriptMessage(role: .user, text: text))
                messages.append(TranscriptMessage(
                    role: .info,
                    text: "Fixture dispatch received without contacting a gateway."
                ))
                fixtureStatus = "Message submitted"
            },
            onInterrupt: {}
        )
    }

    private var approvalBanner: some View {
        ApprovalResponseBanner(
            approval: approval,
            responseState: approvalState
        ) { choice in
            approvalState = .submitting(choice)
            fixtureStatus = "Approval response: \(choice.label)"
        }
    }
}
#endif

private enum TranscriptScroll {
    static let coordinateSpace = "fabric.transcript.scroll"
}

/// The transcript content's frame in the scroll view's coordinate space. Its
/// `maxY` versus the viewport height gives the reader's distance from the latest
/// content; its `minY` (the scroll offset) changes on any viewport move — a
/// touch drag, trackpad, hardware key, scroll bar, or a VoiceOver scroll action
/// — yet stays put when content merely grows at the bottom. That distinction is
/// what lets follow disengage on every scroll input method while still ignoring
/// streaming growth.
private struct TranscriptContentFrameKey: PreferenceKey {
    static let defaultValue: CGRect = .zero
    static func reduce(value: inout CGRect, nextValue: () -> CGRect) {
        value = nextValue()
    }
}

/// Height of the transcript viewport.
private struct TranscriptViewportHeightKey: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

/// Pure follow-mode policy for the streaming transcript. It is extracted from
/// the SwiftUI view so every transition — engage, manual disengage, delta
/// arrival, rich-layout completion, jump, and return-to-bottom — is
/// deterministically unit-testable without a live scroll view. The view feeds
/// it measured geometry and explicit reader intent; this type owns the decision
/// of whether to chase the newest token. Follow is gated on an explicit state,
/// never on a delay or gesture-timing heuristic.
struct TranscriptFollowState: Equatable {
    /// Within this many points of the bottom the viewport counts as "at the
    /// latest turn". A small tolerance absorbs sub-pixel layout drift and the
    /// rounding in SwiftUI's scroll geometry.
    static let bottomTolerance: CGFloat = 24

    /// Whether new content should keep pulling the viewport to the latest token.
    private(set) var isFollowing: Bool
    /// Whether content arrived below the viewport while follow was disengaged.
    private(set) var hasPendingContentBelow: Bool

    init(isFollowing: Bool = true, hasPendingContentBelow: Bool = false) {
        self.isFollowing = isFollowing
        self.hasPendingContentBelow = hasPendingContentBelow
    }

    /// The "Jump to latest" affordance appears only when the reader has moved
    /// away from the bottom *and* newer content exists below the viewport.
    var showsJumpToLatest: Bool { !isFollowing && hasPendingContentBelow }

    enum ContentAdvance: Equatable {
        /// Snap the viewport to the newest content.
        case scrollToLatest
        /// Preserve the reader's current position.
        case hold
    }

    /// The transcript grew — a streaming delta, a completed turn, or a brand new
    /// message. A fresh user turn always re-engages follow (you sent it, so you
    /// expect to watch the reply). Otherwise growth is chased only while
    /// following, and remembered as pending-below while disengaged.
    mutating func transcriptDidGrow(newUserTurn: Bool) -> ContentAdvance {
        if newUserTurn {
            isFollowing = true
            hasPendingContentBelow = false
            return .scrollToLatest
        }
        if isFollowing {
            hasPendingContentBelow = false
            return .scrollToLatest
        }
        hasPendingContentBelow = true
        return .hold
    }

    /// A completed row reported its measured rich-layout height. Only a still-
    /// following viewport may chase that post-completion growth, so a reader who
    /// has scrolled up is never yanked when Markdown re-lays out.
    func richLayoutReadyShouldScroll() -> Bool { isFollowing }

    /// The reader moved the viewport — by a touch drag, trackpad, hardware key,
    /// scroll bar, or a VoiceOver scroll action. Any of these changes the scroll
    /// offset, so all of them route here: more than the tolerance from the
    /// bottom disengages follow, and returning to the bottom re-engages it. This
    /// is the single disengage path, so no scroll input method is missed — a
    /// touch-only signal would leave assistive and hardware scrolling stuck in
    /// follow. It is timing-free: driven by measured offset, never a delay.
    mutating func viewportDidScroll(distanceFromBottom: CGFloat) {
        isFollowing = distanceFromBottom <= Self.bottomTolerance
        if isFollowing {
            hasPendingContentBelow = false
        }
    }

    /// The transcript re-laid out without the reader moving it — a streaming
    /// delta grew the content, or the view rotated (the scroll offset is
    /// unchanged). Reaching the bottom (e.g. after our own snap-to-latest)
    /// re-engages follow; growth below a scrolled-up reader never does, so
    /// streaming cannot flip follow back on.
    mutating func viewportDidSettle(distanceFromBottom: CGFloat) {
        guard distanceFromBottom <= Self.bottomTolerance else { return }
        isFollowing = true
        hasPendingContentBelow = false
    }

    /// The reader tapped "Jump to latest".
    mutating func jumpToLatest() {
        isFollowing = true
        hasPendingContentBelow = false
    }
}

/// Owns transcript scrolling. Follow mode keeps the newest token in view while
/// the reader is at the bottom, but disengages the moment they scroll up so a
/// long streaming response can be read from the top without being snapped back
/// to the latest delta. A "Jump to latest" control returns to — and re-engages
/// — follow. Both scroll call sites (ordinary `messages` growth and the
/// completed row's rich-layout follow-up) are gated behind the explicit follow
/// state so neither can steal the reading position.
struct TranscriptView: View {
    let messages: [TranscriptMessage]

    @State private var follow = TranscriptFollowState()
    @State private var contentFrame: CGRect = .zero
    @State private var viewportHeight: CGFloat = 0
    @State private var lastScrollOffset: CGFloat = 0
    @State private var latestUserMessageID: UUID?

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(messages) { message in
                        MessageBubble(
                            message: message,
                            onRichLayoutReady: message.id == messages.last?.id
                                ? {
                                    if follow.richLayoutReadyShouldScroll() {
                                        proxy.scrollTo(message.id, anchor: .bottom)
                                    }
                                }
                                : nil
                        )
                        .id(message.id)
                    }
                }
                .padding()
                .background(
                    GeometryReader { geometry in
                        Color.clear.preference(
                            key: TranscriptContentFrameKey.self,
                            value: geometry.frame(
                                in: .named(TranscriptScroll.coordinateSpace)
                            )
                        )
                    }
                )
            }
            .coordinateSpace(.named(TranscriptScroll.coordinateSpace))
            .scrollDismissesKeyboard(.interactively)
            .background(
                GeometryReader { geometry in
                    Color.clear.preference(
                        key: TranscriptViewportHeightKey.self,
                        value: geometry.size.height
                    )
                }
            )
            .onPreferenceChange(TranscriptContentFrameKey.self) { value in
                contentFrame = value
                updateFollowFromGeometry()
            }
            .onPreferenceChange(TranscriptViewportHeightKey.self) { value in
                viewportHeight = value
                updateFollowFromGeometry()
            }
            .onChange(of: messages) {
                let currentUserID = messages.last(where: { $0.role == .user })?.id
                let newUserTurn = currentUserID != nil && currentUserID != latestUserMessageID
                latestUserMessageID = currentUserID
                if follow.transcriptDidGrow(newUserTurn: newUserTurn) == .scrollToLatest,
                   let lastId = messages.last?.id {
                    proxy.scrollTo(lastId, anchor: .bottom)
                }
            }
            .onAppear {
                latestUserMessageID = messages.last(where: { $0.role == .user })?.id
            }
            .overlay(alignment: .bottom) {
                if follow.showsJumpToLatest {
                    JumpToLatestButton {
                        follow.jumpToLatest()
                        if let lastId = messages.last?.id {
                            withAnimation(.easeOut(duration: 0.2)) {
                                proxy.scrollTo(lastId, anchor: .bottom)
                            }
                        }
                    }
                    .padding(.bottom, 10)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .animation(.easeInOut(duration: 0.2), value: follow.showsJumpToLatest)
        }
    }

    /// Feed the latest scroll geometry to the follow policy. A change in the
    /// content's top offset (`minY`) means the reader moved the viewport by some
    /// input method, so follow may disengage or re-engage; an unchanged offset
    /// means the transcript only grew or re-laid out, so follow may re-engage at
    /// the bottom but is never disengaged. This routes every scroll input method
    /// through the disengage path while keeping streaming growth from falsely
    /// disengaging.
    private func updateFollowFromGeometry() {
        let distanceFromBottom = max(0, contentFrame.maxY - viewportHeight)
        let scrollOffset = contentFrame.minY
        if abs(scrollOffset - lastScrollOffset) > 0.5 {
            lastScrollOffset = scrollOffset
            follow.viewportDidScroll(distanceFromBottom: distanceFromBottom)
        } else {
            follow.viewportDidSettle(distanceFromBottom: distanceFromBottom)
        }
    }
}

/// Capsule affordance that returns the reader to the newest content and
/// re-engages follow. Meets the 44-point target and carries an explicit
/// VoiceOver label/hint.
private struct JumpToLatestButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label("Jump to latest", systemImage: "arrow.down.circle.fill")
                .font(.footnote.weight(.semibold))
                .padding(.horizontal, 14)
                .frame(minHeight: FabricTheme.minTarget)
        }
        .buttonStyle(.plain)
        .foregroundStyle(FabricTheme.textOnBrand)
        .background(FabricTheme.action, in: Capsule())
        .overlay(Capsule().stroke(FabricTheme.border.opacity(0.4), lineWidth: 0.5))
        .shadow(color: Color.black.opacity(0.18), radius: 6, y: 2)
        .accessibilityIdentifier("transcript-jump-to-latest")
        .accessibilityLabel("Jump to latest")
        .accessibilityHint("Scrolls to the newest message and resumes following the response")
    }
}

private struct MessageBubble: View {
    let message: TranscriptMessage
    let onRichLayoutReady: (() -> Void)?

    var body: some View {
        switch message.role {
        // Purple marks user-controlled elements (contract): the user's own
        // words are the one solid-accent surface in the transcript.
        case .user:
            HStack {
                Spacer(minLength: 40)
                VStack(alignment: .trailing, spacing: 6) {
                    if !message.attachments.isEmpty {
                        UserAttachmentGallery(attachments: message.attachments)
                    }
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
            }
        case .assistant:
            HStack(alignment: .top) {
                AssistantTurnBody(
                    message: message,
                    onRichLayoutReady: onRichLayoutReady
                )
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

private struct AssistantTurnBody: View {
    let message: TranscriptMessage
    let onRichLayoutReady: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if message.assistantParts.isEmpty {
                AssistantMessageBody(
                    text: message.text,
                    streaming: message.streaming,
                    onRichLayoutReady: onRichLayoutReady
                )
            } else {
                ForEach(message.assistantParts) { part in
                    switch part.content {
                    case .text(let text):
                        AssistantMessageBody(
                            text: text,
                            streaming: message.streaming,
                            onRichLayoutReady: onRichLayoutReady
                        )
                    case .reasoning(let reasoning):
                        ReasoningDisclosureCard(reasoning: reasoning)
                    case .tool(let tool):
                        ToolActivityCard(tool: tool)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Fabric response and activity")
    }
}

private struct ReasoningDisclosureCard: View {
    let reasoning: AssistantTurnPart.Reasoning
    @State private var isExpanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $isExpanded) {
            Text(verbatim: reasoning.text)
                .font(.caption)
                .foregroundStyle(FabricTheme.textMuted)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
                .padding(.top, 6)
                .accessibilityLabel("Reasoning detail")
                .accessibilityValue(reasoning.text)
        } label: {
            Label("Reasoning", systemImage: "brain.head.profile")
                .font(.caption.weight(.semibold))
                .foregroundStyle(FabricTheme.textMuted)
                .frame(minHeight: FabricTheme.minTarget)
                .contentShape(Rectangle())
        }
        .tint(FabricTheme.action)
        .padding(.horizontal, 10)
        .background(FabricTheme.surfaceInset)
        .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radius))
        .accessibilityHint(isExpanded ? "Collapse reasoning" : "Expand reasoning")
    }
}

private struct ToolActivityCard: View {
    let tool: AssistantTurnPart.Tool

    private var title: String {
        tool.name.replacingOccurrences(of: "_", with: " ")
    }

    private var stateLabel: String {
        switch tool.state {
        case .generating: return "Preparing"
        case .running: return "Running"
        case .complete: return "Completed"
        case .failed: return "Failed"
        }
    }

    private var systemImage: String {
        switch tool.state {
        case .generating: return "wand.and.stars"
        case .running: return "gearshape.2"
        case .complete: return "checkmark.circle.fill"
        case .failed: return "xmark.octagon.fill"
        }
    }

    private var stateColor: Color {
        switch tool.state {
        case .generating, .running: return FabricTheme.threadActive
        case .complete: return FabricTheme.success
        case .failed: return FabricTheme.danger
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: systemImage)
                .foregroundStyle(stateColor)
                .frame(width: 20, height: 20)
                .symbolEffect(.pulse, isActive: tool.state == .running || tool.state == .generating)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(title)
                        .font(.caption.weight(.semibold))
                        .lineLimit(1)
                    Text(stateLabel)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(stateColor)
                    if let duration = tool.durationSeconds, duration >= 0 {
                        Text(duration.formatted(.number.precision(.fractionLength(1))) + "s")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(FabricTheme.textMuted)
                    }
                }
                if let detail = tool.detail, !detail.isEmpty {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(FabricTheme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                } else if tool.state == .failed {
                    Text("The tool reported a failure. No raw result is shown.")
                        .font(.caption)
                        .foregroundStyle(FabricTheme.textMuted)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FabricTheme.surfaceInset)
        .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radius))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Tool \(title), \(stateLabel)")
        .accessibilityValue(tool.detail ?? "")
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

/// Per-row rich presentation state. `reconciled` returns `nil` when a SwiftUI
/// state write would be redundant: completed rows keep their rendered
/// document across unrelated transcript updates, while an in-flight row with
/// no rich document performs no cache mutation at all.
struct AssistantTranscriptRenderCache: Equatable {
    let document: AssistantTranscriptDocument?

    init(document: AssistantTranscriptDocument? = nil) {
        self.document = document
    }

    func reconciled(
        for input: AssistantTranscriptRenderInput,
        documentBuilder: (String) -> AssistantTranscriptDocument = {
            AssistantTranscriptDocument($0)
        }
    ) -> Self? {
        if input.streaming {
            // A non-nil document is the authoritative rich-state marker.
            // Initial and subsequent streaming deltas therefore perform no
            // write; only a real rich-to-streaming transition clears it.
            guard document != nil else { return nil }
            return Self()
        }

        guard document?.source != input.text else { return nil }
        return Self(document: documentBuilder(input.text))
    }
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

    /// Presentation-ready blocks. Inline Markdown is sanitized and parsed
    /// while the completed document is created, never from a SwiftUI `body`.
    /// Keeping the source `blocks` beside these values preserves the small,
    /// testable block grammar without making later transcript invalidations
    /// repeat Foundation's inline parser.
    enum RenderBlock: Equatable {
        case paragraph(AttributedString)
        case heading(level: Int, text: AttributedString)
        case listItem(marker: ListMarker, depth: Int, text: AttributedString)
        case code(language: String?, text: String)
        case diff(String)
    }

    let source: String
    let blocks: [Block]
    let renderBlocks: [RenderBlock]

    var containsTechnicalBlock: Bool {
        blocks.contains { block in
            switch block {
            case .code, .diff: return true
            default: return false
            }
        }
    }

    init(
        _ source: String,
        inlineRenderer: (String) -> AttributedString = {
            AssistantMarkdownSafety.attributedString(from: $0)
        }
    ) {
        self.source = source
        let parsedBlocks = Self.parse(source)
        blocks = parsedBlocks
        renderBlocks = parsedBlocks.map { block in
            switch block {
            case .paragraph(let markdown):
                return .paragraph(inlineRenderer(markdown))
            case .heading(let level, let markdown):
                return .heading(level: level, text: inlineRenderer(markdown))
            case .listItem(let marker, let depth, let markdown):
                return .listItem(
                    marker: marker,
                    depth: depth,
                    text: inlineRenderer(markdown)
                )
            case .code(let language, let text):
                return .code(language: language, text: text)
            case .diff(let text):
                return .diff(text)
            }
        }
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

private struct RichTranscriptHeightPreferenceKey: PreferenceKey {
    static let defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct AssistantMessageBody: View {
    let text: String
    let streaming: Bool
    let onRichLayoutReady: (() -> Void)?

    @State private var renderCache = AssistantTranscriptRenderCache()

    private var renderInput: AssistantTranscriptRenderInput {
        AssistantTranscriptRenderInput(text: text, streaming: streaming)
    }

    var body: some View {
        Group {
            switch streaming ? AssistantTranscriptPresentationMode.streamingPlain : .rich {
            case .streamingPlain:
                Text(verbatim: text.isEmpty ? "…" : text)
                    .font(.subheadline)
                    .foregroundStyle(FabricTheme.text)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                    .accessibilityLabel("Fabric")
                    .accessibilityValue(text.isEmpty ? "Streaming response" : text)
            case .rich:
                if let document = renderCache.document {
                    AssistantTranscriptView(document: document)
                        .frame(
                            maxWidth: document.containsTechnicalBlock ? .infinity : nil,
                            alignment: .leading
                        )
                        .background {
                            if onRichLayoutReady != nil {
                                GeometryReader { geometry in
                                    Color.clear.preference(
                                        key: RichTranscriptHeightPreferenceKey.self,
                                        value: geometry.size.height
                                    )
                                }
                            }
                        }
                        .accessibilityElement(children: .contain)
                        .accessibilityLabel("Fabric response")
                } else {
                    // A completed row is parsed once on appearance. This
                    // verbatim fallback prevents a blank flash and preserves
                    // malformed text while the state cache is populated.
                    Text(verbatim: text)
                        .font(.subheadline)
                        .foregroundStyle(FabricTheme.text)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                        .accessibilityLabel("Fabric")
                        .accessibilityValue(text)
                }
            }
        }
        .onAppear { cacheDocument(for: renderInput) }
        .onChange(of: renderInput) { _, newValue in
            cacheDocument(for: newValue)
        }
        .onPreferenceChange(RichTranscriptHeightPreferenceKey.self) { height in
            guard height > 0, renderCache.document != nil else { return }
            onRichLayoutReady?()
        }
    }

    private func cacheDocument(for input: AssistantTranscriptRenderInput) {
        guard let reconciled = renderCache.reconciled(for: input) else { return }
        renderCache = reconciled
    }
}

private struct AssistantTranscriptView: View {
    let document: AssistantTranscriptDocument

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(document.renderBlocks.indices, id: \.self) { index in
                blockView(document.renderBlocks[index])
            }
        }
    }

    @ViewBuilder
    private func blockView(_ block: AssistantTranscriptDocument.RenderBlock) -> some View {
        switch block {
        case .paragraph(let attributed):
            SafeInlineMarkdownText(attributed: attributed, font: .subheadline)
        case .heading(let level, let attributed):
            SafeInlineMarkdownText(attributed: attributed, font: headingFont(level))
                .accessibilityAddTraits(.isHeader)
        case .listItem(let marker, let depth, let attributed):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(marker.displayText)
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(FabricTheme.textMuted)
                SafeInlineMarkdownText(attributed: attributed, font: .subheadline)
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
    let attributed: AttributedString
    let font: Font

    var body: some View {
        Text(attributed)
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

// MARK: - Attachment presentation

/// Horizontally scrolling previews of media staged for the next message.
private struct PendingAttachmentStrip: View {
    let attachments: [ChatComposerAttachment]
    let onRemove: (UUID) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(attachments) { attachment in
                    ZStack(alignment: .topTrailing) {
                        PendingAttachmentTile(attachment: attachment)
                        Button {
                            onRemove(attachment.id)
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .font(.body)
                                .symbolRenderingMode(.palette)
                                .foregroundStyle(FabricTheme.text, FabricTheme.surfaceRaised)
                                .frame(minWidth: 28, minHeight: 28)
                        }
                        .accessibilityLabel("Remove \(attachment.filename)")
                    }
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 6)
        }
        .background(FabricTheme.surfaceRaised)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Attachments ready to send")
    }
}

private struct PendingAttachmentTile: View {
    let attachment: ChatComposerAttachment

    var body: some View {
        Group {
            if attachment.kind == .image {
                BoundedImageView(data: attachment.data, contentMode: .scaleAspectFill)
                    .frame(width: 72, height: 72)
                    .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radius))
            } else {
                VStack(spacing: 4) {
                    Image(systemName: attachment.kind == .pdf ? "doc.richtext" : "doc")
                        .font(.title3)
                        .foregroundStyle(FabricTheme.action)
                    Text(attachment.filename)
                        .font(.caption2)
                        .foregroundStyle(FabricTheme.textMuted)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                }
                .padding(6)
                .frame(width: 96, height: 72)
                .background(FabricTheme.surfaceInset)
                .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radius))
            }
        }
        .accessibilityLabel(attachment.filename)
    }
}

/// Media the user sent with a message, rendered from the local bytes —
/// nothing is fetched over the network. Tapping opens the system Quick Look
/// preview (pinch zoom, animated GIF playback, full PDF reader).
private struct UserAttachmentGallery: View {
    let attachments: [TranscriptAttachmentPreview]

    var body: some View {
        VStack(alignment: .trailing, spacing: 6) {
            ForEach(attachments) { attachment in
                TranscriptAttachmentView(attachment: attachment)
            }
        }
    }
}

/// Compact token counts: 999 → "999", 12_400 → "12.4k", 1_900_000 → "1.9m"
/// (one decimal, trailing ".0" trimmed).
private enum TokenCountFormat {
    static func compact(_ count: Int) -> String {
        if count < 1_000 { return "\(count)" }
        if count < 1_000_000 { return scaled(count, divisor: 1_000, suffix: "k") }
        return scaled(count, divisor: 1_000_000, suffix: "m")
    }

    private static func scaled(_ count: Int, divisor: Int, suffix: String) -> String {
        let value = (Double(count) / Double(divisor) * 10).rounded() / 10
        if value == value.rounded() {
            return "\(Int(value))\(suffix)"
        }
        return String(format: "%.1f", value) + suffix
    }
}

/// Compact usage indicator for the chat top bar. The context gauge appears
/// only when the gateway reports a real current-window reading; cumulative
/// totals are never converted into a percent.
private struct SessionUsageChip: View {
    let usage: SessionUsage
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(compactText, systemImage: "chart.bar.fill")
                .font(.caption.weight(.semibold))
                .foregroundStyle(FabricTheme.textMuted)
                .lineLimit(1)
                .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
        }
        .buttonStyle(.plain)
        .contentShape(Rectangle())
        .accessibilityLabel("Session token usage")
        .accessibilityValue(compactText)
        .accessibilityHint("Shows token and context details for this conversation")
        .accessibilityIdentifier("chat-usage-chip")
    }

    private var compactText: String {
        if let percent = usage.contextPercent {
            return "\(percent)% context"
        }
        return "\(TokenCountFormat.compact(usage.totalTokens ?? 0)) tok"
    }
}

/// "Session usage" detail behind the top-bar chip. Rows appear only for
/// reported values; the context section requires both a used and a max
/// reading, so a missing gauge is presented as missing, never as 0%.
private struct SessionUsageDetailSheet: View {
    @Environment(\.dismiss) private var dismiss

    let usage: SessionUsage

    var body: some View {
        NavigationStack {
            List {
                Section {
                    row("Input", usage.input.map(TokenCountFormat.compact))
                    row("Output", usage.output.map(TokenCountFormat.compact))
                    row("Reasoning", usage.reasoning.map(TokenCountFormat.compact))
                    row("Total", usage.totalTokens.map(TokenCountFormat.compact))
                    row("API calls", usage.calls.map { "\($0)" })
                    row("Compressions", usage.compressions.map { "\($0)" })
                    row("Active subagents", usage.activeSubagents.map { "\($0)" })
                    row("Model", usage.model)
                }
                if let used = usage.contextUsed, let maximum = usage.contextMax, maximum > 0 {
                    Section("Context") {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text("\(TokenCountFormat.compact(used)) used")
                                    .foregroundStyle(FabricTheme.text)
                                Spacer()
                                Text("of \(TokenCountFormat.compact(maximum))")
                                    .foregroundStyle(FabricTheme.textMuted)
                            }
                            .font(.subheadline)
                            ProgressView(value: Double(min(used, maximum)), total: Double(maximum))
                                .tint(FabricTheme.action)
                        }
                        .padding(.vertical, 4)
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel("Context window")
                        .accessibilityValue("\(used) of \(maximum) tokens used")
                    }
                }
            }
            .navigationTitle("Session usage")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .frame(minHeight: FabricTheme.minTarget)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    @ViewBuilder
    private func row(_ title: String, _ value: String?) -> some View {
        if let value {
            HStack {
                Text(title)
                    .foregroundStyle(FabricTheme.text)
                Spacer()
                Text(value)
                    .foregroundStyle(FabricTheme.textMuted)
                    .monospacedDigit()
            }
            .font(.subheadline)
            .frame(minHeight: FabricTheme.minTarget)
            .accessibilityElement(children: .combine)
        }
    }
}

private struct TranscriptAttachmentView: View {
    let attachment: TranscriptAttachmentPreview
    @State private var previewURL: URL?

    var body: some View {
        Button {
            previewURL = AttachmentPreviewStore.writeTemporaryFile(
                data: attachment.data,
                filename: attachment.filename
            )
        } label: {
            if attachment.kind == .image {
                BoundedImageView(data: attachment.data, contentMode: .scaleAspectFit)
                    .frame(maxWidth: 220)
                    .frame(height: 160)
                    .clipShape(RoundedRectangle(cornerRadius: FabricTheme.radiusLarge))
            } else {
                HStack(spacing: 6) {
                    Image(systemName: attachment.kind == .pdf ? "doc.richtext" : "doc")
                        .foregroundStyle(FabricTheme.action)
                    Text(attachment.filename)
                        .font(.caption)
                        .foregroundStyle(FabricTheme.text)
                        .lineLimit(1)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(FabricTheme.surfaceInset)
                .clipShape(Capsule())
            }
        }
        .buttonStyle(.plain)
        .frame(minHeight: FabricTheme.minTarget)
        .accessibilityLabel(accessibilityDescription)
        .accessibilityHint("Opens a full-screen preview")
        .quickLookPreview($previewURL)
        .onChange(of: previewURL) { previous, current in
            if current == nil {
                AttachmentPreviewStore.removeTemporaryFile(previous)
            }
        }
    }

    private var accessibilityDescription: String {
        switch attachment.kind {
        case .image: return "Attached image \(attachment.filename)"
        case .pdf: return "Attached PDF \(attachment.filename)"
        case .file: return "Attached file \(attachment.filename)"
        }
    }
}

/// Writes attachment bytes to a protected app-temporary file so Quick Look
/// can present them; the file is removed as soon as the preview dismisses.
private enum AttachmentPreviewStore {
    static func writeTemporaryFile(data: Data, filename: String) -> URL? {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("AttachmentPreviews", isDirectory: true)
        try? FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.complete]
        )
        let safeName = filename
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "\\", with: "_")
        let url = directory.appendingPathComponent(
            UUID().uuidString + "-" + (safeName.isEmpty ? "attachment" : safeName)
        )
        do {
            try data.write(to: url, options: [.atomic, .completeFileProtection])
            return url
        } catch {
            return nil
        }
    }

    static func removeTemporaryFile(_ url: URL?) {
        guard let url else { return }
        try? FileManager.default.removeItem(at: url)
    }

    /// Remove the whole preview directory. iOS only purges tmp under
    /// storage pressure, so surface teardown sweeps deterministically.
    static func removeAllTemporaryFiles() {
        try? FileManager.default.removeItem(
            at: FileManager.default.temporaryDirectory
                .appendingPathComponent("AttachmentPreviews", isDirectory: true)
        )
    }
}

/// Renders local image bytes, animating multi-frame GIFs. SwiftUI's `Image`
/// cannot play GIF data; `UIImageView` can, given the decoded frames. Every
/// frame is decoded through ImageIO's thumbnail path at a bounded pixel size,
/// and animation stops adding frames at a fixed decoded-byte budget, so even
/// a pathological GIF cannot balloon transcript memory. Only bytes the user
/// picked on this device ever reach this view.
private struct BoundedImageView: UIViewRepresentable {
    /// Frames render at most this many pixels on their long edge — plenty for
    /// a transcript preview; Quick Look shows the full-resolution original.
    static let maximumFramePixelSize = 1_024
    /// Total decoded animation budget (RGBA bytes across kept frames).
    static let maximumAnimatedDecodedBytes = 48 * 1_024 * 1_024
    static let maximumGIFFrames = 120

    let data: Data
    let contentMode: UIView.ContentMode

    func makeUIView(context: Context) -> UIImageView {
        let view = UIImageView()
        view.contentMode = contentMode
        view.clipsToBounds = true
        view.isAccessibilityElement = false
        view.setContentHuggingPriority(.defaultLow, for: .horizontal)
        view.setContentHuggingPriority(.defaultLow, for: .vertical)
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        view.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        view.image = Self.decodedImage(from: data)
        return view
    }

    func updateUIView(_ view: UIImageView, context: Context) {
        view.contentMode = contentMode
        if view.image == nil {
            view.image = Self.decodedImage(from: data)
        }
    }

    static func decodedImage(from data: Data) -> UIImage? {
        guard let source = CGImageSourceCreateWithData(
            data as CFData,
            [kCGImageSourceShouldCache: false] as CFDictionary
        ) else { return nil }

        let frameCount = CGImageSourceGetCount(source)
        guard ChatAttachmentPolicy.isAnimatableGIF(data), frameCount > 1 else {
            return boundedFrame(source: source, index: 0).map(UIImage.init(cgImage:))
        }

        var frames: [UIImage] = []
        var duration: Double = 0
        var decodedBytes = 0
        for index in 0..<min(frameCount, maximumGIFFrames) {
            guard let frame = boundedFrame(source: source, index: index) else { continue }
            decodedBytes += frame.width * frame.height * 4
            guard frames.isEmpty || decodedBytes <= maximumAnimatedDecodedBytes else { break }
            frames.append(UIImage(cgImage: frame))
            duration += frameDelay(source: source, index: index)
        }
        guard let first = frames.first else { return nil }
        guard frames.count > 1 else { return first }
        return UIImage.animatedImage(
            with: frames,
            duration: max(duration, 0.04 * Double(frames.count))
        )
    }

    private static func boundedFrame(source: CGImageSource, index: Int) -> CGImage? {
        CGImageSourceCreateThumbnailAtIndex(
            source,
            index,
            [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: maximumFramePixelSize,
                kCGImageSourceShouldCache: false,
            ] as CFDictionary
        )
    }

    private static func frameDelay(source: CGImageSource, index: Int) -> Double {
        guard let properties = CGImageSourceCopyPropertiesAtIndex(source, index, nil) as? [CFString: Any],
              let gif = properties[kCGImagePropertyGIFDictionary] as? [CFString: Any]
        else { return 0.1 }
        let delay = (gif[kCGImagePropertyGIFUnclampedDelayTime] as? NSNumber)?.doubleValue
            ?? (gif[kCGImagePropertyGIFDelayTime] as? NSNumber)?.doubleValue
            ?? 0.1
        // Browsers normalize near-zero GIF delays the same way.
        return delay < 0.02 ? 0.1 : delay
    }
}

/// Animated spritesheet companion shared by Chat and Settings. The base64
/// atlas is decoded once per pet revision; a TimelineView steps frames along
/// the row for the mapped state. Every geometry access is bounds-checked so a
/// malformed sheet renders the idle row or nothing — never a crash.
struct PetSpriteView: View {
    let sheet: PetSpriteSheet
    let state: PetState
    var height: CGFloat = 72

    private static let atlasCache = NSCache<NSString, UIImage>()

    var body: some View {
        if let atlas = Self.atlasImage(for: sheet)?.cgImage,
           let row = resolvedRow(atlasWidth: atlas.width, atlasHeight: atlas.height) {
            TimelineView(.animation(minimumInterval: row.stepSeconds)) { context in
                let column = Self.frameColumn(for: context.date, row: row)
                if let frame = atlas.cropping(to: CGRect(
                    x: CGFloat(column * sheet.frameW),
                    y: CGFloat(row.index * sheet.frameH),
                    width: CGFloat(sheet.frameW),
                    height: CGFloat(sheet.frameH)
                )) {
                    // Sprite art faces left; stationary display needs no
                    // mirroring.
                    Image(decorative: frame, scale: 1)
                        .interpolation(.none)
                        .resizable()
                        .scaledToFit()
                        .frame(height: height)
                }
            }
            .frame(height: height)
        }
    }

    private struct SpriteRow {
        let index: Int
        let frames: Int
        let stepMilliseconds: Int

        var stepSeconds: Double { Double(stepMilliseconds) / 1_000 }
    }

    private func resolvedRow(atlasWidth: Int, atlasHeight: Int) -> SpriteRow? {
        guard sheet.frameW > 0, sheet.frameH > 0, sheet.loopMs > 0 else { return nil }
        let name = resolvedRowName
        guard let index = sheet.stateRows.firstIndex(of: name) else { return nil }
        // The gateway fail-opens `framesByRow` to empty on a decode hiccup; match
        // the desktop renderer and fall back to `framesPerState` (still bounds-
        // checked against the decoded atlas) so an active pet never renders blank.
        let declared = sheet.framesByRow[name] ?? 0
        let frames = declared > 0 ? declared : min(sheet.framesPerState, atlasWidth / sheet.frameW)
        guard frames > 0,
              (index + 1) * sheet.frameH <= atlasHeight,
              frames * sheet.frameW <= atlasWidth
        else { return nil }
        return SpriteRow(
            index: index,
            frames: frames,
            stepMilliseconds: max(1, sheet.loopMs / frames)
        )
    }

    /// UI state → canonical row name, falling back to `idle` when the mapped
    /// row is missing from `stateRows` or has no declared frames. Rows can be
    /// ragged, so `framesByRow` chooses a non-idle row when available; the
    /// bounded `framesPerState` fallback is applied later in `resolvedRow`.
    private var resolvedRowName: String {
        let candidate: String
        switch state {
        case .wave: candidate = "waving"
        case .jump: candidate = "jumping"
        case .run: candidate = "running"
        case .idle: candidate = "idle"
        case .failed: candidate = "failed"
        case .review: candidate = "review"
        case .waiting: candidate = "waiting"
        }
        guard sheet.stateRows.contains(candidate),
              (sheet.framesByRow[candidate] ?? 0) > 0
        else { return "idle" }
        return candidate
    }

    private static func frameColumn(for date: Date, row: SpriteRow) -> Int {
        let elapsedMilliseconds = Int(date.timeIntervalSinceReferenceDate * 1_000)
        return (elapsedMilliseconds / row.stepMilliseconds) % row.frames
    }

    private static func atlasImage(for sheet: PetSpriteSheet) -> UIImage? {
        let key = "\(sheet.slug)#\(sheet.spritesheetRevision)" as NSString
        if let cached = atlasCache.object(forKey: key) { return cached }
        guard let data = Data(base64Encoded: sheet.spritesheetBase64),
              let image = UIImage(data: data)
        else { return nil }
        atlasCache.setObject(image, forKey: key)
        return image
    }
}
