import SwiftUI
import UIKit

struct FabricLinkPairingView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    let pairing: FabricLinkPairing

    @State private var controllerName = UIDevice.current.name
    @State private var authenticationString: String?
    @State private var pairedMachine: FabricLinkMachine?
    @State private var errorMessage: String?
    @State private var started = false
    @State private var pairingTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            Form {
                Section("Computer identity") {
                    LabeledContent("Fingerprint") {
                        Text(pairing.machineFingerprint)
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                    }
                    LabeledContent("Relay") {
                        Text(pairing.relayOrigin)
                            .font(.caption)
                            .multilineTextAlignment(.trailing)
                    }
                    TextField("Name shown on the computer", text: $controllerName)
                        .disabled(started)
                }

                Section("Verify both screens") {
                    if let authenticationString {
                        Text(authenticationString)
                            .font(.system(size: 34, weight: .semibold, design: .monospaced))
                            .tracking(6)
                            .frame(maxWidth: .infinity)
                            .accessibilityLabel(
                                "Authentication code \(authenticationString.map(String.init).joined(separator: " "))"
                            )
                        Text("Compare this six-digit code with the computer. Approve there only when both codes match.")
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.textMuted)
                    } else if pairedMachine == nil, errorMessage == nil {
                        ProgressView("Protecting the controller key on this iPhone…")
                    }
                }

                if let pairedMachine {
                    Section {
                        Label(
                            "\(pairedMachine.label) is paired",
                            systemImage: "checkmark.shield.fill"
                        )
                        .foregroundStyle(FabricTheme.success)
                        Text("Granted: \(pairedMachine.grants.joined(separator: ", "))")
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.textMuted)
                    }
                }

                if let errorMessage {
                    Section {
                        Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(FabricTheme.warning)
                        Text("No password, GitHub account, Google account, or gateway token was used. A pending local key can be removed from the Fabric Link machine list.")
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.textMuted)
                    }
                }

                Section {
                    if pairedMachine != nil {
                        Button("Done") { dismiss() }
                            .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                    } else if errorMessage != nil {
                        Button("Close") { dismiss() }
                            .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                    } else {
                        Button("Cancel", role: .cancel) {
                            pairingTask?.cancel()
                            dismiss()
                        }
                        .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                    }
                }
            }
            .navigationTitle("Pair Fabric Link")
            .navigationBarTitleDisplayMode(.inline)
            .interactiveDismissDisabled(pairedMachine == nil && errorMessage == nil)
            .task {
                guard !started else { return }
                started = true
                let task = Task { @MainActor in
                    do {
                        pairedMachine = try await appModel.linkController.pair(
                            pairing,
                            name: controllerName
                        ) { code in
                            authenticationString = code
                        }
                    } catch is CancellationError {
                        return
                    } catch {
                        errorMessage = error.localizedDescription
                    }
                }
                pairingTask = task
                await task.value
            }
            .onDisappear {
                if pairedMachine == nil {
                    pairingTask?.cancel()
                }
            }
        }
    }
}

struct FabricLinkMachinesView: View {
    @Environment(AppModel.self) private var appModel

    @State private var showScanner = false
    @State private var showPaste = false
    @State private var pairing: FabricLinkPairing?
    @State private var pastedLink = ""
    @State private var pasteError: String?

    var body: some View {
        List {
            Section {
                Label {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("End-to-end encrypted machine access")
                        Text("Device keys, local approval, and a blind relay. No social login or inbound port.")
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.textMuted)
                    }
                } icon: {
                    Image(systemName: "lock.shield.fill")
                        .foregroundStyle(FabricTheme.action)
                }
            }

            Section("Paired machines") {
                if appModel.linkController.machines.isEmpty {
                    Text("No computers are paired to this iPhone.")
                        .foregroundStyle(FabricTheme.textMuted)
                } else {
                    ForEach(appModel.linkController.machines) { machine in
                        NavigationLink {
                            FabricLinkMachineView(machineID: machine.id)
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Text(machine.label)
                                    Spacer()
                                    Text(machine.status == .active ? "Active" : "Pending")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(
                                            machine.status == .active
                                                ? FabricTheme.success
                                                : FabricTheme.warning
                                        )
                                }
                                Text(machine.machineFingerprint)
                                    .font(.system(.caption, design: .monospaced))
                                    .foregroundStyle(FabricTheme.textMuted)
                            }
                        }
                    }
                }
            }

            Section("Add a computer") {
                Button {
                    showScanner = true
                } label: {
                    Label("Scan Fabric Link code", systemImage: "qrcode.viewfinder")
                }
                Button {
                    showPaste = true
                } label: {
                    Label("Paste pairing link", systemImage: "doc.on.clipboard")
                }
            }
        }
        .navigationTitle("Fabric Link")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { appModel.linkController.reload() }
        .sheet(isPresented: $showScanner) {
            PairingScannerFlow(
                onScan: acceptScan,
                onCancel: { showScanner = false },
                onAdvancedSetup: {
                    showScanner = false
                    showPaste = true
                }
            )
        }
        .sheet(isPresented: $showPaste) {
            pasteSheet
        }
        .sheet(item: $pairing) { pairing in
            FabricLinkPairingView(pairing: pairing)
        }
    }

    private var pasteSheet: some View {
        NavigationStack {
            Form {
                Section("Fabric Link pairing URL") {
                    TextEditor(text: $pastedLink)
                        .font(.system(.footnote, design: .monospaced))
                        .frame(minHeight: 130)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    if let pasteError {
                        Text(pasteError)
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.warning)
                    }
                }
                Section {
                    Button("Continue") {
                        do {
                            pairing = try FabricLinkPairing.parse(
                                pastedLink.trimmingCharacters(in: .whitespacesAndNewlines)
                            )
                            pastedLink = ""
                            pasteError = nil
                            showPaste = false
                        } catch {
                            pasteError = error.localizedDescription
                        }
                    }
                    .frame(maxWidth: .infinity, minHeight: FabricTheme.minTarget)
                }
            }
            .navigationTitle("Paste pairing link")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { showPaste = false }
                }
            }
        }
    }

    private func acceptScan(_ raw: String) -> PairingScannerDisposition {
        do {
            pairing = try FabricLinkPairing.parse(raw)
            showScanner = false
            return .accepted
        } catch {
            return .retry(message: error.localizedDescription)
        }
    }
}

private struct FabricLinkMachineView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    let machineID: String

    @State private var showDispatch = false
    @State private var confirmForget = false
    @State private var errorMessage: String?

    private var machine: FabricLinkMachine? {
        appModel.linkController.machines.first { $0.id == machineID }
    }

    var body: some View {
        Form {
            if let machine {
                Section("Identity") {
                    LabeledContent("Computer", value: machine.label)
                    LabeledContent("Fingerprint") {
                        Text(machine.machineFingerprint)
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                    }
                    LabeledContent("Relay", value: machine.relayOrigin)
                    LabeledContent(
                        "Status",
                        value: machine.status == .active ? "Active" : "Pending"
                    )
                    if !machine.grants.isEmpty {
                        LabeledContent(
                            "Grants",
                            value: machine.grants.joined(separator: ", ")
                        )
                    }
                }

                if machine.status == .active {
                    Section("Actions") {
                        Button {
                            showDispatch = true
                        } label: {
                            Label("Dispatch new Work", systemImage: "paperplane.fill")
                        }
                        .disabled(!machine.grants.contains("dispatch"))

                        NavigationLink {
                            FabricLinkRemoteSessionsView(machine: machine)
                        } label: {
                            Label("Open exact live session", systemImage: "terminal.fill")
                        }
                        .disabled(
                            !machine.grants.contains("observe")
                                || !machine.grants.contains("chat")
                        )
                    }
                } else {
                    Section {
                        Text("Pairing did not finish. Remove this pending key, then create and scan a fresh code on the computer.")
                            .font(.footnote)
                            .foregroundStyle(FabricTheme.textMuted)
                    }
                }

                Section {
                    Button("Forget on this iPhone", role: .destructive) {
                        confirmForget = true
                    }
                } footer: {
                    Text("Forgetting removes the protected controller key here. Also run `fabric link revoke` on the computer if this controller is still active there.")
                }
            } else {
                ContentUnavailableView(
                    "Machine not found",
                    systemImage: "desktopcomputer.trianglebadge.exclamationmark"
                )
            }
        }
        .navigationTitle(machine?.label ?? "Fabric Link")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showDispatch) {
            if let machine {
                FabricLinkDispatchView(machine: machine)
            }
        }
        .confirmationDialog(
            "Forget this Fabric Link machine?",
            isPresented: $confirmForget,
            titleVisibility: .visible
        ) {
            Button("Forget protected key", role: .destructive) {
                guard let machine else { return }
                do {
                    try appModel.linkController.forget(machine)
                    dismiss()
                } catch {
                    errorMessage = error.localizedDescription
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This cannot revoke a computer that is currently offline. Revoke this iPhone from the computer as well.")
        }
        .alert("Fabric Link", isPresented: Binding(
            get: { errorMessage != nil },
            set: { if !$0 { errorMessage = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(errorMessage ?? "")
        }
    }
}

private struct FabricLinkDispatchView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    let machine: FabricLinkMachine

    @State private var title = "Dispatched from Fabric Mobile"
    @State private var prompt = ""
    @State private var receipt: String?
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Title", text: $title)
                    TextEditor(text: $prompt)
                        .frame(minHeight: 180)
                } header: {
                    Text("New durable Work")
                } footer: {
                    Text("Dispatch creates separate background Work. It does not turn the current terminal conversation into a remote chat.")
                }
                if let receipt {
                    Section("Accepted") {
                        Label("The computer accepted this Work.", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(FabricTheme.success)
                        Text(receipt)
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                    }
                }
                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .foregroundStyle(FabricTheme.warning)
                    }
                }
                Section {
                    Button {
                        Task { await dispatch() }
                    } label: {
                        HStack {
                            Spacer()
                            if appModel.linkController.isWorking {
                                ProgressView()
                            } else {
                                Text("Dispatch")
                            }
                            Spacer()
                        }
                    }
                    .disabled(
                        prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || appModel.linkController.isWorking
                    )
                }
            }
            .navigationTitle(machine.label)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Close") { dismiss() }
                }
            }
        }
    }

    private func dispatch() async {
        errorMessage = nil
        do {
            let result = try await appModel.linkController.dispatch(
                to: machine,
                prompt: prompt,
                title: title
            )
            receipt = fabricLinkDisplayJSON(result)
            prompt = ""
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct FabricLinkRemoteSession: Identifiable, Hashable {
    let id: String
    let title: String
    let status: String
}

private struct FabricLinkRemoteSessionsView: View {
    @Environment(AppModel.self) private var appModel

    let machine: FabricLinkMachine

    @State private var sessions: [FabricLinkRemoteSession] = []
    @State private var loading = false
    @State private var errorMessage: String?

    var body: some View {
        List {
            Section {
                Text("Only sessions explicitly published with `/remote` appear here. Dispatch is separate and creates new Work.")
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.textMuted)
            }
            Section("Published now") {
                if loading {
                    ProgressView("Loading live sessions…")
                } else if sessions.isEmpty {
                    Text("No exact live sessions are published.")
                        .foregroundStyle(FabricTheme.textMuted)
                } else {
                    ForEach(sessions) { session in
                        NavigationLink {
                            FabricLinkAttachedSessionView(
                                machine: machine,
                                session: session
                            )
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(session.title)
                                Text(session.status)
                                    .font(.caption)
                                    .foregroundStyle(FabricTheme.textMuted)
                            }
                        }
                    }
                }
            }
            if let errorMessage {
                Section {
                    Text(errorMessage)
                        .foregroundStyle(FabricTheme.warning)
                }
            }
        }
        .navigationTitle("Live sessions")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await load() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .disabled(loading || appModel.linkController.isWorking)
            }
        }
        .task { await load() }
    }

    private func load() async {
        guard !loading else { return }
        loading = true
        errorMessage = nil
        defer { loading = false }
        do {
            let result = try await appModel.linkController.invoke(
                machine: machine,
                method: "session.active_list",
                params: .map([:]),
                timeoutSeconds: 60
            )
            guard let rows = result.mapValue?["sessions"]?.arrayValue else {
                throw FabricLinkError.invalidRecord
            }
            var published: [FabricLinkRemoteSession] = []
            for row in rows {
                guard let map = row.mapValue,
                      let id = map["id"]?.stringValue else {
                    continue
                }
                do {
                    let status = try await appModel.linkController.invoke(
                        machine: machine,
                        method: "session.remote_status",
                        params: .map(["session_id": .string(id)]),
                        timeoutSeconds: 30
                    )
                    guard status.mapValue?["published"]?.boolValue == true else {
                        continue
                    }
                    published.append(FabricLinkRemoteSession(
                        id: id,
                        title: map["title"]?.stringValue
                            ?? map["preview"]?.stringValue
                            ?? id,
                        status: map["status"]?.stringValue ?? "live"
                    ))
                } catch {
                    // A session that stopped being published between list and
                    // status is simply absent from this exact-live picker.
                }
            }
            sessions = published
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct FabricLinkTranscriptLine: Identifiable {
    let id = UUID()
    let role: String
    var text: String
}

private struct FabricLinkAttachedSessionView: View {
    @Environment(AppModel.self) private var appModel

    let machine: FabricLinkMachine
    let session: FabricLinkRemoteSession

    @State private var lines: [FabricLinkTranscriptLine] = []
    @State private var eventSequence = 0
    @State private var remoteInput = ""
    @State private var attached = false
    @State private var errorMessage: String?

    private var controllerID: String { "ios:\(machine.id)" }

    var body: some View {
        VStack(spacing: 0) {
            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(FabricTheme.warning)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(FabricTheme.warning.fabricTint())
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if lines.isEmpty {
                        ProgressView("Attaching to the exact session…")
                            .frame(maxWidth: .infinity)
                            .padding(.top, 40)
                    }
                    ForEach(lines) { line in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(line.role)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(FabricTheme.textMuted)
                            Text(line.text)
                                .textSelection(.enabled)
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(
                            FabricTheme.surface,
                            in: RoundedRectangle(cornerRadius: FabricTheme.radius)
                        )
                    }
                }
                .padding()
            }
            Divider()
            HStack(alignment: .bottom, spacing: 10) {
                TextField("Send to this exact session", text: $remoteInput, axis: .vertical)
                    .lineLimit(1...5)
                    .textFieldStyle(.roundedBorder)
                Button {
                    Task { await submit() }
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title2)
                }
                .disabled(
                    !attached
                        || remoteInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || appModel.linkController.isWorking
                )
                .frame(minWidth: FabricTheme.minTarget, minHeight: FabricTheme.minTarget)
            }
            .padding(12)
            .background(FabricTheme.canvas)
        }
        .background(FabricTheme.canvas)
        .navigationTitle(session.title)
        .navigationBarTitleDisplayMode(.inline)
        .task { await attachAndPoll() }
        .onDisappear {
            guard attached else { return }
            attached = false
            Task {
                _ = try? await appModel.linkController.invoke(
                    machine: machine,
                    method: "session.detach",
                    params: .map([
                        "session_id": .string(session.id),
                        "controller_id": .string(controllerID),
                    ]),
                    timeoutSeconds: 30
                )
            }
        }
    }

    private func attachAndPoll() async {
        errorMessage = nil
        do {
            let result = try await appModel.linkController.invoke(
                machine: machine,
                method: "session.attach",
                params: .map([
                    "session_id": .string(session.id),
                    "controller_id": .string(controllerID),
                ]),
                timeoutSeconds: 60
            )
            guard let map = result.mapValue,
                  let snapshotSequence = map["snapshot_seq"]?.intValue,
                  let snapshot = map["snapshot"]?.mapValue else {
                throw FabricLinkError.invalidRecord
            }
            eventSequence = snapshotSequence
            lines = transcriptLines(snapshot["messages"])
            attached = true
            while !Task.isCancelled, attached {
                do {
                    let page = try await appModel.linkController.invoke(
                        machine: machine,
                        method: "events.poll",
                        params: .map([
                            "after_event_seq": .integer(eventSequence),
                            "limit": .integer(100),
                            "wait_ms": .integer(0),
                        ]),
                        timeoutSeconds: 30
                    )
                    guard let pageMap = page.mapValue,
                          let highWatermark = pageMap["high_watermark"]?.intValue,
                          let events = pageMap["events"]?.arrayValue,
                          pageMap["snapshot_required"]?.boolValue != nil else {
                        throw FabricLinkError.invalidRecord
                    }
                    if pageMap["snapshot_required"]?.boolValue == true {
                        throw FabricLinkError.requestRejected("snapshot_required")
                    }
                    let deliveredSequences = try events.map { event in
                        guard let sequence = event.mapValue?["event_seq"]?.intValue else {
                            throw FabricLinkError.invalidRecord
                        }
                        return sequence
                    }
                    eventSequence = fabricLinkAdvanceBoundedCursor(
                        afterSequence: eventSequence,
                        deliveredSequences: deliveredSequences,
                        highWatermark: highWatermark
                    )
                    apply(events: events)
                    try await Task.sleep(for: events.isEmpty
                        ? .milliseconds(750)
                        : .milliseconds(100))
                } catch FabricLinkError.requestInFlight {
                    try await Task.sleep(for: .milliseconds(250))
                }
            }
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
            attached = false
        }
    }

    private func submit() async {
        let text = remoteInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        do {
            _ = try await appModel.linkController.invoke(
                machine: machine,
                method: "session.input.submit",
                params: .map([
                    "session_id": .string(session.id),
                    "controller_id": .string(controllerID),
                    "request_id": .string(UUID().uuidString.lowercased()),
                    "text": .string(text),
                ]),
                timeoutSeconds: 60
            )
            remoteInput = ""
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func transcriptLines(_ value: FabricLinkCBOR?) -> [FabricLinkTranscriptLine] {
        (value?.arrayValue ?? []).compactMap { row in
            guard let map = row.mapValue else { return nil }
            let role = map["role"]?.stringValue ?? "event"
            let text = map["text"]?.stringValue
                ?? map["content"]?.stringValue
                ?? ""
            return text.isEmpty ? nil : FabricLinkTranscriptLine(role: role, text: text)
        }.suffix(200)
    }

    private func apply(events: [FabricLinkCBOR]) {
        for event in events {
            guard let outer = event.mapValue,
                  let frame = outer["frame"]?.mapValue,
                  let params = frame["params"]?.mapValue else {
                continue
            }
            let type = params["type"]?.stringValue ?? "event"
            let payload = params["payload"]?.mapValue ?? [:]
            let text = payload["text"]?.stringValue
                ?? payload["content"]?.stringValue
                ?? payload["message"]?.stringValue
                ?? ""
            guard !text.isEmpty else { continue }
            if type == "message.delta",
               lines.last?.role == "assistant-live" {
                lines[lines.count - 1].text += text
            } else {
                lines.append(FabricLinkTranscriptLine(
                    role: type == "message.delta" ? "assistant-live" : type,
                    text: text
                ))
            }
        }
        if lines.count > 200 {
            lines.removeFirst(lines.count - 200)
        }
    }
}

private func fabricLinkDisplayJSON(_ value: FabricLinkCBOR) -> String {
    let object = value.displayValue()
    guard JSONSerialization.isValidJSONObject(object),
          let data = try? JSONSerialization.data(
            withJSONObject: object,
            options: [.prettyPrinted, .sortedKeys]
          ) else {
        return String(describing: object)
    }
    return String(decoding: data, as: UTF8.self)
}
